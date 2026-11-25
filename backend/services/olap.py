"""Motor OLAP (ROLAP sobre el modelo en estrella).

Traduce una consulta multidimensional {medida, filas, columnas, filtros} a SQL sobre la tabla
de hechos adecuada.  Soporta roll-up / drill-down (jerarquías), slice (un filtro),
dice (varios filtros) y pivot (intercambio de filas y columnas).

Las dimensiones conformadas (fecha, complejo, canal) se comparten entre tablas de hechos;
las que no aplican a una tabla de hechos (por ejemplo, producto en taquilla) se rechazan
con un mensaje explicativo.
"""
import time

from backend.services.db import conn

JOINS = {
    "fecha": "JOIN dim_fecha d ON d.fecha_key = f.fecha_key",
    "complejo": "JOIN dim_complejo c ON c.complejo_key = f.complejo_key",
    "pelicula": "JOIN dim_pelicula p ON p.pelicula_key = f.pelicula_key",
    "sala": "JOIN dim_sala s ON s.sala_key = f.sala_key",
    "horario": "JOIN dim_horario h ON h.horario_key = f.horario_key",
    "canal": "JOIN dim_canal cn ON cn.canal_key = f.canal_key",
    "promocion": "JOIN dim_promocion pr ON pr.promocion_key = f.promocion_key",
    "producto": "JOIN dim_producto pd ON pd.producto_key = f.producto_key",
}

# clave -> (dimensión física, expresión SQL, etiqueta, jerarquía)
DIMENSIONES = {
    "anio": ("fecha", "CAST(d.anio AS TEXT)", "Año", "Tiempo"),
    "trimestre": ("fecha", "d.anio || '-T' || d.trimestre", "Trimestre", "Tiempo"),
    "mes": ("fecha", "d.anio_mes", "Mes", "Tiempo"),
    "fecha": ("fecha", "d.fecha", "Día", "Tiempo"),
    "dia_semana": ("fecha", "d.dia_semana || '. ' || d.nombre_dia", "Día de la semana", "Calendario"),
    "tipo_dia": ("fecha", "CASE WHEN d.es_fin_semana = 1 THEN 'Fin de semana' ELSE 'Entre semana' END", "Tipo de día", "Calendario"),
    "temporada": ("fecha", "d.temporada", "Temporada", "Calendario"),
    "region": ("complejo", "c.region", "Región", "Geografía"),
    "ciudad": ("complejo", "c.ciudad", "Ciudad", "Geografía"),
    "complejo": ("complejo", "c.nombre", "Complejo", "Geografía"),
    "genero": ("pelicula", "p.genero", "Género", "Película"),
    "pelicula": ("pelicula", "p.titulo", "Película", "Película"),
    "clasificacion": ("pelicula", "p.clasificacion", "Clasificación", "Película"),
    "tipo_lanzamiento": ("pelicula", "p.tipo_lanzamiento", "Tipo de lanzamiento", "Película"),
    "formato": ("sala", "s.formato", "Formato de sala", "Sala"),
    "turno": ("horario", "h.turno", "Turno", "Horario"),
    "hora": ("horario", "printf('%02d:00', h.hora_num)", "Hora", "Horario"),
    "canal": ("canal", "cn.nombre", "Canal de venta", "Canal"),
    "promocion": ("promocion", "pr.nombre", "Promoción", "Promoción"),
    "categoria": ("producto", "pd.categoria", "Categoría de producto", "Producto"),
    "producto": ("producto", "pd.nombre", "Producto", "Producto"),
}
JERARQUIAS = {
    "Tiempo": ["anio", "trimestre", "mes", "fecha"],
    "Geografía": ["region", "ciudad", "complejo"],
    "Película": ["genero", "pelicula"],
    "Producto": ["categoria", "producto"],
    "Horario": ["turno", "hora"],
}

HECHOS = {
    "boletos": ("fact_ventas_boletos", {"fecha", "complejo", "pelicula", "sala", "horario", "canal", "promocion"}, "Ventas de boletos"),
    "funciones": ("fact_funciones", {"fecha", "complejo", "pelicula", "sala", "horario", "promocion"}, "Funciones"),
    "dulceria": ("fact_ventas_dulceria", {"fecha", "complejo", "producto", "canal"}, "Ventas de dulcería"),
}

