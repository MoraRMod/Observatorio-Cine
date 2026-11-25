"""Metadatos del Data Warehouse (diccionario de datos, conteos) y validaciones de calidad."""
import json
import re
from pathlib import Path

from backend.services.db import conn, one, rows

SCHEMA = Path(__file__).resolve().parents[1] / "etl" / "schema.sql"

GRANO = {
    "fact_funciones": "Una función: proyección de una película en una sala, en una fecha y hora.",
    "fact_ventas_boletos": "Boletos vendidos de una función por un canal de venta.",
    "fact_ventas_dulceria": "Unidades de un producto vendidas en un complejo, en un día y por un canal.",
    "mart_diario_complejo": "Un complejo en un día (agregado de los tres hechos).",
    "mart_pelicula_mensual": "Una película en un complejo durante un mes.",
    "mart_taquilla_mensual": "Mes × complejo × sala × canal × promoción.",
    "mart_dulceria_mensual": "Mes × complejo × producto × canal.",
}
DESCRIPCION = {
    "dim_fecha": "Calendario con jerarquía año > trimestre > mes > día, festivos, vacaciones y temporada.",
    "dim_complejo": "Complejos cinematográficos (nombres ficticios en ciudades reales). Jerarquía región > ciudad > complejo.",
    "dim_sala": "Salas y su formato (Tradicional, Macro XE, IMAX, 4DX, VIP, Junior) y capacidad.",
    "dim_pelicula": "Películas ficticias con género, clasificación, duración, estreno, distribuidora y tipo de lanzamiento.",
    "dim_horario": "Hora de inicio en intervalos de 5 minutos, turno y clasificación de demanda.",
    "dim_producto": "Productos de dulcería con categoría, precio y costo simulado vigentes.",
    "dim_canal": "Canales de venta presenciales y digitales.",
    "dim_promocion": "Promociones de taquilla con su descuento y vigencia.",
    "etl_ejecucion": "Bitácora de ejecuciones del proceso ETL.",
    "etl_archivo": "Control de archivos cargados (checksum) para la carga incremental.",
    "etl_rechazo": "Registros rechazados por reglas de calidad, con el motivo.",
    "ml_ejecucion": "Metadatos del último entrenamiento del modelo predictivo.",
    "ml_metricas": "Métricas de evaluación de cada modelo por conjunto.",
    "ml_prediccion_prueba": "Valores reales y estimados en el periodo de prueba.",
    "ml_pronostico": "Pronóstico diario por complejo para los próximos 30 días.",
    "ml_importancia": "Importancia por permutación de cada variable.",
}


def _column_comments():
    """Extrae los comentarios '-- ...' de cada columna en schema.sql."""
    out, table = {}, None
    for line in SCHEMA.read_text(encoding="utf-8").splitlines():
        m = re.match(r"CREATE TABLE IF NOT EXISTS (\w+)", line)
        if m:
            table = m.group(1)
            continue
        m = re.match(r"\s+(\w+)\s+[A-Z]+.*?--\s*(.+)$", line)
        if table and m:
            out[(table, m.group(1))] = m.group(2).strip()
    return out


def esquema():
    comments = _column_comments()
    out = []
    with conn() as con:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for t in tables:
            cols = [dict(nombre=c[1], tipo=c[2], nulo=not c[3], pk=bool(c[5]), comentario=comments.get((t, c[1])))
                    for c in con.execute(f"PRAGMA table_info({t})")]
            fks = [dict(columna=f[3], referencia=f"{f[2]}.{f[4]}") for f in con.execute(f"PRAGMA foreign_key_list({t})")]
            for c in cols:
                c["fk"] = next((f["referencia"] for f in fks if f["columna"] == c["nombre"]), None)
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            capa = ("Dimensión" if t.startswith("dim_") else "Hechos" if t.startswith("fact_") else
                    "Data mart" if t.startswith("mart_") else "Control ETL" if t.startswith("etl_") else "Modelo predictivo")
            out.append(dict(tabla=t, capa=capa, filas=n, columnas=cols, grano=GRANO.get(t), descripcion=DESCRIPCION.get(t)))
    return out


