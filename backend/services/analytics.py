"""Servicios analíticos: KPIs y consultas para el dashboard (todo se calcula desde el DW)."""
from backend.services.db import Filtro, frame, one, rows

KPI_SQL = """
SELECT COALESCE(SUM(ingreso_taquilla),0) taquilla, COALESCE(SUM(ingreso_dulceria),0) dulceria,
       COALESCE(SUM(costo_dulceria),0) costo_dulceria, COALESCE(SUM(boletos),0) boletos,
       COALESCE(SUM(asistentes),0) asistentes, COALESCE(SUM(capacidad),0) capacidad,
       COALESCE(SUM(funciones),0) funciones, COALESCE(SUM(descuentos),0) descuentos
FROM mart_diario_complejo m {where}"""


def _kpi_values(r):
    total = r["taquilla"] + r["dulceria"]
    div = lambda a, b: a / b if b else None
    return {
        "ingresos_totales": total,
        "ingresos_taquilla": r["taquilla"],
        "ingresos_dulceria": r["dulceria"],
        "boletos": r["boletos"],
        "asistencia": r["asistentes"],
        "ocupacion": div(100 * r["boletos"], r["capacidad"]),
        "ticket_promedio": div(r["taquilla"], r["boletos"]),
        "ingreso_por_asistente": div(total, r["asistentes"]),
        "margen_dulceria": div(100 * (r["dulceria"] - r["costo_dulceria"]), r["dulceria"]),
        "margen_dulceria_mxn": r["dulceria"] - r["costo_dulceria"],
        "funciones": r["funciones"],
    }


def kpis(f: Filtro):
    w, p = f.where()
    cur = _kpi_values(one(KPI_SQL.format(where=w), p))
    prev_rng = f.previo()
    prev = None
    if prev_rng:
        w2, p2 = f.where(*prev_rng)
        prev = _kpi_values(one(KPI_SQL.format(where=w2), p2))
    out = {}
    for k, v in cur.items():
        pv = prev.get(k) if prev else None
        var = None
        if pv not in (None, 0) and v is not None:
            var = (v - pv) if k in ("ocupacion", "margen_dulceria") else 100 * (v - pv) / abs(pv)
        out[k] = dict(actual=v, anterior=pv, variacion=var,
                      unidad_variacion="pp" if k in ("ocupacion", "margen_dulceria") else "%")
    return dict(kpis=out, periodo=f.describe())


def mensual(f: Filtro, todo=True):
    w, p = f.where(desde=f.min if todo else None, hasta=f.max if todo else None)
    df = frame(f"""
        SELECT d.anio_mes, d.anio, d.mes, SUM(ingreso_taquilla) taquilla, SUM(ingreso_dulceria) dulceria,
               SUM(costo_dulceria) costo_dulceria, SUM(boletos) boletos, SUM(asistentes) asistentes,
               SUM(capacidad) capacidad, SUM(funciones) funciones
        FROM mart_diario_complejo m JOIN dim_fecha d USING (fecha_key) {w}
        GROUP BY d.anio_mes ORDER BY d.anio_mes""", p)
    df["total"] = df.taquilla + df.dulceria
    df["ticket_promedio"] = df.taquilla / df.boletos
    df["ocupacion"] = 100 * df.boletos / df.capacidad
    df["gasto_dulceria_asistente"] = df.dulceria / df.asistentes
    df["ingreso_por_asistente"] = df.total / df.asistentes
    df["margen_dulceria"] = 100 * (df.dulceria - df.costo_dulceria) / df.dulceria
    return df.round(4).to_dict("records")


def comparativo_anual(f: Filtro):
    w, p = f.where(desde=f.min, hasta=f.max)
    return rows(f"""
        SELECT d.anio, d.mes, SUM(ingreso_taquilla + ingreso_dulceria) total, SUM(ingreso_taquilla) taquilla,
               SUM(ingreso_dulceria) dulceria, SUM(boletos) boletos
        FROM mart_diario_complejo m JOIN dim_fecha d USING (fecha_key) {w}
        GROUP BY d.anio, d.mes ORDER BY d.anio, d.mes""", p)