# clave -> (hecho, componentes, fórmula, etiqueta, formato)
# Todas las medidas se expresan como funciones de componentes aditivos (sumas); así los
# totales de filas/columnas se calculan correctamente incluso para razones (ocupación, ticket).
_div = lambda a, b: (a / b) if b else None
MEDIDAS = {
    "ingreso_taquilla": ("boletos", ["ingreso_taq"], lambda c: c["ingreso_taq"], "Ingreso de taquilla", "mxn"),
    "boletos": ("boletos", ["boletos"], lambda c: c["boletos"], "Boletos vendidos", "int"),
    "descuentos": ("boletos", ["descuentos"], lambda c: c["descuentos"], "Descuentos otorgados", "mxn"),
    "ticket_promedio": ("boletos", ["ingreso_taq", "boletos"], lambda c: _div(c["ingreso_taq"], c["boletos"]), "Ticket promedio", "mxn2"),
    "asistentes": ("funciones", ["asistentes"], lambda c: c["asistentes"], "Asistentes", "int"),
    "funciones": ("funciones", ["nfunc"], lambda c: c["nfunc"], "Funciones", "int"),
    "capacidad": ("funciones", ["capacidad"], lambda c: c["capacidad"], "Butacas ofertadas", "int"),
    "ocupacion": ("funciones", ["boletos", "capacidad"], lambda c: _div(100.0 * c["boletos"], c["capacidad"]), "Ocupación (%)", "pct"),
    "ingreso_dulceria": ("dulceria", ["ingreso_dul"], lambda c: c["ingreso_dul"], "Ingreso de dulcería", "mxn"),
    "unidades": ("dulceria", ["unidades"], lambda c: c["unidades"], "Unidades de dulcería", "int"),
    "margen_bruto": ("dulceria", ["margen"], lambda c: c["margen"], "Margen bruto de dulcería", "mxn"),
    "margen_pct": ("dulceria", ["margen", "ingreso_dul"], lambda c: _div(100.0 * c["margen"], c["ingreso_dul"]), "Margen bruto (%)", "pct"),
}
ADITIVAS = {"ingreso_taquilla", "boletos", "descuentos", "asistentes", "funciones", "capacidad", "ingreso_dulceria",
            "unidades", "margen_bruto"}

# Navegación de agregados: se usa la tabla más pequeña capaz de responder la consulta.
_MES = {"anio", "trimestre", "mes"}
_GEO = {"region", "ciudad", "complejo"}
_DIA = {"anio", "trimestre", "mes", "fecha", "dia_semana", "tipo_dia", "temporada"}
_FECHA_MES = ("JOIN (SELECT anio_mes, MIN(anio) anio, MIN(trimestre) trimestre FROM dim_fecha GROUP BY anio_mes) d "
              "ON d.anio_mes = f.anio_mes")
