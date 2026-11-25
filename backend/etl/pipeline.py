"""CAPAS 2-5 · Proceso ETL: Fuentes -> Staging -> Transformación -> Data Warehouse -> Data Marts.

Uso:
    python -m backend.etl.pipeline                 # carga incremental (sólo archivos nuevos o modificados)
    python -m backend.etl.pipeline --completa      # reconstruye el DW desde cero

Carga incremental: cada archivo mensual se identifica por su checksum MD5 en `etl_archivo`.
Si un archivo de un mes es nuevo o cambió, se reprocesa el mes completo: primero se
eliminan los hechos de ese mes y después se insertan de nuevo (operación idempotente,
sin duplicados aunque el proceso se ejecute varias veces).
"""
import argparse
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from backend import calendario as cal
from backend.config import CAL_END, CAL_START, DW_DB, SOURCES_DIR, STAGING_DB

SCHEMA = Path(__file__).with_name("schema.sql")
DW_TABLES = ["mart_dulceria_mensual", "mart_taquilla_mensual", "mart_pelicula_mensual", "mart_diario_complejo",
             "fact_ventas_dulceria", "fact_ventas_boletos", "fact_funciones", "dim_promocion", "dim_canal",
             "dim_producto", "dim_horario", "dim_pelicula", "dim_sala", "dim_complejo", "dim_fecha"]


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


CANAL_MAP = {"taquilla": "TAQ", "kiosko": "KIO", "kiosco": "KIO", "kiosko de autoservicio": "KIO",
             "app": "APP", "aplicacion": "APP", "aplicacion movil": "APP", "web": "WEB", "pagina web": "WEB",
             "mostrador": "MOS", "dulceria": "MOS", "mostrador de dulceria": "MOS",
             "servicio en sala": "SAL", "sala vip": "SAL"}


def connect(path=DW_DB) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=60)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    return con


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Stats:
    def __init__(self):
        self.d = {}

    def add(self, fuente, campo, n):
        self.d.setdefault(fuente, {}).setdefault(campo, 0)
        self.d[fuente][campo] += int(n)

    def total(self, campo):
        return sum(v.get(campo, 0) for v in self.d.values())


