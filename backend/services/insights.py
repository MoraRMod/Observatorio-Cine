"""Inteligencia de negocios: hallazgos y recomendaciones generados a partir del DW y del modelo.

Cada recomendación se calcula con consultas reales; los textos se construyen con los valores
obtenidos.  Los impactos son ESTIMACIONES (no medidas) y así se etiquetan.
"""
import json
from datetime import date, timedelta

import pandas as pd

from backend.services.db import frame, one, rows


def _mxn(v):
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e6:
        return f"${v / 1e6:,.1f} M"
    if a >= 1e3:
        return f"${v / 1e3:,.0f} mil"
    return f"${v:,.0f}"


def _pct(v, signo=True):
    return "—" if v is None else (f"{v:+.1f} %" if signo else f"{v:.1f} %")


def _ultimo_anio():
    r = one("SELECT MAX(fecha_key) b FROM mart_diario_complejo")
    last = date(r["b"] // 10000, r["b"] // 100 % 100, r["b"] % 100)
    # último año completo disponible
    return last.year if last.month == 12 and last.day == 31 else last.year - 1, last


def generar():
    anio, last = _ultimo_anio()
    prev = anio - 1
    yk = lambda y: (y * 10000 + 101, y * 10000 + 1231)
    hallazgos, recomendaciones, riesgos, oportunidades = [], [], [], []

    # ---------------------------------------------------------------- tendencia
    yr = frame("""SELECT d.anio, SUM(ingreso_taquilla) taq, SUM(ingreso_dulceria) dul, SUM(asistentes) asis,
                         SUM(boletos) bol, SUM(capacidad) cap, SUM(costo_dulceria) costo
                  FROM mart_diario_complejo m JOIN dim_fecha d USING (fecha_key) GROUP BY d.anio""").set_index("anio")
    yr["total"] = yr.taq + yr.dul
    tendencia = []
    if prev in yr.index and anio in yr.index:
        c, p = yr.loc[anio], yr.loc[prev]
        g = 100 * (c.total / p.total - 1)
        ga = 100 * (c.asis / p.asis - 1)
        tp, tc = p.taq / p.bol, c.taq / c.bol
        sp, sc = p.dul / p.asis, c.dul / c.asis
        hallazgos.append(dict(titulo="Tendencia de ingresos",
                              texto=f"En {anio} los ingresos totales fueron {_mxn(c.total)}, {_pct(g)} frente a {prev}. "
                                    f"La asistencia varió {_pct(ga)}; el resto del cambio se explica por el ticket promedio "
                                    f"({_mxn(tp)} → {_mxn(tc)}) y el gasto en dulcería por asistente ({_mxn(sp)} → {_mxn(sc)}).",
                              tono="positivo" if g > 0 else "negativo"))
        tendencia = [dict(anio=int(i), total=float(r.total), asistentes=int(r.asis), ocupacion=float(100 * r.bol / r.cap))
                     for i, r in yr.iterrows()]

    # ---------------------------------------------------------------- complejos
    cx = frame(f"""SELECT c.complejo_key, c.nombre, c.ciudad, c.tipo_complejo, c.num_salas, c.fecha_apertura,
                          SUM(CASE WHEN fecha_key BETWEEN {yk(anio)[0]} AND {yk(anio)[1]} THEN ingreso_taquilla + ingreso_dulceria END) cur,
                          SUM(CASE WHEN fecha_key BETWEEN {yk(prev)[0]} AND {yk(prev)[1]} THEN ingreso_taquilla + ingreso_dulceria END) prev,
                          SUM(CASE WHEN fecha_key BETWEEN {yk(anio)[0]} AND {yk(anio)[1]} THEN boletos END) * 100.0 /
                          SUM(CASE WHEN fecha_key BETWEEN {yk(anio)[0]} AND {yk(anio)[1]} THEN capacidad END) occ,
                          SUM(CASE WHEN fecha_key BETWEEN {yk(anio)[0]} AND {yk(anio)[1]} THEN ingreso_dulceria END) /
                          SUM(CASE WHEN fecha_key BETWEEN {yk(anio)[0]} AND {yk(anio)[1]} THEN asistentes END) gasto,
                          SUM(CASE WHEN fecha_key BETWEEN {yk(anio)[0]} AND {yk(anio)[1]} THEN asistentes END) asis
                   FROM mart_diario_complejo m JOIN dim_complejo c USING (complejo_key) GROUP BY c.complejo_key""")
    cx["var"] = 100 * (cx.cur / cx.prev - 1)
    cx["por_sala"] = cx.cur / cx.num_salas
    cx = cx.sort_values("cur", ascending=False)
    top = cx.head(3)
    comparables = cx[cx.prev.notna() & (cx.fecha_apertura < f"{prev}-01-01")]
    bottom = comparables.sort_values("var").head(3)
    mejores = [dict(nombre=r.nombre, ciudad=r.ciudad, ingreso=r.cur, variacion=r["var"], ocupacion=r.occ,
                    ingreso_por_sala=r.por_sala) for _, r in top.iterrows()]
    peores = [dict(nombre=r.nombre, ciudad=r.ciudad, ingreso=r.cur, variacion=r["var"], ocupacion=r.occ,
                   ingreso_por_sala=r.por_sala) for _, r in bottom.iterrows()]
    hallazgos.append(dict(titulo="Complejos líderes",
                          texto=f"{top.iloc[0].nombre} ({top.iloc[0].ciudad}) encabeza los ingresos de {anio} con "
                                f"{_mxn(top.iloc[0].cur)}; los tres primeros concentran "
                                f"{100 * top.cur.sum() / cx.cur.sum():.0f} % del total.", tono="neutral"))

    # Caída sostenida en el último semestre
    h2 = frame(f"""SELECT c.complejo_key, c.nombre, c.ciudad,
                          SUM(CASE WHEN fecha_key BETWEEN {anio}0701 AND {anio}1231 THEN ingreso_taquilla + ingreso_dulceria END) cur,
                          SUM(CASE WHEN fecha_key BETWEEN {prev}0701 AND {prev}1231 THEN ingreso_taquilla + ingreso_dulceria END) ant
                   FROM mart_diario_complejo m JOIN dim_complejo c USING (complejo_key) GROUP BY 1""").dropna()
    h2["var"] = 100 * (h2.cur / h2.ant - 1)
    med = h2["var"].median()
    caidas = h2[(h2["var"] < med - 12)].sort_values("var")

    # ---------------------------------------------------------------- modelo
    run = one("SELECT detalle FROM ml_ejecucion WHERE id = 1")
    modelo = None
    alertas = []
    if run:
        info = json.loads(run["detalle"])
        met = {(r["modelo"], r["conjunto"]): r for r in rows("SELECT * FROM ml_metricas")}
        test = met.get((info["algoritmo"], "prueba"))
        base = met.get(("Línea base (promedio mismo día, 5-8 semanas)", "prueba"))
        agg = info.get("metricas_agregadas_prueba", {}).get("semanal_por_complejo", {})
        modelo = dict(algoritmo=info["algoritmo"], mape=test["mape"], r2=test["r2"], mae=test["mae"],
                      mape_base=base["mape"] if base else None, mape_semanal=agg.get("mape"))
        hallazgos.append(dict(titulo="Resultados del modelo predictivo",
                              texto=f"El modelo {info['algoritmo']} explica {100 * test['r2']:.0f} % de la variación del ingreso "
                                    f"diario por complejo en el periodo de prueba (MAPE diario {test['mape']:.1f} %, "
                                    f"MAPE semanal {agg.get('mape', 0):.1f} %), frente a {base['mape']:.1f} % de la línea base. "
                                    f"La incertidumbre restante proviene sobre todo del desempeño de cada estreno, que no se "
                                    f"conoce antes de exhibirse.", tono="neutral"))
        # Real vs estimado en prueba por complejo (desempeño inferior al esperado)
        rv = frame("""SELECT c.nombre, c.ciudad, SUM(ingreso_real) real, SUM(ingreso_pred) pred,
                             SUM(CASE WHEN fecha >= date((SELECT MAX(fecha) FROM ml_prediccion_prueba), '-90 day') THEN ingreso_real END) real90,
                             SUM(CASE WHEN fecha >= date((SELECT MAX(fecha) FROM ml_prediccion_prueba), '-90 day') THEN ingreso_pred END) pred90
                      FROM ml_prediccion_prueba t JOIN dim_complejo c USING (complejo_key) GROUP BY 1""")
        rv["brecha"] = 100 * (rv.real90 / rv.pred90 - 1)
        # Pronóstico 30 días vs mismo periodo del año anterior y vs últimos 30 días
        fc = frame("""SELECT c.complejo_key, c.nombre, c.ciudad, MIN(fecha) desde, MAX(fecha) hasta, SUM(ingreso_pred) pred,
                             SUM(asistencia_pred) asis
                      FROM ml_pronostico p JOIN dim_complejo c USING (complejo_key) GROUP BY 1""")
        if len(fc):
            d0, d1 = date.fromisoformat(fc.desde.min()), date.fromisoformat(fc.hasta.max())
            ly0, ly1 = d0.replace(year=d0.year - 1), d1.replace(year=d1.year - 1)
            ly = frame(f"""SELECT complejo_key, SUM(ingreso_taquilla + ingreso_dulceria) ly FROM mart_diario_complejo
                           WHERE fecha_key BETWEEN {ly0:%Y%m%d} AND {ly1:%Y%m%d} GROUP BY 1""")
            l30 = frame(f"""SELECT complejo_key, SUM(ingreso_taquilla + ingreso_dulceria) l30 FROM mart_diario_complejo
                            WHERE fecha_key BETWEEN {(d0 - timedelta(days=30)):%Y%m%d} AND {(d0 - timedelta(days=1)):%Y%m%d} GROUP BY 1""")
            fc = fc.merge(ly, on="complejo_key", how="left").merge(l30, on="complejo_key", how="left")
            fc["vs_ly"] = 100 * (fc.pred / fc.ly - 1)
            mvs = fc.vs_ly.median()
            fc = fc.merge(rv[["nombre", "brecha"]], on="nombre", how="left")
            for _, r in fc.sort_values("vs_ly").iterrows():
                if pd.notna(r.vs_ly) and (r.vs_ly < mvs - 10 or (pd.notna(r.brecha) and r.brecha < -10)):
                    alertas.append(dict(complejo=r.nombre, ciudad=r.ciudad, pronostico=r.pred, anio_anterior=r.ly,
                                        variacion=r.vs_ly, brecha_modelo=r.brecha))
            total_pred, total_ly = fc.pred.sum(), fc.ly.sum()
            hallazgos.append(dict(titulo="Pronóstico de los próximos 30 días",
                                  texto=f"Para {d0:%d/%m/%Y}–{d1:%d/%m/%Y} el modelo estima {_mxn(total_pred)} en ingresos totales "
                                        f"({_pct(100 * (total_pred / total_ly - 1))} contra el mismo periodo del año anterior) "
                                        f"y {fc.asis.sum():,.0f} asistentes.", tono="neutral"))

    # ---- Riesgo: complejos con caída
    for a in alertas[:3]:
        txt = (f"{a['complejo']}: el pronóstico de 30 días ({_mxn(a['pronostico'])}) es {_pct(a['variacion'])} frente al mismo "
               f"periodo del año anterior")
        if a["brecha_modelo"] is not None and pd.notna(a["brecha_modelo"]) and a["brecha_modelo"] < -10:
            txt += f", y en los últimos 90 días de prueba vendió {_pct(a['brecha_modelo'])} respecto a lo que el modelo esperaba"
        riesgos.append(txt + ".")
    if len(caidas):
        r0 = caidas.iloc[0]
        recomendaciones.append(dict(
            prioridad="Alta", area="Operación de complejos",
            hallazgo=f"{r0.nombre} ({r0.ciudad}) muestra la mayor caída de ingresos del segundo semestre de {anio}.",
            indicador=f"Variación S2 {anio} vs S2 {prev}: {_pct(r0['var'])} (mediana de la cadena: {_pct(med)}).",
            interpretacion="La caída es muy superior a la del resto de la cadena, por lo que no se explica por la "
                           "estacionalidad ni por la cartelera; sugiere un factor local (competencia, acceso, plaza comercial).",
            accion="Realizar un diagnóstico local (encuesta de salida, revisión de accesos y competencia), ajustar la "
                   "programación a los horarios con mayor demanda y lanzar una promoción local de recuperación.",
            impacto=f"Recuperar la mitad de la brecha equivaldría a ~{_mxn(0.5 * (r0.ant * (1 + med / 100) - r0.cur))} por semestre.",
            tipo_impacto="Estimación"))

    # ---------------------------------------------------------------- días y horarios
    dw = frame(f"""SELECT d.nombre_dia, d.dia_semana, AVG(t) ingreso_dia FROM (
                     SELECT fecha_key, SUM(ingreso_taquilla + ingreso_dulceria) t FROM mart_diario_complejo
                     WHERE fecha_key BETWEEN {yk(anio)[0]} AND {yk(anio)[1]} GROUP BY 1) x
                   JOIN dim_fecha d USING (fecha_key) GROUP BY d.dia_semana ORDER BY ingreso_dia DESC""")
    hol = one(f"""SELECT AVG(CASE WHEN d.es_festivo = 1 AND d.es_fin_semana = 0 THEN t END) fest,
                         AVG(CASE WHEN d.es_festivo = 0 AND d.es_fin_semana = 0 AND d.es_vacaciones = 0 THEN t END) normal
                  FROM (SELECT fecha_key, SUM(ingreso_taquilla + ingreso_dulceria) t FROM mart_diario_complejo GROUP BY 1) x
                  JOIN dim_fecha d USING (fecha_key)""")
    hallazgos.append(dict(titulo="Días de mayor demanda",
                          texto=f"El {dw.iloc[0].nombre_dia.lower()} genera en promedio {_mxn(dw.iloc[0].ingreso_dia)} diarios en la "
                                f"cadena, {dw.iloc[0].ingreso_dia / dw.iloc[-1].ingreso_dia:.1f} veces más que el "
                                f"{dw.iloc[-1].nombre_dia.lower()}. Un festivo entre semana genera "
                                f"{_pct(100 * (hol['fest'] / hol['normal'] - 1))} frente a un día laborable normal.",
                          tono="neutral"))
    slot = frame(f"""SELECT h.turno, CASE WHEN d.es_fin_semana = 1 THEN 'fin de semana' ELSE 'entre semana' END tipo,
                            COUNT(*) funciones, 100.0 * SUM(boletos_vendidos) / SUM(capacidad) occ,
                            SUM(CASE WHEN porcentaje_ocupacion < 10 THEN 1 ELSE 0 END) bajas, SUM(capacidad) cap
                     FROM fact_funciones f JOIN dim_horario h USING (horario_key) JOIN dim_fecha d USING (fecha_key)
                     WHERE f.fecha_key BETWEEN {yk(anio)[0]} AND {yk(anio)[1]} GROUP BY 1, 2""")
    peak = frame(f"""SELECT 100.0 * SUM(boletos_vendidos) / SUM(capacidad) occ,
                            SUM(CASE WHEN porcentaje_ocupacion >= 80 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) llenas
                     FROM fact_funciones f JOIN dim_horario h USING (horario_key) JOIN dim_fecha d USING (fecha_key)
                     WHERE f.fecha_key BETWEEN {yk(anio)[0]} AND {yk(anio)[1]} AND h.clasificacion_horario = 'Pico'
                       AND d.es_fin_semana = 1""").iloc[0]
    low = slot.sort_values("occ").iloc[0]
    tot_func = slot.funciones.sum()
    recomendaciones.append(dict(
        prioridad="Media", area="Programación de funciones",
        hallazgo=f"El turno {low.turno.lower()} {low.tipo} tiene la ocupación más baja de la cadena; en horario pico de fin de "
                 f"semana {peak.llenas:.1f} % de las funciones supera 80 % de ocupación.",
        indicador=f"Ocupación turno {low.turno.lower()} {low.tipo}: {low.occ:.1f} % ({int(low.funciones):,} funciones en {anio}); "
                  f"pico de fin de semana: {peak.occ:.1f} %.",
        interpretacion="Hay butacas ociosas en horarios de baja demanda y saturación en los horarios pico; la oferta no está "
                       "alineada con la demanda.",
        accion=f"Reducir funciones del turno {low.turno.lower()} {low.tipo} en salas grandes, moverlas a salas pequeñas y abrir "
               f"funciones adicionales los viernes y sábados entre 18:00 y 22:00 para los títulos más fuertes.",
        impacto=f"Reasignar 10 % de las funciones de ese turno ({int(0.1 * low.funciones):,} al año) libera capacidad operativa "
                f"que hoy atienden a sólo {0.1 * low.occ * low.cap / 100:,.0f} asistentes al año "
                f"(que pueden reubicarse en otros horarios).", tipo_impacto="Estimación"))

    # ---------------------------------------------------------------- géneros y películas
    gen = frame(f"""SELECT p.genero, SUM(m.funciones) funciones, SUM(m.asistentes) asis, 100.0 * SUM(m.boletos) / SUM(m.capacidad) occ,
                           1.0 * SUM(m.asistentes) / SUM(m.funciones) apf
                    FROM mart_pelicula_mensual m JOIN dim_pelicula p USING (pelicula_key)
                    WHERE anio_mes BETWEEN '{anio}-01' AND '{anio}-12' GROUP BY 1""")
    gen["share_func"] = 100 * gen.funciones / gen.funciones.sum()
    gen["share_asis"] = 100 * gen.asis / gen.asis.sum()
    gen["eficiencia"] = gen.share_asis / gen.share_func
    gbest = gen.sort_values("eficiencia", ascending=False).iloc[0]
    gworst = gen[gen.share_func > 3].sort_values("eficiencia").iloc[0]
    recomendaciones.append(dict(
        prioridad="Media", area="Cartelera",
        hallazgo=f"{gbest.genero} rinde más asistentes por función que su participación en la programación; "
                 f"{gworst.genero} rinde menos.",
        indicador=f"{gbest.genero}: {gbest.share_asis:.1f} % de la asistencia con {gbest.share_func:.1f} % de las funciones "
                  f"({gbest.apf:.0f} asistentes/función). {gworst.genero}: {gworst.share_asis:.1f} % con {gworst.share_func:.1f} % "
                  f"({gworst.apf:.0f}/función).",
        interpretacion="La mezcla de géneros por función puede optimizarse: cada función adicional del género eficiente "
                       "atrae, en promedio, más público.",
        accion=f"Dar prioridad a títulos de {gbest.genero.lower()} en salas de mayor capacidad y limitar {gworst.genero.lower()} "
               f"a horarios y salas de menor demanda, sin eliminar la diversidad de la cartelera.",
        impacto=f"Mover 5 % de las funciones de {gworst.genero.lower()} a {gbest.genero.lower()} añadiría "
                f"~{0.05 * gworst.funciones * (gbest.apf - gworst.apf):,.0f} asistentes al año.", tipo_impacto="Estimación"))

    topf = rows(f"""SELECT p.titulo, p.genero, p.tipo_lanzamiento, SUM(m.ingreso_taquilla) ingreso, SUM(m.asistentes) asis
                    FROM mart_pelicula_mensual m JOIN dim_pelicula p USING (pelicula_key)
                    WHERE anio_mes BETWEEN '{anio}-01' AND '{anio}-12' GROUP BY 1 ORDER BY ingreso DESC LIMIT 5""")
    tot_taq = yr.loc[anio].taq if anio in yr.index else None
    if topf and tot_taq:
        hallazgos.append(dict(titulo="Películas con mayor impacto comercial",
                              texto=f"«{topf[0]['titulo']}» ({topf[0]['genero'].lower()}) fue la película más taquillera de {anio} "
                                    f"con {_mxn(topf[0]['ingreso'])}. Los cinco títulos principales generaron "
                                    f"{100 * sum(t['ingreso'] for t in topf) / tot_taq:.0f} % de la taquilla del año.",
                              tono="neutral"))
    # Películas próximas con alto potencial (calendario de estrenos)
    apf_tipo = {r["tipo_lanzamiento"]: r["apf"] for r in rows(
        """SELECT p.tipo_lanzamiento, 1.0 * SUM(m.asistentes) / SUM(m.funciones) apf
           FROM mart_pelicula_mensual m JOIN dim_pelicula p USING (pelicula_key) GROUP BY 1""")}
    apf_gen = dict(zip(gen.genero, gen.apf))
    prox = rows("""SELECT titulo, genero, tipo_lanzamiento, fecha_estreno, distribuidora FROM dim_pelicula
                   WHERE fecha_estreno > ? AND fecha_estreno <= date(?, '+75 day') ORDER BY fecha_estreno""",
                (str(last), str(last)))
    for pz in prox:
        pz["indice_potencial"] = round((apf_tipo.get(pz["tipo_lanzamiento"], 0) / max(apf_tipo.values())) * 60 +
                                       (apf_gen.get(pz["genero"], 0) / max(apf_gen.values())) * 40)
    prox.sort(key=lambda x: -x["indice_potencial"])
    if prox:
        best = prox[0]
        recomendaciones.append(dict(
            prioridad="Alta", area="Cartelera",
            hallazgo=f"«{best['titulo']}» ({best['genero'].lower()}, {best['tipo_lanzamiento'].lower()}) se estrena el "
                     f"{best['fecha_estreno']} y es el próximo título con mayor potencial estimado.",
            indicador=f"Índice de potencial {best['indice_potencial']}/100, basado en la asistencia histórica por función de su "
                      f"tipo de lanzamiento ({apf_tipo.get(best['tipo_lanzamiento'], 0):.0f}) y de su género "
                      f"({apf_gen.get(best['genero'], 0):.0f}).",
            interpretacion="La primera y segunda semana concentran la mayor asistencia de un estreno; asegurar capacidad en "
                           "esas semanas captura la demanda antes de que decaiga.",
            accion="Asignar salas premium (IMAX / Macro XE / 4DX) y horarios pico en la semana de estreno, habilitar preventa "
                   "en la aplicación y preparar combos temáticos en dulcería.",
            impacto="Depende del desempeño real del estreno; se recomienda medirlo contra el pronóstico semanal.",
            tipo_impacto="Estimación cualitativa"))

    # ---------------------------------------------------------------- dulcería
    med_gasto = cx.gasto.median()
    low_g = cx.sort_values("gasto").iloc[0]
    oportunidad = (med_gasto - low_g.gasto) * low_g.asis
    recomendaciones.append(dict(
        prioridad="Alta", area="Dulcería",
        hallazgo=f"{low_g.nombre} tiene el menor gasto en dulcería por asistente de la cadena.",
        indicador=f"Gasto por asistente {anio}: {_mxn(low_g.gasto)} vs. mediana de la cadena {_mxn(med_gasto)}.",
        interpretacion="La asistencia existe, pero la conversión en dulcería es baja: hay oportunidad sin necesidad de atraer "
                       "más público.",
        accion="Impulsar combos y pedidos anticipados desde la app, revisar tiempos de fila en mostrador y probar "
               "precios escalonados en tamaños grandes.",
        impacto=f"Alcanzar la mediana de la cadena equivale a ~{_mxn(oportunidad)} adicionales al año.", tipo_impacto="Estimación"))
    oportunidades.append(f"Dulcería en {low_g.nombre}: ~{_mxn(oportunidad)} al año si alcanza el gasto mediano por asistente (estimación).")

    cat = frame(f"""SELECT substr(anio_mes, 1, 4) anio, pd.categoria, SUM(ingreso) ingreso, SUM(margen) margen
                    FROM mart_dulceria_mensual m JOIN dim_producto pd USING (producto_key) GROUP BY 1, 2""")
    cat["share"] = 100 * cat.ingreso / cat.groupby("anio").ingreso.transform("sum")
    first_y = cat.anio.min()
    piv = cat.pivot(index="categoria", columns="anio", values="share")
    combos = piv.loc["Combos"] if "Combos" in piv.index else None
    ch = frame("""SELECT substr(anio_mes, 1, 4) anio, cn.canal_codigo, SUM(boletos) b FROM mart_taquilla_mensual m
                  JOIN dim_canal cn USING (canal_key) GROUP BY 1, 2""")
    ch["share"] = 100 * ch.b / ch.groupby("anio").b.transform("sum")
    chp = ch.pivot(index="canal_codigo", columns="anio", values="share")
    dch = frame("""SELECT substr(anio_mes, 1, 4) anio, cn.canal_codigo, SUM(ingreso) i FROM mart_dulceria_mensual m
                   JOIN dim_canal cn USING (canal_key) GROUP BY 1, 2""")
    dch["share"] = 100 * dch.i / dch.groupby("anio").i.transform("sum")
    dchp = dch.pivot(index="canal_codigo", columns="anio", values="share")
    y0, y1 = str(first_y), str(anio)
    habitos = []
    if "APP" in chp.index and y1 in chp.columns:
        dig0 = chp.loc[["APP", "WEB"], y0].sum()
        dig1 = chp.loc[["APP", "WEB"], y1].sum()
        habitos.append(f"La venta digital de boletos (app + web) pasó de {dig0:.1f} % en {y0} a {dig1:.1f} % en {y1}; la taquilla "
                       f"tradicional bajó de {chp.loc['TAQ', y0]:.1f} % a {chp.loc['TAQ', y1]:.1f} %.")
        recomendaciones.append(dict(
            prioridad="Media", area="Canales digitales",
            hallazgo="El público migra a la compra digital de boletos y de dulcería.",
            indicador=f"Boletos por app + web: {dig0:.1f} % ({y0}) → {dig1:.1f} % ({y1}). Dulcería por app: "
                      f"{dchp.loc['APP', y0]:.1f} % → {dchp.loc['APP', y1]:.1f} %.",
            interpretacion="La app es ya el canal de mayor crecimiento; cada compra digital permite ofrecer dulcería "
                           "anticipada y reduce filas en taquilla.",
            accion="Ofrecer combos exclusivos en la app al comprar boletos, reasignar personal de taquilla a dulcería en horas "
                   "pico y convertir posiciones de taquilla en kioscos.",
            impacto="Por cada punto porcentual de asistentes que agrega dulcería en la app, el ingreso de dulcería crece en "
                    "proporción a su gasto promedio; medir con pruebas A/B.", tipo_impacto="Estimación cualitativa"))
    if combos is not None:
        habitos.append(f"Los combos pasaron de {combos[y0]:.1f} % a {combos[y1]:.1f} % del ingreso de dulcería, mientras las "
                       f"bebidas sueltas pierden participación: el cliente prefiere paquetes.")

    # ---------------------------------------------------------------- promociones
    promo = frame("""SELECT pr.promocion_codigo, pr.nombre, pr.tipo, pr.vigencia_inicio, pr.vigencia_fin, d.dia_semana,
                            100.0 * SUM(boletos_vendidos) / SUM(capacidad) occ, COUNT(*) n
                     FROM fact_funciones f JOIN dim_promocion pr USING (promocion_key) JOIN dim_fecha d USING (fecha_key)
                     GROUP BY pr.promocion_codigo""")
    ev = promo[promo.tipo == "Evento temporal"]
    if len(ev):
        e = ev.iloc[-1]
        ini, fin = date.fromisoformat(e.vigencia_inicio), date.fromisoformat(e.vigencia_fin)
        around = one(f"""SELECT 100.0 * SUM(boletos) / SUM(capacidad) occ, SUM(asistentes) / COUNT(DISTINCT fecha_key) asis
                         FROM mart_diario_complejo WHERE (fecha_key BETWEEN {(ini - timedelta(days=21)):%Y%m%d} AND {(ini - timedelta(days=1)):%Y%m%d})
                            OR (fecha_key BETWEEN {(fin + timedelta(days=1)):%Y%m%d} AND {(fin + timedelta(days=21)):%Y%m%d})""")
        during = one(f"""SELECT 100.0 * SUM(boletos) / SUM(capacidad) occ, SUM(asistentes) / COUNT(DISTINCT fecha_key) asis,
                                SUM(ingreso_taquilla) / SUM(boletos) ticket
                         FROM mart_diario_complejo WHERE fecha_key BETWEEN {ini:%Y%m%d} AND {fin:%Y%m%d}""")
        lowm = frame(f"""SELECT d.nombre_mes, 100.0 * SUM(boletos) / SUM(capacidad) occ FROM mart_diario_complejo m
                         JOIN dim_fecha d USING (fecha_key) WHERE d.anio = {anio} GROUP BY d.mes ORDER BY occ""").iloc[:2]
        if around and during and around["asis"]:
            uplift = 100 * (during["asis"] / around["asis"] - 1)
            recomendaciones.append(dict(
                prioridad="Media", area="Promociones",
                hallazgo=f"La «{e.nombre}» elevó la asistencia diaria aun con 50 % de descuento.",
                indicador=f"Asistencia diaria durante el evento: {during['asis']:,.0f} vs {around['asis']:,.0f} en las tres semanas "
                          f"previas y posteriores ({_pct(uplift)}). Meses de menor ocupación en {anio}: "
                          f"{lowm.iloc[0].nombre_mes} ({lowm.iloc[0].occ:.1f} %) y {lowm.iloc[1].nombre_mes} ({lowm.iloc[1].occ:.1f} %).",
                interpretacion="En temporada baja el precio es una palanca efectiva: la ocupación sube y la dulcería (sin "
                               "descuento) compensa parte del menor ticket.",
                accion=f"Programar promociones de precio en {lowm.iloc[0].nombre_mes.lower()} y {lowm.iloc[1].nombre_mes.lower()}, "
                       f"concentradas entre lunes y jueves, y acompañarlas con combos de dulcería a precio regular.",
                impacto="Requiere validar el efecto neto (más asistentes × menor ticket + dulcería) con un piloto en 2-3 complejos.",
                tipo_impacto="Estimación cualitativa"))
            oportunidades.append(f"Promociones en temporada baja: la última semana del cine elevó {_pct(uplift)} la asistencia diaria.")
    mier = promo[promo.promocion_codigo == "MIERCOLES"]

    # ---------------------------------------------------------------- asistencia y consumo
    occ_y = yr.loc[anio] if anio in yr.index else None
    comport = []
    if occ_y is not None:
        comport.append(f"La ocupación promedio de {anio} fue de {100 * occ_y.bol / occ_y.cap:.1f} %; la cadena tiene capacidad "
                       f"ociosa fuera de fines de semana, vacaciones y estrenos fuertes.")
    sem = one(f"""SELECT AVG(CASE WHEN semana_exhibicion = 1 THEN asistentes END) s1, AVG(CASE WHEN semana_exhibicion = 4 THEN asistentes END) s4
                  FROM fact_funciones WHERE fecha_key BETWEEN {yk(anio)[0]} AND {yk(anio)[1]}""")
    if sem and sem["s1"]:
        comport.append(f"Una película pierde en promedio {100 * (1 - sem['s4'] / sem['s1']):.0f} % de su asistencia por función entre "
                       f"su primera y su cuarta semana en cartelera.")
    corr = one(f"""SELECT COUNT(*) n, AVG(asistentes) ma, AVG(ingreso_dulceria) md,
                          AVG(asistentes * ingreso_dulceria) mad, AVG(asistentes * asistentes) maa, AVG(ingreso_dulceria * ingreso_dulceria) mdd
                   FROM mart_diario_complejo WHERE fecha_key BETWEEN {yk(anio)[0]} AND {yk(anio)[1]}""")
    if corr and corr["n"]:
        cv = (corr["mad"] - corr["ma"] * corr["md"]) / (((corr["maa"] - corr["ma"] ** 2) * (corr["mdd"] - corr["md"] ** 2)) ** 0.5)
        comport.append(f"La correlación entre asistencia diaria e ingreso de dulcería es de {cv:.2f}: más público implica más "
                       f"ventas, pero el gasto por persona varía entre complejos y temporadas.")

    if caidas is not None and len(caidas) == 0 and not alertas:
        riesgos.append("No se detectaron complejos con caídas atípicas en el último semestre.")
    riesgos.append("Alta dependencia de los estrenos: los cinco títulos principales concentran una parte relevante de la "
                   "taquilla y su desempeño no puede anticiparse con precisión.")
    riesgos.append("La migración a canales digitales reduce el tráfico frente al mostrador; si la app no ofrece dulcería, "
                   "se pierde la venta por impulso.")

    return dict(anio=anio, anio_anterior=prev, ultimo_dato=str(last), hallazgos=hallazgos, tendencia=tendencia,
                mejores_complejos=mejores, menores_complejos=peores, peliculas_top=topf, proximos_estrenos=prox[:8],
                comportamiento=comport, habitos=habitos, modelo=modelo, alertas=alertas, riesgos=riesgos,
                oportunidades=oportunidades, recomendaciones=recomendaciones)