def ranking_complejos(f: Filtro):
    w, p = f.where(geo=False)
    cur = frame(f"""
        SELECT c.complejo_key, c.complejo_codigo, c.nombre, c.ciudad, c.region, c.tipo_complejo, c.num_salas,
               SUM(ingreso_taquilla) taquilla, SUM(ingreso_dulceria) dulceria, SUM(costo_dulceria) costo_dulceria,
               SUM(boletos) boletos, SUM(asistentes) asistentes, SUM(capacidad) capacidad, SUM(funciones) funciones
        FROM mart_diario_complejo m JOIN dim_complejo c USING (complejo_key) {w}
        GROUP BY c.complejo_key""", p)
    prev_rng = f.previo()
    if prev_rng:
        w2, p2 = f.where(*prev_rng, geo=False)
        prev = frame(f"SELECT complejo_key, SUM(ingreso_taquilla + ingreso_dulceria) prev FROM mart_diario_complejo m {w2} GROUP BY 1", p2)
        cur = cur.merge(prev, on="complejo_key", how="left")
    else:
        cur["prev"] = None
    cur["total"] = cur.taquilla + cur.dulceria
    cur["ocupacion"] = 100 * cur.boletos / cur.capacidad
    cur["ticket_promedio"] = cur.taquilla / cur.boletos
    cur["gasto_dulceria_asistente"] = cur.dulceria / cur.asistentes
    cur["ingreso_por_sala"] = cur.total / cur.num_salas
    cur["margen_dulceria"] = 100 * (cur.dulceria - cur.costo_dulceria) / cur.dulceria
    cur["variacion"] = 100 * (cur.total - cur.prev) / cur.prev
    if f.ciudad:
        cur = cur[cur.ciudad == f.ciudad]
    return cur.sort_values("total", ascending=False).round(4).where(cur.notna(), None).to_dict("records")


def ciudades(f: Filtro):
    w, p = f.where(geo=False)
    return rows(f"""
        SELECT c.ciudad, c.region, COUNT(DISTINCT c.complejo_key) complejos, SUM(ingreso_taquilla) taquilla,
               SUM(ingreso_dulceria) dulceria, SUM(ingreso_taquilla + ingreso_dulceria) total, SUM(asistentes) asistentes,
               100.0 * SUM(boletos) / SUM(capacidad) ocupacion
        FROM mart_diario_complejo m JOIN dim_complejo c USING (complejo_key) {w}
        GROUP BY c.ciudad ORDER BY total DESC""", p)


def peliculas(f: Filtro, orden="ingreso", limite=10):
    w, p = f.where_mes()
    col = {"ingreso": "ingreso", "asistencia": "asistentes", "ocupacion": "ocupacion"}.get(orden, "ingreso")
    lim = f"LIMIT {int(limite)}" if limite else ""
    return rows(f"""
        SELECT pe.pelicula_key, pe.titulo, pe.genero, pe.clasificacion, pe.tipo_lanzamiento, pe.distribuidora,
               pe.fecha_estreno, pe.duracion_min, SUM(m.funciones) funciones, SUM(m.boletos) boletos,
               SUM(m.asistentes) asistentes, SUM(m.ingreso_taquilla) ingreso,
               100.0 * SUM(m.boletos) / SUM(m.capacidad) ocupacion, 1.0 * SUM(m.asistentes) / SUM(m.funciones) asistentes_funcion,
               COUNT(DISTINCT m.complejo_key) complejos
        FROM mart_pelicula_mensual m JOIN dim_pelicula pe USING (pelicula_key) {w}
        GROUP BY pe.pelicula_key ORDER BY {col} DESC {lim}""", p)


def generos(f: Filtro):
    w, p = f.where_mes()
    return rows(f"""
        SELECT pe.genero, COUNT(DISTINCT pe.pelicula_key) peliculas, SUM(m.funciones) funciones, SUM(m.asistentes) asistentes,
               SUM(m.ingreso_taquilla) ingreso, 100.0 * SUM(m.boletos) / SUM(m.capacidad) ocupacion,
               1.0 * SUM(m.asistentes) / SUM(m.funciones) asistentes_funcion
        FROM mart_pelicula_mensual m JOIN dim_pelicula pe USING (pelicula_key) {w}
        GROUP BY pe.genero ORDER BY ingreso DESC""", p)


