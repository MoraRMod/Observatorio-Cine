"""Acceso a datos: conexión de sólo lectura al Data Warehouse y utilidades de filtrado."""
import sqlite3
from datetime import date, timedelta

import pandas as pd

from backend.config import DW_DB


def conn() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DW_DB}?mode=ro", uri=True, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def rows(sql: str, params=()) -> list:
    with conn() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def one(sql: str, params=()):
    r = rows(sql, params)
    return r[0] if r else None


def frame(sql: str, params=()) -> pd.DataFrame:
    with conn() as con:
        return pd.read_sql_query(sql, con, params=params)


def data_range():
    r = one("SELECT MIN(fecha_key) a, MAX(fecha_key) b FROM mart_diario_complejo")
    if not r or r["a"] is None:
        return None
    f = lambda k: date(k // 10000, k // 100 % 100, k % 100)
    return f(r["a"]), f(r["b"])


def _month_end(y, m):
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))


class Filtro:
    """Filtros globales del dashboard: periodo (año/trimestre/mes), ciudad y complejo.

    Construye el periodo actual y el periodo de comparación (anterior inmediato de la misma
    longitud o el mismo periodo del año anterior).
    """

    def __init__(self, anio=None, trimestre=None, mes=None, ciudad=None, complejo=None, comparar="anterior"):
        rng = data_range()
        self.min, self.max = rng if rng else (date(2023, 1, 1), date(2025, 12, 31))
        self.anio = int(anio) if anio else None
        self.trimestre = int(trimestre) if trimestre else None
        self.mes = int(mes) if mes else None
        self.ciudad = ciudad or None
        self.complejo = int(complejo) if complejo else None
        self.comparar = comparar
        if self.anio and self.mes:
            self.desde, self.hasta = date(self.anio, self.mes, 1), _month_end(self.anio, self.mes)
            self.unidad = ("mes", 1)
        elif self.anio and self.trimestre:
            m0 = 3 * (self.trimestre - 1) + 1
            self.desde, self.hasta = date(self.anio, m0, 1), _month_end(self.anio, m0 + 2)
            self.unidad = ("mes", 3)
        elif self.anio:
            self.desde, self.hasta = date(self.anio, 1, 1), date(self.anio, 12, 31)
            self.unidad = ("mes", 12)
        else:
            self.desde, self.hasta = self.min, self.max
            self.unidad = None
        self.hasta = min(self.hasta, self.max)

    # ---- periodo de comparación
    def previo(self):
        if not self.unidad:
            return None
        if self.comparar == "anio":
            a = self.desde.replace(year=self.desde.year - 1)
            b = _month_end(self.hasta.year - 1, self.hasta.month)
        else:
            n = self.unidad[1]
            m = self.desde.year * 12 + self.desde.month - 1 - n
            a = date(m // 12, m % 12 + 1, 1)
            e = self.desde.year * 12 + self.desde.month - 2
            b = _month_end(e // 12, e % 12 + 1)
        if b < self.min:
            return None
        return max(a, self.min), b

    def where(self, desde=None, hasta=None, alias_f="m", fecha=True, geo=True):
        """WHERE para tablas con fecha_key y complejo_key."""
        cond, p = [], []
        if fecha:
            a, b = desde or self.desde, hasta or self.hasta
            cond.append(f"{alias_f}.fecha_key BETWEEN ? AND ?")
            p += [int(a.strftime("%Y%m%d")), int(b.strftime("%Y%m%d"))]
        if geo:
            if self.complejo:
                cond.append(f"{alias_f}.complejo_key = ?")
                p.append(self.complejo)
            elif self.ciudad:
                cond.append(f"{alias_f}.complejo_key IN (SELECT complejo_key FROM dim_complejo WHERE ciudad = ?)")
                p.append(self.ciudad)
        return (" WHERE " + " AND ".join(cond)) if cond else "", p

    def where_mes(self, alias="m", desde=None, hasta=None):
        """WHERE para marts mensuales (columna anio_mes)."""
        a, b = desde or self.desde, hasta or self.hasta
        cond, p = [f"{alias}.anio_mes BETWEEN ? AND ?"], [a.strftime("%Y-%m"), b.strftime("%Y-%m")]
        if self.complejo:
            cond.append(f"{alias}.complejo_key = ?")
            p.append(self.complejo)
        elif self.ciudad:
            cond.append(f"{alias}.complejo_key IN (SELECT complejo_key FROM dim_complejo WHERE ciudad = ?)")
            p.append(self.ciudad)
        return " WHERE " + " AND ".join(cond), p

    def describe(self):
        prev = self.previo()
        return dict(desde=str(self.desde), hasta=str(self.hasta),
                    previo=[str(prev[0]), str(prev[1])] if prev else None)