FUENTES = [
    dict(tabla="mart_diario_complejo", tipo="Data mart (agregado diario)", hechos={"boletos", "funciones", "dulceria"},
         dims=_DIA | _GEO, mensual=False,
         comps=dict(ingreso_taq="SUM(f.ingreso_taquilla)", boletos="SUM(f.boletos)", descuentos="SUM(f.descuentos)",
                    asistentes="SUM(f.asistentes)", nfunc="SUM(f.funciones)", capacidad="SUM(f.capacidad)",
                    ingreso_dul="SUM(f.ingreso_dulceria)", unidades="SUM(f.unidades_dulceria)",
                    margen="SUM(f.ingreso_dulceria - f.costo_dulceria)")),
    dict(tabla="mart_pelicula_mensual", tipo="Data mart (agregado mensual)", hechos={"boletos", "funciones"},
         dims=_MES | _GEO | {"genero", "pelicula", "clasificacion", "tipo_lanzamiento"}, mensual=True,
         comps=dict(ingreso_taq="SUM(f.ingreso_taquilla)", boletos="SUM(f.boletos)", asistentes="SUM(f.asistentes)",
                    nfunc="SUM(f.funciones)", capacidad="SUM(f.capacidad)")),
    dict(tabla="mart_taquilla_mensual", tipo="Data mart (agregado mensual)", hechos={"boletos"},
         dims=_MES | _GEO | {"formato", "canal", "promocion"}, mensual=True,
         comps=dict(ingreso_taq="SUM(f.ingreso)", boletos="SUM(f.boletos)", descuentos="SUM(f.descuentos)")),
    dict(tabla="mart_dulceria_mensual", tipo="Data mart (agregado mensual)", hechos={"dulceria"},
         dims=_MES | _GEO | {"categoria", "producto", "canal"}, mensual=True,
         comps=dict(ingreso_dul="SUM(f.ingreso)", unidades="SUM(f.unidades)", margen="SUM(f.margen)")),
    dict(tabla="fact_ventas_boletos", tipo="Tabla de hechos (detalle)", hechos={"boletos"}, mensual=False,
         dims={k for k, v in DIMENSIONES.items() if v[0] in HECHOS["boletos"][1]},
         comps=dict(ingreso_taq="SUM(f.ingreso_total)", boletos="SUM(f.boletos_vendidos)", descuentos="SUM(f.monto_descuento)")),
    dict(tabla="fact_funciones", tipo="Tabla de hechos (detalle)", hechos={"funciones"}, mensual=False,
         dims={k for k, v in DIMENSIONES.items() if v[0] in HECHOS["funciones"][1]},
         comps=dict(asistentes="SUM(f.asistentes)", nfunc="COUNT(*)", capacidad="SUM(f.capacidad)", boletos="SUM(f.boletos_vendidos)")),
    dict(tabla="fact_ventas_dulceria", tipo="Tabla de hechos (detalle)", hechos={"dulceria"}, mensual=False,
         dims={k for k, v in DIMENSIONES.items() if v[0] in HECHOS["dulceria"][1]},
         comps=dict(ingreso_dul="SUM(f.ingreso_total)", unidades="SUM(f.unidades_vendidas)", margen="SUM(f.margen_bruto)")),
]
MAX_COLS = 15
MAX_ROWS = 400


class OlapError(ValueError):
    pass


def metadata():
    return dict(
        dimensiones=[dict(clave=k, etiqueta=v[2], grupo=v[3], tabla=v[0]) for k, v in DIMENSIONES.items()],
        medidas=[dict(clave=k, etiqueta=v[3], hecho=v[0], formato=v[4], hecho_nombre=HECHOS[v[0]][2],
                      dimensiones=sorted(d for d, (t, *_) in DIMENSIONES.items() if t in HECHOS[v[0]][1]))
                 for k, v in MEDIDAS.items()],
        jerarquias=JERARQUIAS,
    )


def _choose_source(hecho, comps, dims):
    for src in FUENTES:
        if hecho in src["hechos"] and set(comps) <= set(src["comps"]) and set(dims) <= src["dims"]:
            return src
    raise OlapError("No hay una tabla capaz de responder la consulta.")


