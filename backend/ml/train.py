"""MINERÍA DE DATOS · Modelo predictivo de ingresos diarios por complejo.

Objetivo: pronosticar el ingreso total diario (taquilla + dulcería) y la asistencia de
cada complejo para los próximos 7 y 30 días.

Prevención de fuga de información (data leakage)
-------------------------------------------------
* Todas las variables históricas (rezagos y promedios móviles) usan un rezago mínimo de
  35 días.  Así, el mismo modelo puede pronosticar hasta 35 días hacia adelante sin
  necesitar valores que todavía no se conocen (pronóstico directo, no recursivo).
* Las variables de calendario (día, mes, festivos, vacaciones) y el calendario de
  estrenos (fecha y tipo de lanzamiento, que las distribuidoras anuncian con meses de
  anticipación) sí se conocen de antemano.
* No se usan variables del mismo día que se pretende predecir (boletos, funciones
  efectivamente programadas, dulcería del día, etc.).

Validación: división cronológica entrenamiento / validación / prueba (sin mezclar el orden
temporal).  El modelo se elige por el MAE en validación y se reporta en prueba.  Después
se reentrena con todo el histórico para generar el pronóstico.

Uso: python -m backend.ml.train
"""
import json
import sqlite3
import time
from datetime import datetime, timedelta

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from backend.config import DW_DB, MODELS_DIR, SEED

MIN_LAG = 35
HORIZON = 30

FEATURES_DOC = {
    "dia_semana": "Día de la semana (1=lunes … 7=domingo)",
    "mes": "Mes del año",
    "anio": "Año (captura tendencia de largo plazo)",
    "semana_anio": "Semana ISO del año",
    "dia_anio_sin": "Estacionalidad anual (seno del día del año)",
    "dia_anio_cos": "Estacionalidad anual (coseno del día del año)",
    "es_fin_semana": "Sábado o domingo",
    "es_viernes": "Viernes (inicio del fin de semana cinematográfico)",
    "es_vacaciones": "Periodo vacacional escolar",
    "es_festivo": "Día festivo",
    "temporada_alta": "Temporada alta",
    "temporada_baja": "Temporada baja",
    "estrenos_7d": "Películas estrenadas en los últimos 7 días (calendario de estrenos)",
    "blockbusters_21d": "Estrenos tipo blockbuster en los últimos 21 días",
    "familiares_21d": "Estrenos de animación o familiares en los últimos 21 días",
    "terror_21d": "Estrenos de terror en los últimos 21 días",
    "evento_promocional": "Evento promocional planificado (p. ej. semana del cine a precio especial)",
    "complejo_*": "Complejo (variable indicadora)",
    "num_salas": "Número de salas del complejo",
    "premium": "Complejo con salas premium",
    "dias_desde_apertura": "Antigüedad del complejo en días (limitada a 3 años)",
    "ingreso_lag35": "Ingreso del mismo complejo hace 35 días (mismo día de la semana)",
    "ingreso_lag42": "Ingreso hace 42 días",
    "ingreso_lag364": "Ingreso hace 364 días (mismo día de la semana del año anterior)",
    "ingreso_media28_lag35": "Promedio de ingreso de 28 días que terminó hace 35 días",
    "ingreso_media_dow_lag35": "Promedio de las últimas 4 semanas para el mismo día de la semana (con rezago de 35 días)",
    "asistencia_media28_lag35": "Asistencia promedio de 28 días con rezago de 35 días",
    "ocupacion_media28_lag35": "Ocupación promedio de 28 días con rezago de 35 días",
    "dulceria_por_asistente_lag35": "Gasto en dulcería por asistente (28 días, rezago de 35 días)",
    "funciones_media28_lag35": "Funciones diarias promedio (28 días, rezago de 35 días)",
    "tendencia_lag35": "Razón entre el promedio de 28 días y el de 91 días (rezago de 35 días)",
}