def ocupacion_horario(f: Filtro):
    w, p = f.where(alias_f="ff")
    return rows(f"""
        SELECT d.dia_semana, d.nombre_dia, h.hora_num, COUNT(*) funciones,
               100.0 * SUM(ff.boletos_vendidos) / SUM(ff.capacidad) ocupacion, AVG(ff.asistentes) asistentes_funcion
        FROM fact_funciones ff JOIN dim_fecha d USING (fecha_key) JOIN dim_horario h USING (horario_key) {w}
        GROUP BY d.dia_semana, h.hora_num ORDER BY d.dia_semana, h.hora_num""", p)


def turnos(f: Filtro):
    w, p = f.where(alias_f="ff")
    return rows(f"""
        SELECT h.turno, CASE WHEN d.es_fin_semana = 1 THEN 'Fin de semana' ELSE 'Entre semana' END tipo_dia, COUNT(*) funciones,
               100.0 * SUM(ff.boletos_vendidos) / SUM(ff.capacidad) ocupacion, SUM(ff.asistentes) asistentes
        FROM fact_funciones ff JOIN dim_fecha d USING (fecha_key) JOIN dim_horario h USING (horario_key) {w}
        GROUP BY 1, 2 ORDER BY MIN(h.hora_num), 2""", p)


def semana_vs_finde(f: Filtro):
    w, p = f.where()
    por_dia = rows(f"""
        SELECT d.dia_semana, d.nombre_dia, COUNT(DISTINCT d.fecha_key) dias,
               SUM(ingreso_taquilla + ingreso_dulceria) / COUNT(DISTINCT d.fecha_key) ingreso_dia,
               SUM(ingreso_taquilla) / COUNT(DISTINCT d.fecha_key) taquilla_dia,
               SUM(ingreso_dulceria) / COUNT(DISTINCT d.fecha_key) dulceria_dia,
               1.0 * SUM(asistentes) / COUNT(DISTINCT d.fecha_key) asistentes_dia,
               100.0 * SUM(boletos) / SUM(capacidad) ocupacion
        FROM mart_diario_complejo m JOIN dim_fecha d USING (fecha_key) {w}
        GROUP BY d.dia_semana ORDER BY d.dia_semana""", p)
    tipo = rows(f"""
        SELECT CASE WHEN d.dia_semana >= 5 THEN 'Viernes a domingo' ELSE 'Lunes a jueves' END tipo,
               COUNT(DISTINCT d.fecha_key) dias, SUM(ingreso_taquilla + ingreso_dulceria) total,
               SUM(ingreso_taquilla + ingreso_dulceria) / COUNT(DISTINCT d.fecha_key) ingreso_dia,
               100.0 * SUM(boletos) / SUM(capacidad) ocupacion, SUM(ingreso_dulceria) / SUM(asistentes) gasto_dulceria
        FROM mart_diario_complejo m JOIN dim_fecha d USING (fecha_key) {w} GROUP BY 1 ORDER BY 1 DESC""", p)
    return dict(por_dia=por_dia, por_tipo=tipo)


def formatos(f: Filtro):
    w, p = f.where(alias_f="ff")
    occ = {r["formato"]: r for r in rows(f"""
        SELECT s.formato, COUNT(*) funciones, COUNT(DISTINCT s.sala_key) salas,
               100.0 * SUM(ff.boletos_vendidos) / SUM(ff.capacidad) ocupacion
        FROM fact_funciones ff JOIN dim_sala s USING (sala_key) {w} GROUP BY 1""", p)}
    w2, p2 = f.where_mes()
    out = rows(f"""
        SELECT s.formato, SUM(m.boletos) boletos, SUM(m.ingreso) ingreso, SUM(m.ingreso) / SUM(m.boletos) precio_promedio
        FROM mart_taquilla_mensual m JOIN dim_sala s USING (sala_key) {w2} GROUP BY 1 ORDER BY ingreso DESC""", p2)
    for r in out:
        r.update({k: v for k, v in occ.get(r["formato"], {}).items() if k != "formato"})
    return out