class ETL:
    def __init__(self, progress=None):
        self.progress = progress or (lambda msg, pct: None)
        self.stats = Stats()
        self.rejects = []      # (fuente, archivo, motivo, registro_json)

    # ------------------------------------------------------------------ util
    def reject(self, fuente, archivo, df, motivo):
        if len(df):
            self.stats.add(fuente, "rechazados", len(df))
            for rec in df.astype(str).to_dict("records"):
                self.rejects.append((fuente, archivo, motivo, json.dumps(rec, ensure_ascii=False)))

    # =============================================================== EXTRACT
    def extract(self, con, full: bool):
        """Detecta archivos nuevos/modificados y los copia al área de staging."""
        loaded = {} if full else dict(con.execute("SELECT archivo, checksum FROM etl_archivo"))
        months, files = set(), {}
        for folder in ("programacion", "taquilla", "dulceria"):
            for p in sorted((SOURCES_DIR / folder).glob("*.csv")):
                rel = f"{folder}/{p.name}"
                chk = md5(p)
                files[rel] = (p, chk)
                if loaded.get(rel) != chk:
                    months.add(p.stem.rsplit("_", 1)[1])
        cat_changed = full
        for p in sorted((SOURCES_DIR / "catalogos").glob("*.json")):
            rel = f"catalogos/{p.name}"
            chk = md5(p)
            files[rel] = (p, chk)
            if loaded.get(rel) != chk:
                cat_changed = True
        return sorted(months), cat_changed, files

    def stage(self, month: str):
        """Lee los CSV crudos de un mes (todo como texto) y los deja en staging.sqlite."""
        raw = {
            "funciones": pd.read_csv(SOURCES_DIR / "programacion" / f"funciones_{month}.csv", dtype=str, keep_default_na=False),
            "boletos": pd.read_csv(SOURCES_DIR / "taquilla" / f"ventas_boletos_{month}.csv", dtype=str, keep_default_na=False),
            "dulceria": pd.read_csv(SOURCES_DIR / "dulceria" / f"ventas_dulceria_{month}.csv", dtype=str, keep_default_na=False),
        }
        with sqlite3.connect(STAGING_DB) as st:
            for name, df in raw.items():
                df.assign(_mes=month, _extraido_en=datetime.now().isoformat(timespec="seconds")) \
                  .to_sql(f"stg_{name}", st, if_exists="replace", index=False)
                self.stats.add(name, "extraidos", len(df))
        return raw

    # ============================================================= TRANSFORM
    @staticmethod
    def build_dim_fecha():
        rows, d = [], CAL_START
        while d <= CAL_END:
            hol = cal.holidays(d.year).get(d)
            vac = cal.vacation_name(d)
            rows.append((int(d.strftime("%Y%m%d")), d.isoformat(), d.day, d.isoweekday(), cal.DIAS[d.weekday()],
                         int(d.weekday() >= 5), d.isocalendar()[1], d.month, cal.MESES[d.month - 1],
                         (d.month - 1) // 3 + 1, d.year, d.strftime("%Y-%m"), cal.season(d), int(bool(vac)), vac,
                         int(bool(hol)), int(bool(hol and hol[1])), hol[0] if hol else None))
            d += timedelta(days=1)
        return rows

    @staticmethod
    def build_dim_horario():
        rows = []
        for h in range(9, 24):
            for m in range(0, 60, 5):
                turno = ("Matutino" if h < 14 else "Vespertino" if h < 18 else "Nocturno" if h < 22 else "Trasnoche")
                clase = "Pico" if 18 <= h < 22 else "Normal" if 15 <= h < 18 or h >= 22 else "Valle"
                rows.append((h * 100 + m, f"{h:02d}:{m:02d}", h, turno, clase))
        return rows

    def transform_funciones(self, df, month, keys):
        src, fname = "funciones", f"programacion/funciones_{month}.csv"
        df = df.apply(lambda c: c.str.strip())
        dup = df.duplicated(keep="first")
        self.reject(src, fname, df[dup], "Registro duplicado")
        df = df[~dup]
        dup = df.duplicated("funcion_id", keep="first")
        self.reject(src, fname, df[dup], "Identificador de función duplicado")
        df = df[~dup].copy()
        df["_fecha"] = pd.to_datetime(df["fecha"], format="%Y-%m-%d", errors="coerce")
        bad = df["_fecha"].isna()
        self.reject(src, fname, df[bad].drop(columns="_fecha"), "Fecha inválida")
        df = df[~bad]
        hm = df["hora_inicio"].str.extract(r"^(\d{2}):(\d{2})$").astype(float)
        ok = hm[0].between(0, 23) & hm[1].between(0, 59)
        self.reject(src, fname, df[~ok].drop(columns="_fecha"), "Hora de inicio inválida")
        df, hm = df[ok].copy(), hm[ok]
        df["horario_key"] = (hm[0] * 100 + (hm[1] // 5) * 5).astype(int)
        for col, mp, motivo in (("complejo", keys["complejo"], "Complejo inexistente"),
                                ("sala", keys["sala"], "Sala inexistente"),
                                ("pelicula", keys["pelicula"], "Película inexistente"),
                                ("promocion", keys["promocion"], "Promoción inexistente")):
            df[col + "_key"] = df[col].map(mp)
            bad = df[col + "_key"].isna()
            self.reject(src, fname, df[bad].drop(columns=["_fecha"]), motivo)
            df = df[~bad].copy()
        bad = df["sala_key"].map(keys["sala_complejo"]) != df["complejo_key"]
        self.reject(src, fname, df[bad].drop(columns=["_fecha"]), "La sala no pertenece al complejo")
        df = df[~bad].copy()
        cap = pd.to_numeric(df["capacidad"], errors="coerce")
        dim_cap = df["sala_key"].map(keys["sala_capacidad"])
        fix = cap != dim_cap
        self.stats.add(src, "corregidos", fix.sum())
        df["capacidad"] = dim_cap.astype(int)
        df["asistentes_registrados"] = pd.to_numeric(df["asistentes_registrados"], errors="coerce")
        df["funcion_id"] = df["funcion_id"].astype("int64")
        df["fecha_key"] = df["_fecha"].dt.strftime("%Y%m%d").astype(int)
        estreno = pd.to_datetime(df["pelicula_key"].map(keys["pelicula_estreno"]))
        df["semana_exhibicion"] = ((df["_fecha"] - estreno).dt.days // 7 + 1).clip(lower=1).astype(int)
        return df

    def transform_boletos(self, df, month, fun):
        src, fname = "boletos", f"taquilla/ventas_boletos_{month}.csv"
        dup = df.duplicated(keep="first")
        self.reject(src, fname, df[dup], "Registro duplicado")
        df = df[~dup]
        dup = df.duplicated("venta_id", keep="first")
        self.reject(src, fname, df[dup], "Identificador de venta duplicado")
        df = df[~dup].copy()
        canon = df["canal"].map(_norm)
        df["canal_codigo"] = canon.map(CANAL_MAP)
        self.stats.add(src, "corregidos", ((df["canal"] != df["canal"].str.strip()) |
                                           ~df["canal"].isin(["Taquilla", "Kiosko", "App", "Web"])).sum())
        bad = df["canal_codigo"].isna()
        self.reject(src, fname, df[bad].drop(columns="canal_codigo"), "Canal desconocido")
        df = df[~bad].copy()
        df["boletos"] = pd.to_numeric(df["boletos"], errors="coerce")
        bad = df["boletos"].isna() | (df["boletos"] <= 0)
        self.reject(src, fname, df[bad].drop(columns="canal_codigo"), "Cantidad de boletos no válida")
        df = df[~bad].copy()
        df["funcion_id"] = pd.to_numeric(df["funcion_id"], errors="coerce")
        bad = ~df["funcion_id"].isin(fun["funcion_id"])
        self.reject(src, fname, df[bad].drop(columns="canal_codigo"), "Función inexistente (clave huérfana)")
        df = df[~bad].copy()
        df["funcion_id"] = df["funcion_id"].astype("int64")
        df["precio_unitario"] = pd.to_numeric(df["precio_unitario"], errors="coerce")
        missing = df["precio_unitario"].isna() | (df["precio_unitario"] <= 0)
        if missing.any():   # imputación: precio de lista de la misma función en otros canales
            ref = df[~missing].groupby("funcion_id")["precio_unitario"].median()
            df.loc[missing, "precio_unitario"] = df.loc[missing, "funcion_id"].map(ref)
            self.stats.add(src, "corregidos", df.loc[missing, "precio_unitario"].notna().sum())
        bad = df["precio_unitario"].isna()
        self.reject(src, fname, df[bad].drop(columns="canal_codigo"), "Precio faltante sin referencia")
        df = df[~bad].copy()
        df["descuento_pct"] = pd.to_numeric(df["descuento_pct"], errors="coerce").fillna(0).clip(0, 1)
        f = fun.set_index("funcion_id")
        for col in ("fecha_key", "complejo_key", "pelicula_key", "sala_key", "horario_key", "promocion_key"):
            df[col] = df["funcion_id"].map(f[col]).astype(int)
        # Validación: los boletos de una función no pueden exceder su capacidad
        tot = df.groupby("funcion_id")["boletos"].transform("sum")
        bad = tot > df["funcion_id"].map(f["capacidad"])
        self.reject(src, fname, df[bad][["venta_id", "funcion_id", "canal", "boletos"]], "Boletos exceden la capacidad de la sala")
        df = df[~bad].copy()
        df["descuento_unitario"] = (df["precio_unitario"] * df["descuento_pct"]).round(2)
        df["monto_descuento"] = (df["descuento_unitario"] * df["boletos"]).round(2)
        df["ingreso_total"] = ((df["precio_unitario"] - df["descuento_unitario"]) * df["boletos"]).round(2)
        df["venta_id"] = df["venta_id"].astype("int64")
        df["boletos"] = df["boletos"].astype(int)
        return df

    def finish_funciones(self, fun, bol):
        sold = bol.groupby("funcion_id")["boletos"].sum()
        fun = fun.copy()
        fun["boletos_vendidos"] = fun["funcion_id"].map(sold).fillna(0).astype(int)
        a = fun["asistentes_registrados"]
        bad = a.isna() | (a < 0) | (a > fun["boletos_vendidos"])
        self.stats.add("funciones", "corregidos", bad.sum())
        fun["asistentes"] = np.where(bad, fun["boletos_vendidos"], a).astype(int)
        fun["asientos_disponibles"] = fun["capacidad"] - fun["boletos_vendidos"]
        fun["porcentaje_ocupacion"] = (100 * fun["boletos_vendidos"] / fun["capacidad"]).round(2)
        return fun

    def transform_dulceria(self, df, month, keys, catalogo_productos):
        src, fname = "dulceria", f"dulceria/ventas_dulceria_{month}.csv"
        dup = df.duplicated(keep="first")
        self.reject(src, fname, df[dup], "Registro duplicado")
        df = df[~dup].copy()
        f1 = pd.to_datetime(df["fecha"], format="%Y-%m-%d", errors="coerce")
        f2 = pd.to_datetime(df["fecha"], format="%d/%m/%Y", errors="coerce")
        self.stats.add(src, "corregidos", (f1.isna() & f2.notna()).sum())
        df["_fecha"] = f1.fillna(f2)
        bad = df["_fecha"].isna()
        self.reject(src, fname, df[bad].drop(columns="_fecha"), "Fecha inválida")
        df = df[~bad].copy()
        sku = df["sku"].str.strip().str.upper()
        self.stats.add(src, "corregidos", (sku != df["sku"]).sum())
        df["sku"] = sku
        df["canal_codigo"] = df["canal"].map(_norm).map(CANAL_MAP)
        for col, mp, motivo in (("sku", keys["producto"], "Producto inexistente"),
                                ("complejo", keys["complejo"], "Complejo inexistente"),
                                ("canal_codigo", keys["canal"], "Canal desconocido")):
            df[col + "_key"] = df[col].map(mp)
            bad = df[col + "_key"].isna()
            self.reject(src, fname, df[bad][["fecha", "complejo", "sku", "canal", "unidades", "precio_unitario"]], motivo)
            df = df[~bad].copy()
        df["fecha_key"] = df["_fecha"].dt.strftime("%Y%m%d").astype(int)
        dup = df.duplicated(["fecha_key", "complejo_key", "sku_key", "canal_codigo_key"], keep="first")
        self.reject(src, fname, df[dup][["fecha", "complejo", "sku", "canal", "unidades"]], "Duplicado tras normalizar")
        df = df[~dup].copy()
        df["unidades"] = pd.to_numeric(df["unidades"], errors="coerce")
        bad = df["unidades"].isna() | (df["unidades"] <= 0)
        self.reject(src, fname, df[bad][["fecha", "complejo", "sku", "canal", "unidades"]], "Unidades no válidas")
        df = df[~bad].copy()
        year = df["_fecha"].dt.year.astype(str)
        lista = [catalogo_productos[s]["precio_lista"].get(y) for s, y in zip(df["sku"], year)]
        costo = [catalogo_productos[s]["costo_unitario"].get(y) for s, y in zip(df["sku"], year)]
        df["precio_unitario"] = pd.to_numeric(df["precio_unitario"], errors="coerce")
        miss = df["precio_unitario"].isna() | (df["precio_unitario"] <= 0)
        self.stats.add(src, "corregidos", miss.sum())
        df.loc[miss, "precio_unitario"] = pd.Series(lista, index=df.index)[miss]
        df["costo_unitario"] = pd.Series(costo, index=df.index).astype(float)
        df["unidades"] = df["unidades"].astype(int)
        df["ingreso_total"] = (df["unidades"] * df["precio_unitario"]).round(2)
        df["costo_total"] = (df["unidades"] * df["costo_unitario"]).round(2)
        df["margen_bruto"] = (df["ingreso_total"] - df["costo_total"]).round(2)
        return df

    # ================================================================== LOAD
    def load_dimensions(self, con, cat_changed):
        cat = {n: json.loads((SOURCES_DIR / "catalogos" / f"{n}.json").read_text(encoding="utf-8"))
               for n in ("complejos", "salas", "peliculas", "productos", "promociones", "canales")}
        n = 0
        if cat_changed or not con.execute("SELECT COUNT(*) FROM dim_fecha").fetchone()[0]:
            fechas = self.build_dim_fecha()
            con.executemany("INSERT OR REPLACE INTO dim_fecha VALUES (" + ",".join("?" * 18) + ")", fechas)
            horarios = self.build_dim_horario()
            con.executemany("INSERT OR REPLACE INTO dim_horario VALUES (?,?,?,?,?)", horarios)
            n += len(fechas) + len(horarios)
            up = lambda t, k, cols: (f"INSERT INTO {t} ({k},{','.join(cols)}) VALUES ({','.join('?' * (len(cols) + 1))}) "
                                     f"ON CONFLICT({k}) DO UPDATE SET " + ",".join(f"{c}=excluded.{c}" for c in cols))
            cols = ["nombre", "ciudad", "estado", "region", "tipo_complejo", "fecha_apertura", "num_salas"]
            con.executemany(up("dim_complejo", "complejo_codigo", cols), [[c["codigo"]] + [c[k] for k in cols] for c in cat["complejos"]])
            ck = dict(con.execute("SELECT complejo_codigo, complejo_key FROM dim_complejo"))
            con.executemany(up("dim_sala", "sala_codigo", ["complejo_key", "numero", "formato", "capacidad"]),
                            [[s["codigo"], ck[s["complejo"]], s["numero"], s["formato"], s["capacidad"]] for s in cat["salas"]])
            cols = ["titulo", "genero", "clasificacion", "duracion_min", "fecha_estreno", "distribuidora", "tipo_lanzamiento"]
            con.executemany(up("dim_pelicula", "pelicula_codigo", cols), [[p["codigo"]] + [p[k] for k in cols] for p in cat["peliculas"]])
            cur = str(max(int(y) for y in cat["productos"][0]["precio_lista"]))
            yr = str(min(int(cur), date.today().year))
            con.executemany(up("dim_producto", "sku", ["nombre", "categoria", "precio_lista", "costo_unitario", "exclusivo_vip"]),
                            [[p["sku"], p["nombre"], p["categoria"], p["precio_lista"][yr], p["costo_unitario"][yr], int(p["exclusivo_vip"])]
                             for p in cat["productos"]])
            cols = ["nombre", "tipo", "descuento_pct", "vigencia_inicio", "vigencia_fin"]
            con.executemany(up("dim_promocion", "promocion_codigo", cols), [[p["codigo"]] + [p[k] for k in cols] for p in cat["promociones"]])
            con.executemany(up("dim_canal", "canal_codigo", ["nombre", "tipo_canal", "vende_boletos", "vende_dulceria"]),
                            [[c["codigo"], c["nombre"], c["tipo"], int(c["vende_boletos"]), int(c["vende_dulceria"])] for c in cat["canales"]])
            n += sum(len(cat[k]) for k in cat)
            self.stats.add("catalogos", "extraidos", sum(len(cat[k]) for k in cat))
            self.stats.add("catalogos", "cargados", n)
        q = lambda sql: dict(con.execute(sql))
        keys = dict(
            complejo=q("SELECT complejo_codigo, complejo_key FROM dim_complejo"),
            sala=q("SELECT sala_codigo, sala_key FROM dim_sala"),
            sala_complejo=q("SELECT sala_key, complejo_key FROM dim_sala"),
            sala_capacidad=q("SELECT sala_key, capacidad FROM dim_sala"),
            pelicula=q("SELECT pelicula_codigo, pelicula_key FROM dim_pelicula"),
            pelicula_estreno=q("SELECT pelicula_key, fecha_estreno FROM dim_pelicula"),
            promocion=q("SELECT promocion_codigo, promocion_key FROM dim_promocion"),
            producto=q("SELECT sku, producto_key FROM dim_producto"),
            canal=q("SELECT canal_codigo, canal_key FROM dim_canal"),
        )
        return keys, {p["sku"]: p for p in cat["productos"]}

    def load_month(self, con, month, fun, bol, dul, keys):
        a, b = int(month.replace("-", "") + "01"), int(month.replace("-", "") + "31")
        for t in ("fact_ventas_boletos", "fact_ventas_dulceria", "fact_funciones"):
            con.execute(f"DELETE FROM {t} WHERE fecha_key BETWEEN ? AND ?", (a, b))
        cols = ["funcion_id", "fecha_key", "complejo_key", "pelicula_key", "sala_key", "horario_key", "promocion_key",
                "semana_exhibicion", "capacidad", "boletos_vendidos", "asistentes", "asientos_disponibles", "porcentaje_ocupacion"]
        con.executemany(f"INSERT INTO fact_funciones ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        fun[cols].astype(object).itertuples(index=False, name=None))
        bol = bol.assign(canal_key=bol["canal_codigo"].map(keys["canal"]).astype(int))
        cols_src = ["venta_id", "funcion_id", "fecha_key", "complejo_key", "pelicula_key", "sala_key", "horario_key",
                    "canal_key", "promocion_key", "boletos", "precio_unitario", "descuento_unitario", "monto_descuento", "ingreso_total"]
        con.executemany("INSERT INTO fact_ventas_boletos VALUES (" + ",".join("?" * 14) + ")",
                        bol[cols_src].astype(object).itertuples(index=False, name=None))
        cols_d = ["fecha_key", "complejo_key", "sku_key", "canal_codigo_key", "unidades", "precio_unitario", "costo_unitario",
                  "ingreso_total", "costo_total", "margen_bruto"]
        con.executemany("INSERT INTO fact_ventas_dulceria VALUES (" + ",".join("?" * 10) + ")",
                        dul[cols_d].astype(object).itertuples(index=False, name=None))
        self.stats.add("funciones", "cargados", len(fun))
        self.stats.add("boletos", "cargados", len(bol))
        self.stats.add("dulceria", "cargados", len(dul))
        for k, df in (("funciones", fun), ("boletos", bol), ("dulceria", dul)):
            self.stats.add(k, "transformados", len(df))
        self.refresh_marts(con, month)

    @staticmethod
    def refresh_marts(con, month):
        a, b = int(month.replace("-", "") + "01"), int(month.replace("-", "") + "31")
        for t in ("mart_diario_complejo",):
            con.execute(f"DELETE FROM {t} WHERE fecha_key BETWEEN ? AND ?", (a, b))
        for t in ("mart_pelicula_mensual", "mart_taquilla_mensual", "mart_dulceria_mensual"):
            con.execute(f"DELETE FROM {t} WHERE anio_mes = ?", (month,))
        con.execute("""
        INSERT INTO mart_diario_complejo
        WITH f AS (SELECT fecha_key, complejo_key, COUNT(*) funciones, SUM(capacidad) capacidad,
                          SUM(boletos_vendidos) boletos, SUM(asistentes) asistentes,
                          COUNT(DISTINCT pelicula_key) peliculas,
                          COUNT(DISTINCT CASE WHEN semana_exhibicion = 1 THEN pelicula_key END) estrenos
                   FROM fact_funciones WHERE fecha_key BETWEEN :a AND :b GROUP BY 1, 2),
             v AS (SELECT fecha_key, complejo_key, SUM(ingreso_total) ingreso, SUM(monto_descuento) descuentos
                   FROM fact_ventas_boletos WHERE fecha_key BETWEEN :a AND :b GROUP BY 1, 2),
             d AS (SELECT fecha_key, complejo_key, SUM(ingreso_total) ingreso, SUM(costo_total) costo,
                          SUM(unidades_vendidas) unidades
                   FROM fact_ventas_dulceria WHERE fecha_key BETWEEN :a AND :b GROUP BY 1, 2)
        SELECT f.fecha_key, f.complejo_key, f.funciones, f.capacidad, f.boletos, f.asistentes,
               COALESCE(v.ingreso, 0), COALESCE(v.descuentos, 0), COALESCE(d.ingreso, 0), COALESCE(d.costo, 0),
               COALESCE(d.unidades, 0), f.peliculas, f.estrenos
        FROM f LEFT JOIN v USING (fecha_key, complejo_key) LEFT JOIN d USING (fecha_key, complejo_key)""", {"a": a, "b": b})
        con.execute("""
        INSERT INTO mart_pelicula_mensual
        SELECT :m, f.complejo_key, f.pelicula_key, COUNT(*), SUM(capacidad), SUM(boletos_vendidos), SUM(asistentes),
               COALESCE(SUM(v.ingreso), 0)
        FROM fact_funciones f
        LEFT JOIN (SELECT funcion_id, SUM(ingreso_total) ingreso FROM fact_ventas_boletos
                   WHERE fecha_key BETWEEN :a AND :b GROUP BY 1) v USING (funcion_id)
        WHERE f.fecha_key BETWEEN :a AND :b GROUP BY f.complejo_key, f.pelicula_key""", {"a": a, "b": b, "m": month})
        con.execute("""
        INSERT INTO mart_taquilla_mensual
        SELECT :m, complejo_key, sala_key, canal_key, promocion_key, SUM(boletos_vendidos), SUM(ingreso_total), SUM(monto_descuento)
        FROM fact_ventas_boletos WHERE fecha_key BETWEEN :a AND :b GROUP BY 2, 3, 4, 5""", {"a": a, "b": b, "m": month})
        con.execute("""
        INSERT INTO mart_dulceria_mensual
        SELECT :m, complejo_key, producto_key, canal_key, SUM(unidades_vendidas), SUM(ingreso_total), SUM(costo_total), SUM(margen_bruto)
        FROM fact_ventas_dulceria WHERE fecha_key BETWEEN :a AND :b GROUP BY 2, 3, 4""", {"a": a, "b": b, "m": month})

    # =================================================================== RUN
    def run(self, full=False) -> dict:
        t0 = time.time()
        DW_DB.parent.mkdir(parents=True, exist_ok=True)
        con = connect()
        con.executescript(SCHEMA.read_text(encoding="utf-8"))   # garantiza las tablas de control
        cur = con.execute("INSERT INTO etl_ejecucion (inicio, modo, estado) VALUES (?, ?, 'EN PROCESO')",
                          (datetime.now().isoformat(timespec="seconds"), "completa" if full else "incremental"))
        run_id = cur.lastrowid
        con.commit()
        try:
            if full:
                # Reconstrucción: se eliminan hechos, dimensiones, marts y resultados del modelo
                # (que dependen de las dimensiones); la bitácora del ETL se conserva.
                self.progress("Reconstrucción completa: eliminando tablas del DW", 1)
                con.execute("PRAGMA foreign_keys = OFF")
                ml = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ml_%'")]
                for t in ml + DW_TABLES:
                    con.execute(f"DROP TABLE IF EXISTS {t}")
                con.execute("DELETE FROM etl_archivo")
                con.commit()
                con.execute("PRAGMA foreign_keys = ON")
                con.executescript(SCHEMA.read_text(encoding="utf-8"))
            self.progress("Extracción: detectando archivos nuevos o modificados", 2)
            months, cat_changed, files = self.extract(con, full)
            keys, catalogo_productos = self.load_dimensions(con, cat_changed)
            con.commit()
            for i, month in enumerate(months):
                self.progress(f"Procesando {month} ({i + 1}/{len(months)})", 5 + int(90 * i / max(1, len(months))))
                raw = self.stage(month)
                fun = self.transform_funciones(raw["funciones"], month, keys)
                bol = self.transform_boletos(raw["boletos"], month, fun)
                fun = self.finish_funciones(fun, bol)
                dul = self.transform_dulceria(raw["dulceria"], month, keys, catalogo_productos)
                self.load_month(con, month, fun, bol, dul, keys)
                for folder, prefix in (("programacion", "funciones"), ("taquilla", "ventas_boletos"), ("dulceria", "ventas_dulceria")):
                    rel = f"{folder}/{prefix}_{month}.csv"
                    con.execute("INSERT OR REPLACE INTO etl_archivo VALUES (?,?,?,?,?)",
                                (rel, files[rel][1], len(raw[prefix.split("_")[-1]]), run_id, datetime.now().isoformat(timespec="seconds")))
                con.commit()
            for rel, (p, chk) in files.items():
                if rel.startswith("catalogos/"):
                    con.execute("INSERT OR REPLACE INTO etl_archivo VALUES (?,?,?,?,?)",
                                (rel, chk, len(json.loads(p.read_text(encoding="utf-8"))), run_id, datetime.now().isoformat(timespec="seconds")))
            self.progress("Validando integridad referencial", 96)
            fk = con.execute("PRAGMA foreign_key_check").fetchall()
            if fk:
                raise RuntimeError(f"Violaciones de integridad referencial: {len(fk)}")
            con.executemany("INSERT INTO etl_rechazo (run_id, fuente, archivo, motivo, registro) VALUES (?,?,?,?,?)",
                            [(run_id,) + r for r in self.rejects])
            s = self.stats
            estado = "EXITOSO" if months or cat_changed else "SIN CAMBIOS"
            msg = (f"{len(months)} mes(es) procesado(s): {', '.join(months)}" if months
                   else "No se detectaron archivos nuevos o modificados; el DW ya está actualizado.")
            con.execute("""UPDATE etl_ejecucion SET fin=?, duracion_seg=?, archivos_procesados=?, extraidos=?, transformados=?,
                           cargados=?, rechazados=?, corregidos=?, estado=?, mensaje=?, detalle=? WHERE run_id=?""",
                        (datetime.now().isoformat(timespec="seconds"), round(time.time() - t0, 2), len(months) * 3,
                         s.total("extraidos"), s.total("transformados"), s.total("cargados"), s.total("rechazados"),
                         s.total("corregidos"), estado, msg, json.dumps(s.d, ensure_ascii=False), run_id))
            con.commit()
            con.execute("PRAGMA optimize")
            self.progress("Proceso terminado", 100)
            return dict(run_id=run_id, estado=estado, mensaje=msg, meses=months, detalle=s.d,
                        duracion_seg=round(time.time() - t0, 2))
        except Exception as exc:
            con.rollback()
            con.execute("UPDATE etl_ejecucion SET fin=?, duracion_seg=?, estado='ERROR', mensaje=? WHERE run_id=?",
                        (datetime.now().isoformat(timespec="seconds"), round(time.time() - t0, 2), str(exc)[:500], run_id))
            con.commit()
            raise
        finally:
            con.close()


def run_etl(full=False, progress=None) -> dict:
    return ETL(progress).run(full=full)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--completa", action="store_true", help="reconstruye el Data Warehouse desde cero")
    args = ap.parse_args()
    res = run_etl(full=args.completa, progress=lambda m, p: print(f"[{p:3d}%] {m}"))
    print(json.dumps({k: v for k, v in res.items() if k != "detalle"}, ensure_ascii=False, indent=1))
    print(json.dumps(res["detalle"], ensure_ascii=False, indent=1))