def validaciones():
    checks = []

    def add(nombre, ok, detalle):
        checks.append(dict(prueba=nombre, ok=bool(ok), detalle=detalle))

    with conn() as con:
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        add("Integridad referencial (PRAGMA foreign_key_check)", not fk, f"{len(fk)} violaciones")
        for t, k in (("fact_funciones", "funcion_id"), ("fact_ventas_boletos", "venta_id")):
            d = con.execute(f"SELECT COUNT(*) - COUNT(DISTINCT {k}) FROM {t}").fetchone()[0]
            add(f"Sin duplicados en {t}", d == 0, f"{d} claves repetidas")
        d = con.execute("SELECT COUNT(*) FROM (SELECT 1 FROM fact_ventas_boletos GROUP BY funcion_id, canal_key HAVING COUNT(*) > 1)").fetchone()[0]
        add("Grano único función × canal en ventas de boletos", d == 0, f"{d} combinaciones repetidas")
        a, b = con.execute("""SELECT (SELECT SUM(boletos_vendidos) FROM fact_funciones),
                                     (SELECT SUM(boletos_vendidos) FROM fact_ventas_boletos)""").fetchone()
        add("Boletos en fact_funciones = boletos en fact_ventas_boletos", a == b, f"{a:,} vs {b:,}")
        o = con.execute("SELECT COUNT(*) FROM fact_funciones WHERE boletos_vendidos > capacidad OR asistentes > boletos_vendidos").fetchone()[0]
        add("Boletos ≤ capacidad y asistentes ≤ boletos", o == 0, f"{o} funciones inconsistentes")
        x = con.execute("""SELECT COUNT(*) FROM fact_funciones WHERE ABS(porcentaje_ocupacion - 100.0 * boletos_vendidos / capacidad) > 0.01
                           OR asientos_disponibles <> capacidad - boletos_vendidos""").fetchone()[0]
        add("Ocupación y asientos disponibles calculados correctamente", x == 0, f"{x} diferencias")
        x = con.execute("""SELECT COUNT(*) FROM fact_ventas_dulceria WHERE ABS(ingreso_total - unidades_vendidas * precio_unitario) > 0.02
                           OR ABS(margen_bruto - (ingreso_total - costo_total)) > 0.02""").fetchone()[0]
        add("Ingreso, costo y margen de dulcería consistentes", x == 0, f"{x} diferencias")
        a, b = con.execute("""SELECT (SELECT ROUND(SUM(ingreso_total), 0) FROM fact_ventas_boletos),
                                     (SELECT ROUND(SUM(ingreso_taquilla), 0) FROM mart_diario_complejo)""").fetchone()
        add("Mart diario cuadra con hechos de taquilla", a == b, f"${a:,.0f} vs ${b:,.0f}")
        a, b = con.execute("""SELECT (SELECT ROUND(SUM(ingreso_total), 0) FROM fact_ventas_dulceria),
                                     (SELECT ROUND(SUM(ingreso), 0) FROM mart_dulceria_mensual)""").fetchone()
        add("Mart de dulcería cuadra con hechos de dulcería", a == b, f"${a:,.0f} vs ${b:,.0f}")
        a, b = con.execute("""SELECT (SELECT SUM(asistentes) FROM fact_funciones),
                                     (SELECT SUM(asistentes) FROM mart_pelicula_mensual)""").fetchone()
        add("Mart de películas cuadra con hechos de funciones", a == b, f"{a:,} vs {b:,}")
        g = con.execute("""SELECT COUNT(*) FROM (SELECT fecha FROM dim_fecha WHERE fecha_key BETWEEN
                           (SELECT MIN(fecha_key) FROM mart_diario_complejo) AND (SELECT MAX(fecha_key) FROM mart_diario_complejo)
                           EXCEPT SELECT d.fecha FROM mart_diario_complejo m JOIN dim_fecha d USING (fecha_key))""").fetchone()[0]
        add("Serie de tiempo continua (sin días faltantes)", g == 0, f"{g} días sin datos")
    return checks


def contexto_publico():
    """Información pública verificable usada como contexto (no se mezcla con los datos sintéticos)."""
    return [
        dict(dato="Cinépolis se fundó en 1971 en Morelia, Michoacán, donde mantiene su sede.", fuente="Información corporativa pública de Cinépolis"),
        dict(dato="Formatos de sala comercializados por la cadena: Tradicional, VIP, IMAX, 4DX, Macro XE, ScreenX y salas Junior, entre otros.",
             fuente="Sitio web público de Cinépolis"),
        dict(dato="Canales de venta de boletos: taquilla, kioscos de autoservicio, aplicación móvil y página web.", fuente="Sitio web y app públicos de Cinépolis"),
        dict(dato="Taquilla nacional 2024: 15,378 millones de pesos (−1.37 % vs 2023) y 217 millones de boletos (−6.78 %).",
             fuente="CANACINE, Resultados de industria 2024"),
        dict(dato="El precio promedio implícito por boleto en México en 2024 fue de ~70.9 MXN (15,378 M / 217 M).", fuente="Cálculo propio con cifras de CANACINE"),
        dict(dato="Las huelgas de guionistas y actores de Hollywood de 2023 redujeron la oferta de estrenos de 2024.", fuente="Cobertura de prensa especializada"),
        dict(dato="Directorio de complejos de la cadena por entidad federativa (477 complejos, archivo descargado el 19-oct-2026).",
             fuente="Sistema de Información Cultural (SIC), Secretaría de Cultura"),
    ]