def canales_mensual(f: Filtro, fuente="boletos"):
    w, p = f.where_mes(desde=f.min, hasta=f.max)
    if fuente == "dulceria":
        sql = f"""SELECT m.anio_mes, cn.nombre canal, cn.tipo_canal, SUM(m.ingreso) valor, SUM(m.unidades) unidades
                  FROM mart_dulceria_mensual m JOIN dim_canal cn USING (canal_key) {w} GROUP BY 1, 2 ORDER BY 1"""
    else:
        sql = f"""SELECT m.anio_mes, cn.nombre canal, cn.tipo_canal, SUM(m.boletos) valor, SUM(m.ingreso) ingreso
                  FROM mart_taquilla_mensual m JOIN dim_canal cn USING (canal_key) {w} GROUP BY 1, 2 ORDER BY 1"""
    return rows(sql, p)


def promociones(f: Filtro):
    w, p = f.where(alias_f="ff")
    return rows(f"""
        SELECT pr.nombre promocion, pr.tipo, pr.descuento_pct, COUNT(*) funciones, SUM(ff.boletos_vendidos) boletos,
               100.0 * SUM(ff.boletos_vendidos) / SUM(ff.capacidad) ocupacion, AVG(ff.asistentes) asistentes_funcion
        FROM fact_funciones ff JOIN dim_promocion pr USING (promocion_key) {w}
        GROUP BY pr.promocion_key ORDER BY funciones DESC""", p)


def semana_exhibicion(f: Filtro):
    w, p = f.where(alias_f="ff")
    return rows(f"""
        SELECT ff.semana_exhibicion semana, pe.tipo_lanzamiento, AVG(ff.asistentes) asistentes_funcion,
               100.0 * SUM(ff.boletos_vendidos) / SUM(ff.capacidad) ocupacion, COUNT(*) funciones
        FROM fact_funciones ff JOIN dim_pelicula pe USING (pelicula_key) {w} {"AND" if w else "WHERE"} ff.semana_exhibicion <= 10
        GROUP BY 1, 2 ORDER BY 2, 1""", p)


# ---------------------------------------------------------------- Dulcería
def dulceria_categorias(f: Filtro):
    w, p = f.where_mes()
    return rows(f"""
        SELECT pd.categoria, SUM(m.unidades) unidades, SUM(m.ingreso) ingreso, SUM(m.costo) costo, SUM(m.margen) margen,
               100.0 * SUM(m.margen) / SUM(m.ingreso) margen_pct
        FROM mart_dulceria_mensual m JOIN dim_producto pd USING (producto_key) {w} GROUP BY 1 ORDER BY ingreso DESC""", p)


def dulceria_productos(f: Filtro, limite=None):
    w, p = f.where_mes()
    lim = f"LIMIT {int(limite)}" if limite else ""
    return rows(f"""
        SELECT pd.sku, pd.nombre, pd.categoria, pd.precio_lista, SUM(m.unidades) unidades, SUM(m.ingreso) ingreso,
               SUM(m.margen) margen, 100.0 * SUM(m.margen) / SUM(m.ingreso) margen_pct
        FROM mart_dulceria_mensual m JOIN dim_producto pd USING (producto_key) {w} GROUP BY 1 ORDER BY unidades DESC {lim}""", p)


def dulceria_categorias_mensual(f: Filtro):
    w, p = f.where_mes(desde=f.min, hasta=f.max)
    return rows(f"""
        SELECT m.anio_mes, pd.categoria, SUM(m.ingreso) ingreso, SUM(m.unidades) unidades
        FROM mart_dulceria_mensual m JOIN dim_producto pd USING (producto_key) {w} GROUP BY 1, 2 ORDER BY 1""", p)


def dulceria_dispersion(f: Filtro):
    """Asistencia vs. ingreso de dulcería por complejo-día (muestra sistemática)."""
    w, p = f.where()
    return rows(f"""
        SELECT m.fecha_key, c.nombre complejo, c.tipo_complejo, m.asistentes, m.ingreso_dulceria
        FROM mart_diario_complejo m JOIN dim_complejo c USING (complejo_key) {w}
        {"AND" if w else "WHERE"} (m.fecha_key % 7) = 0 LIMIT 3000""", p)


def correlacion_asistencia_dulceria(f: Filtro):
    df = frame("SELECT asistentes, ingreso_dulceria FROM mart_diario_complejo m" + f.where()[0], f.where()[1])
    if len(df) < 3:
        return None
    return float(df.asistentes.corr(df.ingreso_dulceria))


# ---------------------------------------------------------------- Tablas
def tabla_peliculas(f: Filtro):
    return peliculas(f, orden="ingreso", limite=None)