def query(medida: str, filas: str, columnas=None, filtros=None, orden="valor", forzar_detalle=False):
    t0 = time.time()
    if medida not in MEDIDAS:
        raise OlapError(f"Medida desconocida: {medida}")
    hecho, comps, formula, etiqueta, fmt = MEDIDAS[medida]
    tabla, dims_ok, hecho_nombre = HECHOS[hecho]
    filtros = {k: (v if isinstance(v, list) else [v]) for k, v in (filtros or {}).items() if v not in (None, "", [])}
    if columnas == filas:
        columnas = None
    usados = [filas] + ([columnas] if columnas else []) + list(filtros)
    for dkey in usados:
        if dkey not in DIMENSIONES:
            raise OlapError(f"Dimensión desconocida: {dkey}")
        if DIMENSIONES[dkey][0] not in dims_ok:
            raise OlapError(f"La dimensión «{DIMENSIONES[dkey][2]}» no está relacionada con la tabla de hechos "
                            f"«{hecho_nombre}». Elige otra medida o quita esa dimensión/filtro.")
    src = next(s for s in FUENTES if s["tabla"] == tabla) if forzar_detalle else _choose_source(hecho, comps, usados)
    joins = []
    for dkey in usados:
        phys = DIMENSIONES[dkey][0]
        j = _FECHA_MES if (phys == "fecha" and src["mensual"]) else JOINS[phys]
        if j not in joins:
            joins.append(j)
    where, params = [], []
    for dkey, vals in filtros.items():
        where.append(f"{DIMENSIONES[dkey][1]} IN ({','.join('?' * len(vals))})")
        params += [str(v) for v in vals]
    if "anio" in filtros:   # poda por rango: aprovecha los índices por fecha
        ys = [int(y) for y in filtros["anio"]]
        if src["mensual"]:
            where.append("f.anio_mes BETWEEN ? AND ?")
            params += [f"{min(ys)}-01", f"{max(ys)}-12"]
        else:
            where.append("f.fecha_key BETWEEN ? AND ?")
            params += [min(ys) * 10000 + 101, max(ys) * 10000 + 1231]
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    sel_comps = ", ".join(f"{src['comps'][c]} AS {c}" for c in comps)
    rexpr = DIMENSIONES[filas][1]
    cexpr = DIMENSIONES[columnas][1] if columnas else "''"
    sql = (f"SELECT {rexpr} AS r, {cexpr} AS c, {sel_comps} FROM {src['tabla']} f {' '.join(joins)}{wsql} GROUP BY r, c")
    with conn() as con:
        data = con.execute(sql, params).fetchall()
    zero = lambda: {c: 0.0 for c in comps}
    cells, rtot, ctot, gtot = {}, {}, {}, zero()
    for rec in data:
        r, c, vals = rec[0], rec[1], dict(zip(comps, (v or 0 for v in rec[2:])))
        cells.setdefault(r, {})[c] = vals
        for acc in (rtot.setdefault(r, zero()), ctot.setdefault(c, zero()), gtot):
            for k in comps:
                acc[k] += vals[k]
    cols = []
    if columnas:
        ordered_time = DIMENSIONES[columnas][3] in ("Tiempo",) or columnas in ("dia_semana", "hora", "turno")
        cols = sorted(ctot, key=(lambda k: k) if ordered_time else (lambda k: -(formula(ctot[k]) or 0)))[:MAX_COLS]
        if ordered_time and len(ctot) > MAX_COLS:
            cols = sorted(ctot)[-MAX_COLS:]
    time_like = DIMENSIONES[filas][3] == "Tiempo" or filas in ("dia_semana", "hora", "turno")
    keys = sorted(rtot, key=(lambda k: k) if (time_like and orden == "valor") or orden == "etiqueta"
                  else (lambda k: -(formula(rtot[k]) or 0)))
    truncated = len(keys) > MAX_ROWS
    keys = keys[:MAX_ROWS]
    datos = []
    for k in keys:
        if columnas:
            celdas = {c: formula(cells[k][c]) for c in cols if c in cells[k]}
        else:
            celdas = {"valor": formula(rtot[k])}
        datos.append(dict(clave=k, celdas=celdas, total=formula(rtot[k])))
    return dict(
        medida=dict(clave=medida, etiqueta=etiqueta, formato=fmt, aditiva=medida in ADITIVAS),
        hecho=dict(clave=hecho, tabla=tabla, nombre=hecho_nombre),
        fuente=dict(tabla=src["tabla"], tipo=src["tipo"]),
        filas=dict(clave=filas, etiqueta=DIMENSIONES[filas][2]),
        columnas=dict(clave=columnas, etiqueta=DIMENSIONES[columnas][2]) if columnas else None,
        encabezados=cols,
        datos=datos,
        totales_columna=[formula(ctot[c]) for c in cols],
        total=formula(gtot) if data else None, truncado=truncated, columnas_omitidas=max(0, len(ctot) - len(cols)),
        filtros=filtros, sql=sql, ms=round(1000 * (time.time() - t0)),
    )


def valores(dim: str, limite=500):
    if dim not in DIMENSIONES:
        raise OlapError(f"Dimensión desconocida: {dim}")
    tbl, expr, *_ = DIMENSIONES[dim]
    table = {"fecha": "dim_fecha d WHERE d.fecha_key IN (SELECT DISTINCT fecha_key FROM mart_diario_complejo)",
             "complejo": "dim_complejo c", "pelicula": "dim_pelicula p WHERE p.pelicula_key IN (SELECT DISTINCT pelicula_key FROM mart_pelicula_mensual)",
             "sala": "dim_sala s", "horario": "dim_horario h WHERE h.horario_key IN (SELECT DISTINCT horario_key FROM fact_funciones)",
             "canal": "dim_canal cn", "promocion": "dim_promocion pr", "producto": "dim_producto pd"}[tbl]
    with conn() as con:
        return [r[0] for r in con.execute(f"SELECT DISTINCT {expr} v FROM {table} ORDER BY v LIMIT {int(limite)}")]