def load_daily(con):
    df = pd.read_sql_query("""
        SELECT m.fecha_key, d.fecha, d.dia_semana, d.mes, d.anio, d.semana_anio, d.es_fin_semana,
               d.es_vacaciones, d.es_festivo, d.temporada, c.complejo_key, c.complejo_codigo, c.nombre complejo,
               c.num_salas, c.tipo_complejo, c.fecha_apertura,
               m.funciones, m.capacidad, m.boletos, m.asistentes,
               m.ingreso_taquilla, m.ingreso_dulceria, m.ingreso_taquilla + m.ingreso_dulceria ingreso_total
        FROM mart_diario_complejo m JOIN dim_fecha d USING (fecha_key) JOIN dim_complejo c USING (complejo_key)
        ORDER BY c.complejo_key, m.fecha_key""", con, parse_dates=["fecha", "fecha_apertura"])
    return df


def release_features(con, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Variables del calendario de estrenos (conocido con anticipación)."""
    pel = pd.read_sql_query("SELECT fecha_estreno, genero, tipo_lanzamiento FROM dim_pelicula", con, parse_dates=["fecha_estreno"])
    out = pd.DataFrame(index=dates)
    for name, mask, days in (("estrenos_7d", pel.index == pel.index, 7),
                             ("blockbusters_21d", pel["tipo_lanzamiento"] == "Blockbuster", 21),
                             ("familiares_21d", pel["genero"].isin(["Animación", "Familiar"]), 21),
                             ("terror_21d", pel["genero"] == "Terror", 21)):
        rel = pel.loc[mask, "fecha_estreno"].values
        out[name] = [int(((rel <= d) & (rel > d - np.timedelta64(days, "D"))).sum()) for d in dates.values]
    # Eventos promocionales planificados (vigencia conocida con anticipación)
    ev = pd.read_sql_query("SELECT vigencia_inicio, vigencia_fin FROM dim_promocion WHERE tipo = 'Evento temporal'", con)
    out["evento_promocional"] = 0
    for a, b in ev.itertuples(index=False):
        out.loc[(out.index >= a) & (out.index <= b), "evento_promocional"] = 1
    return out


def calendar_frame(con, start, end):
    cal = pd.read_sql_query("SELECT fecha, dia_semana, mes, anio, semana_anio, es_fin_semana, es_vacaciones, es_festivo, temporada "
                            "FROM dim_fecha WHERE fecha BETWEEN ? AND ?", con, params=(str(start.date()), str(end.date())),
                            parse_dates=["fecha"])
    return cal


def build_features(df: pd.DataFrame, rel: pd.DataFrame, complexes: list) -> pd.DataFrame:
    df = df.sort_values(["complejo_key", "fecha"]).copy()
    g = df.groupby("complejo_key")
    s = lambda col, k: g[col].shift(k)
    df["ingreso_lag35"] = s("ingreso_total", 35)
    df["ingreso_lag42"] = s("ingreso_total", 42)
    df["ingreso_lag364"] = s("ingreso_total", 364)
    roll = lambda col, w: g[col].transform(lambda x: x.shift(MIN_LAG).rolling(w, min_periods=max(7, w // 2)).mean())
    df["ingreso_media28_lag35"] = roll("ingreso_total", 28)
    df["_media91"] = roll("ingreso_total", 91)
    df["tendencia_lag35"] = df["ingreso_media28_lag35"] / df["_media91"]
    df["ingreso_media_dow_lag35"] = df.groupby(["complejo_key", "dia_semana"])["ingreso_total"].transform(
        lambda x: x.shift(5).rolling(4, min_periods=2).mean())   # 5 semanas = 35 días
    df["asistencia_media28_lag35"] = roll("asistentes", 28)
    df["ocupacion_media28_lag35"] = g["boletos"].transform(lambda x: x.shift(MIN_LAG).rolling(28, min_periods=14).sum()) / \
        g["capacidad"].transform(lambda x: x.shift(MIN_LAG).rolling(28, min_periods=14).sum())
    df["dulceria_por_asistente_lag35"] = g["ingreso_dulceria"].transform(lambda x: x.shift(MIN_LAG).rolling(28, min_periods=14).sum()) / \
        g["asistentes"].transform(lambda x: x.shift(MIN_LAG).rolling(28, min_periods=14).sum())
    df["funciones_media28_lag35"] = roll("funciones", 28)
    return add_static(df, rel, complexes)


def add_static(df, rel, complexes):
    doy = df["fecha"].dt.dayofyear
    df["dia_anio_sin"] = np.sin(2 * np.pi * doy / 365.25)
    df["dia_anio_cos"] = np.cos(2 * np.pi * doy / 365.25)
    df["es_viernes"] = (df["dia_semana"] == 5).astype(int)
    df["temporada_alta"] = (df["temporada"] == "Alta").astype(int)
    df["temporada_baja"] = (df["temporada"] == "Baja").astype(int)
    df["premium"] = (df["tipo_complejo"] == "Premium").astype(int)
    df["dias_desde_apertura"] = (df["fecha"] - df["fecha_apertura"]).dt.days.clip(upper=1095)
    df = df.join(rel, on="fecha")
    for c in complexes:
        df[f"complejo_{c}"] = (df["complejo_codigo"] == c).astype(int)
    return df


def feature_columns(complexes):
    base = [k for k in FEATURES_DOC if k != "complejo_*"]
    return base + [f"complejo_{c}" for c in complexes]


def metrics(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    mask = y > 1000   # MAPE sólo con valores reales no cercanos a cero
    return dict(mae=float(mean_absolute_error(y, p)), rmse=float(np.sqrt(mean_squared_error(y, p))),
                mape=float(np.mean(np.abs((y[mask] - p[mask]) / y[mask])) * 100) if mask.any() else None,
                r2=float(r2_score(y, p)), n=int(len(y)))


def candidate_models():
    return {
        "Regresión lineal (Ridge)": make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "Random Forest": RandomForestRegressor(n_estimators=300, min_samples_leaf=3, max_features=0.5,
                                               n_jobs=-1, random_state=SEED),
        "Gradient Boosting": HistGradientBoostingRegressor(max_iter=500, learning_rate=0.05, max_leaf_nodes=31,
                                                           min_samples_leaf=20, l2_regularization=1.0, random_state=SEED),
        "Gradient Boosting (objetivo logarítmico)": TransformedTargetRegressor(
            regressor=HistGradientBoostingRegressor(max_iter=500, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=20,
                                                    l2_regularization=1.0, random_state=SEED),
            func=np.log1p, inverse_func=np.expm1),
    }


def fill(X, med):
    return X.fillna(med)


def train(progress=None) -> dict:
    progress = progress or (lambda m, p: None)
    t0 = time.time()
    con = sqlite3.connect(DW_DB)
    progress("Leyendo el mart diario del Data Warehouse", 5)
    daily = load_daily(con)
    complexes = sorted(daily["complejo_codigo"].unique())
    last_date = daily["fecha"].max()
    future_dates = pd.date_range(last_date + timedelta(days=1), periods=HORIZON)
    all_dates = pd.date_range(daily["fecha"].min(), future_dates[-1])
    rel = release_features(con, all_dates)
    progress("Construyendo variables (rezago mínimo de 35 días)", 15)
    feat = build_features(daily, rel, complexes)
    cols = feature_columns(complexes)
    data = feat.dropna(subset=["ingreso_media28_lag35", "ingreso_lag42", "ingreso_media_dow_lag35"]).copy()

    # ---- División cronológica: 70 % / 15 % / 15 % de las fechas disponibles
    dates = np.sort(data["fecha"].unique())
    d_val, d_test = dates[int(len(dates) * 0.70)], dates[int(len(dates) * 0.85)]
    tr, va, te = data[data.fecha < d_val], data[(data.fecha >= d_val) & (data.fecha < d_test)], data[data.fecha >= d_test]
    med = tr[cols].median()
    target = "ingreso_total"

    results, fitted = [], {}
    # Línea base ingenua: promedio del mismo día de la semana de 5-8 semanas atrás
    for name, part in (("validacion", va), ("prueba", te)):
        results.append(dict(modelo="Línea base (promedio mismo día, 5-8 semanas)", conjunto=name,
                            **metrics(part[target], part["ingreso_media_dow_lag35"])))
    for i, (name, model) in enumerate(candidate_models().items()):
        progress(f"Entrenando {name}", 25 + 15 * i)
        model.fit(fill(tr[cols], med), tr[target])
        fitted[name] = model
        for pname, part in (("entrenamiento", tr), ("validacion", va), ("prueba", te)):
            results.append(dict(modelo=name, conjunto=pname, **metrics(part[target], model.predict(fill(part[cols], med)))))
    res = pd.DataFrame(results)
    best = res[(res.conjunto == "validacion") & (res.modelo.isin(fitted))].sort_values("mae").iloc[0]["modelo"]
    model = fitted[best]
    progress(f"Modelo seleccionado: {best}. Calculando importancia de variables", 72)
    pi = permutation_importance(model, fill(va[cols], med), va[target], n_repeats=5, random_state=SEED,
                                scoring="neg_mean_absolute_error", n_jobs=-1)
    imp = pd.DataFrame({"variable": cols, "importancia": pi.importances_mean}).sort_values("importancia", ascending=False)
    comp_imp = imp[imp.variable.str.startswith("complejo_")]["importancia"].sum()
    imp = pd.concat([imp[~imp.variable.str.startswith("complejo_")],
                     pd.DataFrame([{"variable": "complejo_*", "importancia": comp_imp}])]).sort_values("importancia", ascending=False)

    test_pred = te[["fecha", "complejo_key", target, "asistentes"]].copy()
    test_pred["prediccion"] = model.predict(fill(te[cols], med))
    # Error agregado: suma semanal por complejo y total diario de la cadena (uso de negocio)
    tp = test_pred.assign(semana=test_pred.fecha.dt.to_period("W"))
    wk = tp.groupby(["complejo_key", "semana"])[[target, "prediccion"]].sum()
    wk = wk[tp.groupby(["complejo_key", "semana"]).size() == 7]
    ch = tp.groupby("fecha")[[target, "prediccion"]].sum()
    agregadas = dict(semanal_por_complejo=metrics(wk[target], wk["prediccion"]),
                     diario_cadena=metrics(ch[target], ch["prediccion"]))
    resid = (va[target] - model.predict(fill(va[cols], med))) / va["ingreso_media28_lag35"]

    # ---- Modelo de asistencia (mismo algoritmo y variables)
    progress("Entrenando modelo de asistencia", 80)
    att_model = candidate_models()[best]
    att_model.fit(fill(tr[cols], med), tr["asistentes"])
    att_metrics = metrics(te["asistentes"], att_model.predict(fill(te[cols], med)))
    test_pred["asistencia_pred"] = att_model.predict(fill(te[cols], med))

    # ---- Reentrenamiento con todo el histórico y pronóstico a 30 días
    progress("Reentrenando con todo el histórico y pronosticando 30 días", 88)
    med_all = data[cols].median()
    final = candidate_models()[best].fit(fill(data[cols], med_all), data[target])
    final_att = candidate_models()[best].fit(fill(data[cols], med_all), data["asistentes"])
    cal = calendar_frame(con, future_dates[0], future_dates[-1])
    cinfo = daily.drop_duplicates("complejo_key")[["complejo_key", "complejo_codigo", "complejo", "num_salas",
                                                    "tipo_complejo", "fecha_apertura"]]
    fut = cinfo.assign(_k=1).merge(cal.assign(_k=1), on="_k").drop(columns="_k")
    for c in ("funciones", "capacidad", "boletos", "asistentes", "ingreso_taquilla", "ingreso_dulceria", "ingreso_total"):
        fut[c] = np.nan
    hist = daily[[c for c in fut.columns]]
    combo = build_features(pd.concat([hist, fut[hist.columns]], ignore_index=True), rel, complexes)
    fut_feat = combo[combo.fecha > last_date].copy()
    fut_feat["ingreso_pred"] = final.predict(fill(fut_feat[cols], med_all))
    fut_feat["asistencia_pred"] = final_att.predict(fill(fut_feat[cols], med_all))
    q_lo, q_hi = np.nanquantile(resid, [0.10, 0.90])
    fut_feat["ingreso_li"] = (fut_feat["ingreso_pred"] + q_lo * fut_feat["ingreso_media28_lag35"]).clip(lower=0)
    fut_feat["ingreso_ls"] = fut_feat["ingreso_pred"] + q_hi * fut_feat["ingreso_media28_lag35"]

    # ---- Persistencia
    progress("Guardando resultados en el Data Warehouse", 95)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(dict(modelo=final, modelo_asistencia=final_att, columnas=cols, medianas=med_all, algoritmo=best),
                MODELS_DIR / "modelo_ingresos.joblib")
    run = dict(entrenado_en=datetime.now().isoformat(timespec="seconds"), algoritmo=best, objetivo="Ingreso total diario por complejo (MXN)",
               horizonte_dias=HORIZON, rezago_minimo=MIN_LAG, ultimo_dato=str(last_date.date()),
               entrenamiento=[str(pd.Timestamp(dates[0]).date()), str((pd.Timestamp(d_val) - timedelta(days=1)).date())],
               validacion=[str(pd.Timestamp(d_val).date()), str((pd.Timestamp(d_test) - timedelta(days=1)).date())],
               prueba=[str(pd.Timestamp(d_test).date()), str(pd.Timestamp(dates[-1]).date())],
               filas=dict(entrenamiento=len(tr), validacion=len(va), prueba=len(te)),
               metricas_asistencia_prueba=att_metrics, metricas_agregadas_prueba=agregadas, intervalo="80 % (cuantiles 10-90 de los residuos de validación)",
               duracion_seg=round(time.time() - t0, 1), variables=len(cols))
    con.executescript("""
        DROP TABLE IF EXISTS ml_ejecucion; DROP TABLE IF EXISTS ml_metricas; DROP TABLE IF EXISTS ml_prediccion_prueba;
        DROP TABLE IF EXISTS ml_pronostico; DROP TABLE IF EXISTS ml_importancia;
        CREATE TABLE ml_ejecucion (id INTEGER PRIMARY KEY, detalle TEXT NOT NULL);
        CREATE TABLE ml_metricas (modelo TEXT, conjunto TEXT, mae REAL, rmse REAL, mape REAL, r2 REAL, n INTEGER, seleccionado INTEGER);
        CREATE TABLE ml_prediccion_prueba (fecha TEXT, complejo_key INTEGER REFERENCES dim_complejo(complejo_key),
            ingreso_real REAL, ingreso_pred REAL, asistencia_real INTEGER, asistencia_pred REAL);
        CREATE TABLE ml_pronostico (fecha TEXT, complejo_key INTEGER REFERENCES dim_complejo(complejo_key),
            ingreso_pred REAL, ingreso_li REAL, ingreso_ls REAL, asistencia_pred REAL);
        CREATE TABLE ml_importancia (variable TEXT, descripcion TEXT, importancia REAL);""")
    con.execute("INSERT INTO ml_ejecucion VALUES (1, ?)", (json.dumps(run, ensure_ascii=False),))
    res["seleccionado"] = (res.modelo == best).astype(int)
    con.executemany("INSERT INTO ml_metricas VALUES (?,?,?,?,?,?,?,?)",
                    res[["modelo", "conjunto", "mae", "rmse", "mape", "r2", "n", "seleccionado"]].itertuples(index=False, name=None))
    con.executemany("INSERT INTO ml_prediccion_prueba VALUES (?,?,?,?,?,?)",
                    [(str(r.fecha.date()), int(r.complejo_key), float(r.ingreso_total), float(r.prediccion),
                      int(r.asistentes), float(r.asistencia_pred)) for r in test_pred.itertuples()])
    con.executemany("INSERT INTO ml_pronostico VALUES (?,?,?,?,?,?)",
                    [(str(r.fecha.date()), int(r.complejo_key), float(r.ingreso_pred), float(r.ingreso_li),
                      float(r.ingreso_ls), float(r.asistencia_pred)) for r in fut_feat.itertuples()])
    con.executemany("INSERT INTO ml_importancia VALUES (?,?,?)",
                    [(r.variable, FEATURES_DOC.get(r.variable, r.variable), float(r.importancia)) for r in imp.itertuples()])
    con.commit()
    con.close()
    progress("Modelo entrenado", 100)
    return dict(run=run, metricas=res.to_dict("records"))


if __name__ == "__main__":
    out = train(progress=lambda m, p: print(f"[{p:3d}%] {m}"))
    print(json.dumps(out["run"], ensure_ascii=False, indent=1))
    df = pd.DataFrame(out["metricas"])
    with pd.option_context("display.width", 160, "display.float_format", "{:,.3f}".format):
        print(df[df.conjunto != "entrenamiento"].to_string(index=False))
