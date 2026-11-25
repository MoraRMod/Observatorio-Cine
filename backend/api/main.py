"""CAPA 6 · API de Business Intelligence (FastAPI).

Ejecutar:  .venv/bin/python run.py        (o)   .venv/bin/uvicorn backend.api.main:app --port 8765
Documentación interactiva: http://localhost:8765/docs
"""
import json
import math
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import DATA_LABEL, DW_DB, FRONTEND_DIR, PUBLIC_DIRECTORY, ROOT
from backend.services import analytics as an
from backend.services import dwinfo, insights, olap
from backend.services.db import Filtro, one, rows


def _clean(o):
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if hasattr(o, "item"):          # numpy escalares
        return _clean(o.item())
    return o


class SafeJSON(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(_clean(content), ensure_ascii=False, allow_nan=False, default=str).encode("utf-8")


app = FastAPI(title="Cine BI · API del Data Warehouse", version="1.0",
              description="API académica de Business Intelligence. " + DATA_LABEL, default_response_class=SafeJSON)


# --------------------------------------------------------------------- tareas
class Jobs:
    """Ejecuta procesos largos (ETL, entrenamiento) en segundo plano, uno a la vez."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = dict(activo=False, tipo=None, mensaje="", pct=0, resultado=None, error=None, inicio=None, fin=None)

    def start(self, tipo, fn):
        if not self.lock.acquire(blocking=False):
            raise HTTPException(409, f"Ya hay un proceso en ejecución: {self.state['tipo']}")
        self.state = dict(activo=True, tipo=tipo, mensaje="Iniciando…", pct=0, resultado=None, error=None,
                          inicio=datetime.now().isoformat(timespec="seconds"), fin=None)

        def progress(msg, pct):
            self.state.update(mensaje=msg, pct=pct)

        def worker():
            try:
                self.state["resultado"] = fn(progress)
                self.state.update(mensaje="Terminado", pct=100)
            except Exception as exc:  # se reporta al usuario, no se oculta
                traceback.print_exc()
                self.state.update(error=str(exc), mensaje="Error")
            finally:
                self.state.update(activo=False, fin=datetime.now().isoformat(timespec="seconds"))
                self.lock.release()

        threading.Thread(target=worker, daemon=True).start()
        return self.state


jobs = Jobs()


def _etl_and_train(full: bool):
    def run(progress):
        from backend.etl.pipeline import run_etl
        from backend.ml.train import train
        res = run_etl(full=full, progress=lambda m, p: progress("ETL · " + m, int(p * 0.7)))
        out = dict(etl=res)
        if res["estado"] == "EXITOSO" and res["meses"]:
            t = train(progress=lambda m, p: progress("Modelo · " + m, 70 + int(p * 0.3)))
            out["modelo"] = t["run"]
        return out
    return run


def _filtro(anio, trimestre, mes, ciudad, complejo, comparar="anterior"):
    return Filtro(anio=anio, trimestre=trimestre, mes=mes, ciudad=ciudad, complejo=complejo, comparar=comparar)


def F(anio: Optional[int] = None, trimestre: Optional[int] = None, mes: Optional[int] = None,
      ciudad: Optional[str] = None, complejo: Optional[int] = None, comparar: str = "anterior"):
    return dict(anio=anio, trimestre=trimestre, mes=mes, ciudad=ciudad, complejo=complejo, comparar=comparar)


def _require_dw():
    if not DW_DB.exists():
        raise HTTPException(503, "El Data Warehouse no existe todavía. Ejecuta: python run.py --setup")


# ----------------------------------------------------------------------- meta
@app.get("/api/meta", tags=["General"])
def meta():
    _require_dw()
    from backend.services.db import data_range
    try:
        rng = data_range()
    except Exception:
        rng = None
    if not rng:
        raise HTTPException(503, "El Data Warehouse se está cargando o reconstruyendo. Espera a que termine el proceso ETL "
                                 "y recarga la página.")
    a, b = rng
    etl = one("SELECT run_id, fin, estado, mensaje FROM etl_ejecucion WHERE estado <> 'EN PROCESO' ORDER BY run_id DESC LIMIT 1")
    ml = one("SELECT detalle FROM ml_ejecucion WHERE id = 1") if one("SELECT name FROM sqlite_master WHERE name='ml_ejecucion'") else None
    return dict(
        etiqueta=DATA_LABEL, desde=str(a), hasta=str(b),
        anios=[r["anio"] for r in rows("SELECT DISTINCT anio FROM dim_fecha WHERE fecha_key BETWEEN ? AND ? ORDER BY 1",
                                        (int(a.strftime('%Y%m%d')), int(b.strftime('%Y%m%d'))))],
        ciudades=[r["ciudad"] for r in rows("SELECT DISTINCT ciudad FROM dim_complejo ORDER BY 1")],
        complejos=rows("SELECT complejo_key, complejo_codigo, nombre, ciudad, region, tipo_complejo FROM dim_complejo ORDER BY nombre"),
        ultima_etl=etl, modelo=json.loads(ml["detalle"]) if ml else None, tarea=jobs.state,
    )


# ----------------------------------------------------------------- dashboard
@app.get("/api/resumen", tags=["Dashboard"])
def resumen(anio: Optional[int] = None, trimestre: Optional[int] = None, mes: Optional[int] = None,
            ciudad: Optional[str] = None, complejo: Optional[int] = None, comparar: str = "anterior"):
    _require_dw()
    f = _filtro(anio, trimestre, mes, ciudad, complejo, comparar)
    return dict(kpis=an.kpis(f), mensual=an.mensual(f), anual=an.comparativo_anual(f),
                complejos=an.ranking_complejos(f)[:8], peliculas=an.peliculas(f, "ingreso", 8))


@app.get("/api/ventas", tags=["Dashboard"])
def ventas(anio: Optional[int] = None, trimestre: Optional[int] = None, mes: Optional[int] = None,
           ciudad: Optional[str] = None, complejo: Optional[int] = None, comparar: str = "anterior"):
    _require_dw()
    f = _filtro(anio, trimestre, mes, ciudad, complejo, comparar)
    return dict(kpis=an.kpis(f), mensual=an.mensual(f), anual=an.comparativo_anual(f), ciudades=an.ciudades(f),
                semana=an.semana_vs_finde(f))


@app.get("/api/taquilla", tags=["Dashboard"])
def taquilla(anio: Optional[int] = None, trimestre: Optional[int] = None, mes: Optional[int] = None,
             ciudad: Optional[str] = None, complejo: Optional[int] = None):
    _require_dw()
    f = _filtro(anio, trimestre, mes, ciudad, complejo)
    return dict(kpis=an.kpis(f), peliculas_ingreso=an.peliculas(f, "ingreso", 10), peliculas_asistencia=an.peliculas(f, "asistencia", 10),
                generos=an.generos(f), horario=an.ocupacion_horario(f), turnos=an.turnos(f), formatos=an.formatos(f),
                canales=an.canales_mensual(f, "boletos"), promociones=an.promociones(f), semanas=an.semana_exhibicion(f))


@app.get("/api/dulceria", tags=["Dashboard"])
def dulceria(anio: Optional[int] = None, trimestre: Optional[int] = None, mes: Optional[int] = None,
             ciudad: Optional[str] = None, complejo: Optional[int] = None):
    _require_dw()
    f = _filtro(anio, trimestre, mes, ciudad, complejo)
    return dict(kpis=an.kpis(f), mensual=an.mensual(f), categorias=an.dulceria_categorias(f),
                productos=an.dulceria_productos(f), categorias_mensual=an.dulceria_categorias_mensual(f),
                canales=an.canales_mensual(f, "dulceria"), complejos=an.ranking_complejos(f),
                dispersion=an.dulceria_dispersion(f), correlacion=an.correlacion_asistencia_dulceria(f))


@app.get("/api/complejos-peliculas", tags=["Dashboard"])
def complejos_peliculas(anio: Optional[int] = None, trimestre: Optional[int] = None, mes: Optional[int] = None,
                        ciudad: Optional[str] = None, complejo: Optional[int] = None, comparar: str = "anterior"):
    _require_dw()
    f = _filtro(anio, trimestre, mes, ciudad, complejo, comparar)
    return dict(complejos=an.ranking_complejos(f), peliculas=an.tabla_peliculas(f), periodo=f.describe())


@app.get("/api/complejo/{complejo_key}/serie", tags=["Dashboard"])
def serie_complejo(complejo_key: int):
    _require_dw()
    return rows("""SELECT d.anio_mes, SUM(ingreso_taquilla) taquilla, SUM(ingreso_dulceria) dulceria, SUM(asistentes) asistentes,
                          100.0 * SUM(boletos) / SUM(capacidad) ocupacion
                   FROM mart_diario_complejo m JOIN dim_fecha d USING (fecha_key) WHERE complejo_key = ? GROUP BY 1 ORDER BY 1""",
                (complejo_key,))


# ----------------------------------------------------------------------- OLAP
class OlapRequest(BaseModel):
    medida: str
    filas: str
    columnas: Optional[str] = None
    filtros: Dict[str, List[str]] = {}
    orden: str = "valor"
    forzar_detalle: bool = False


@app.get("/api/olap/meta", tags=["OLAP"])
def olap_meta():
    return olap.metadata()


@app.get("/api/olap/valores/{dimension}", tags=["OLAP"])
def olap_valores(dimension: str):
    _require_dw()
    try:
        return olap.valores(dimension)
    except olap.OlapError as e:
        raise HTTPException(400, str(e))


@app.post("/api/olap", tags=["OLAP"])
def olap_query(req: OlapRequest):
    _require_dw()
    try:
        return olap.query(req.medida, req.filas, req.columnas, req.filtros, req.orden, req.forzar_detalle)
    except olap.OlapError as e:
        raise HTTPException(400, str(e))


# --------------------------------------------------------------------- Modelo
@app.get("/api/modelo", tags=["Modelo predictivo"])
def modelo(complejo: Optional[int] = None):
    _require_dw()
    if not one("SELECT name FROM sqlite_master WHERE name='ml_ejecucion'"):
        return dict(entrenado=False)
    info = json.loads(one("SELECT detalle FROM ml_ejecucion WHERE id = 1")["detalle"])
    wc, p = ("WHERE complejo_key = ?", (complejo,)) if complejo else ("", ())
    prueba = rows(f"""SELECT fecha, SUM(ingreso_real) real, SUM(ingreso_pred) pred, SUM(asistencia_real) asistencia_real,
                             SUM(asistencia_pred) asistencia_pred FROM ml_prediccion_prueba {wc} GROUP BY fecha ORDER BY fecha""", p)
    pron = rows(f"""SELECT fecha, SUM(ingreso_pred) pred, SUM(ingreso_li) li, SUM(ingreso_ls) ls, SUM(asistencia_pred) asistencia
                    FROM ml_pronostico {wc} GROUP BY fecha ORDER BY fecha""", p)
    hist = rows(f"""SELECT d.fecha, SUM(ingreso_taquilla + ingreso_dulceria) real, SUM(asistentes) asistentes
                    FROM mart_diario_complejo m JOIN dim_fecha d USING (fecha_key)
                    WHERE d.fecha >= date((SELECT MAX(fecha) FROM ml_prediccion_prueba), '-59 day') {"AND complejo_key = ?" if complejo else ""}
                    GROUP BY d.fecha ORDER BY d.fecha""", p)
    por_complejo = rows("""
        SELECT c.complejo_key, c.nombre, c.ciudad, f.pred7, f.pred30, f.asis30, r.real30_ly, t.real_prueba, t.pred_prueba, l.l30
        FROM dim_complejo c
        JOIN (SELECT complejo_key, SUM(CASE WHEN fecha < date((SELECT MIN(fecha) FROM ml_pronostico), '+7 day') THEN ingreso_pred END) pred7,
                     SUM(ingreso_pred) pred30, SUM(asistencia_pred) asis30 FROM ml_pronostico GROUP BY 1) f USING (complejo_key)
        LEFT JOIN (SELECT complejo_key, SUM(ingreso_taquilla + ingreso_dulceria) real30_ly FROM mart_diario_complejo m JOIN dim_fecha d USING (fecha_key)
                   WHERE d.fecha BETWEEN date((SELECT MIN(fecha) FROM ml_pronostico), '-1 year') AND date((SELECT MAX(fecha) FROM ml_pronostico), '-1 year')
                   GROUP BY 1) r USING (complejo_key)
        LEFT JOIN (SELECT complejo_key, SUM(ingreso_taquilla + ingreso_dulceria) l30 FROM mart_diario_complejo m JOIN dim_fecha d USING (fecha_key)
                   WHERE d.fecha >= date((SELECT MIN(fecha) FROM ml_pronostico), '-30 day') GROUP BY 1) l USING (complejo_key)
        LEFT JOIN (SELECT complejo_key, SUM(ingreso_real) real_prueba, SUM(ingreso_pred) pred_prueba FROM ml_prediccion_prueba
                   WHERE fecha >= date((SELECT MAX(fecha) FROM ml_prediccion_prueba), '-89 day') GROUP BY 1) t USING (complejo_key)
        ORDER BY f.pred30 DESC""")
    for r in por_complejo:
        r["var_anio_anterior"] = 100 * (r["pred30"] / r["real30_ly"] - 1) if r["real30_ly"] else None
        r["var_ultimos30"] = 100 * (r["pred30"] / r["l30"] - 1) if r["l30"] else None
        r["brecha_prueba"] = 100 * (r["real_prueba"] / r["pred_prueba"] - 1) if r["pred_prueba"] else None
    dispersion = rows(f"SELECT ingreso_real real, ingreso_pred pred FROM ml_prediccion_prueba {wc} ORDER BY random() LIMIT 1200", p)
    return dict(entrenado=True, info=info, metricas=rows("SELECT * FROM ml_metricas"),
                importancia=rows("SELECT * FROM ml_importancia ORDER BY importancia DESC"),
                prueba=prueba, pronostico=pron, historico=hist, por_complejo=por_complejo, dispersion=dispersion, tarea=jobs.state)


@app.post("/api/modelo/entrenar", tags=["Modelo predictivo"])
def entrenar():
    _require_dw()
    from backend.ml.train import train
    return jobs.start("Entrenamiento del modelo", lambda progress: dict(modelo=train(progress=progress)["run"]))


# --------------------------------------------------------------------- BI
@app.get("/api/inteligencia", tags=["Inteligencia de negocios"])
def inteligencia():
    _require_dw()
    return insights.generar()


# ------------------------------------------------------------------ DW / ETL
@app.get("/api/dw/esquema", tags=["Data Warehouse"])
def dw_esquema():
    _require_dw()
    return dict(tablas=dwinfo.esquema(), tamano_mb=round(DW_DB.stat().st_size / 1e6, 1), contexto_publico=dwinfo.contexto_publico())


@app.get("/api/dw/validaciones", tags=["Data Warehouse"])
def dw_validaciones():
    _require_dw()
    return dwinfo.validaciones()


@app.get("/api/publico/directorio", tags=["Data Warehouse"])
def directorio_publico():
    if not PUBLIC_DIRECTORY.exists():
        return []
    return json.loads(PUBLIC_DIRECTORY.read_text(encoding="utf-8"))


@app.get("/api/etl", tags=["ETL"])
def etl_info():
    _require_dw()
    from backend.sources.generate_sources import existing_months, next_month
    from backend.config import MAX_SIM_MONTH
    ny, nm = next_month()
    return dict(
        ejecuciones=rows("SELECT * FROM etl_ejecucion ORDER BY run_id DESC LIMIT 50"),
        archivos=rows("SELECT * FROM etl_archivo ORDER BY archivo"),
        rechazos_resumen=rows("""SELECT run_id, fuente, motivo, COUNT(*) n FROM etl_rechazo GROUP BY 1, 2, 3 ORDER BY run_id DESC, n DESC"""),
        meses_fuente=[f"{y}-{m:02d}" for y, m in existing_months()],
        siguiente_mes=f"{ny}-{nm:02d}" if (ny, nm) <= MAX_SIM_MONTH else None,
        tarea=jobs.state,
    )


@app.get("/api/etl/rechazos/{run_id}", tags=["ETL"])
def etl_rechazos(run_id: int, motivo: Optional[str] = None, limite: int = Query(100, le=1000)):
    sql = "SELECT rechazo_id, fuente, archivo, motivo, registro FROM etl_rechazo WHERE run_id = ?"
    p = [run_id]
    if motivo:
        sql += " AND motivo = ?"
        p.append(motivo)
    return rows(sql + f" LIMIT {int(limite)}", p)


class EtlRequest(BaseModel):
    modo: str = "incremental"


@app.post("/api/etl/ejecutar", tags=["ETL"])
def etl_ejecutar(req: EtlRequest):
    return jobs.start("ETL " + req.modo, _etl_and_train(full=req.modo == "completa"))


@app.post("/api/etl/nuevo-mes", tags=["ETL"])
def etl_nuevo_mes():
    from backend.sources.generate_sources import generate_next

    def run(progress):
        progress("Fuentes · generando exportaciones del siguiente mes", 1)
        mes, n = generate_next(verbose=False)
        out = _etl_and_train(full=False)(progress)
        out["mes_generado"], out["registros_fuente"] = mes, n
        return out
    return jobs.start("Simulación de nueva extracción mensual", run)


@app.get("/api/tarea", tags=["ETL"])
def tarea():
    return jobs.state


# ------------------------------------------------------------------ Frontend
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


NO_CACHE = {"Cache-Control": "no-cache"}


@app.get("/", include_in_schema=False)
def landing():
    """Página de inicio original del proyecto (Observatorio Cine)."""
    return FileResponse(ROOT / "index.html", headers=NO_CACHE)


@app.get("/styles.css", include_in_schema=False)
def landing_css():
    return FileResponse(ROOT / "styles.css", headers=NO_CACHE)


@app.get("/app.js", include_in_schema=False)
def landing_js():
    return FileResponse(ROOT / "app.js", headers=NO_CACHE)


@app.get("/data/complejos.json", include_in_schema=False)
def landing_directory():
    return FileResponse(PUBLIC_DIRECTORY, headers=NO_CACHE)


@app.get("/bi", include_in_schema=False)
def plataforma_bi():
    """Plataforma de análisis BI (10 secciones)."""
    return FileResponse(FRONTEND_DIR / "index.html", headers=NO_CACHE)
