// Modelo predictivo e Inteligencia de negocios.
import { api, card, dataTable, esc, fmt, h, loading, pollTask, state } from '../core.js';
import { barChart, lineChart, PALETTE, scatter } from '../charts.js';

function add(parent, title, sub, cls) { const c = card(title, sub, cls); parent.appendChild(c); return c.querySelector('.card-body'); }
function grid(root, cls) { const g = h(`<div class="grid ${cls}"></div>`); root.appendChild(g); return g; }

export async function viewModelo(root, stale) {
  const top = h('<div></div>'); root.appendChild(top); loading(top);
  const sel = state.filtros.complejo || '';
  const d = await api('/api/modelo' + (sel ? `?complejo=${sel}` : ''));
  if (stale()) return;
  top.remove();
  if (!d.entrenado) { root.appendChild(h('<div class="intro">El modelo aún no ha sido entrenado. Ejecuta el proceso desde la sección ETL.</div>')); return; }
  const info = d.info;
  const M = (m, c) => d.metricas.find(r => r.modelo === m && r.conjunto === c);
  const best = M(info.algoritmo, 'prueba'), bestVal = M(info.algoritmo, 'validacion');
  const base = d.metricas.find(r => r.modelo.startsWith('Línea base') && r.conjunto === 'prueba');
  const agg = info.metricas_agregadas_prueba || {};
  root.appendChild(h(`<div class="intro"><b>Objetivo:</b> ${esc(info.objetivo)}, con horizonte de ${info.horizonte_dias} días. Se compararon modelos de regresión lineal, Random Forest y Gradient Boosting contra una línea base ingenua; se eligió <b>${esc(info.algoritmo)}</b> por tener el menor MAE en validación.
    <b>División cronológica</b> (sin mezclar el orden temporal): entrenamiento ${info.entrenamiento[0]} a ${info.entrenamiento[1]} (${fmt.int(info.filas.entrenamiento)} filas), validación ${info.validacion[0]} a ${info.validacion[1]} (${fmt.int(info.filas.validacion)}), prueba ${info.prueba[0]} a ${info.prueba[1]} (${fmt.int(info.filas.prueba)}).
    <b>Sin fuga de información:</b> toda variable histórica tiene un rezago mínimo de ${info.rezago_minimo} días; sólo se usan datos conocidos de antemano (calendario, estrenos programados, eventos promocionales planificados). Entrenado el ${esc(info.entrenado_en.replace('T', ' '))} con ${info.variables} variables.</div>`));

  const mc = add(root, `Desempeño en el conjunto de prueba · ${info.algoritmo}`, 'Métricas calculadas sobre datos que el modelo nunca vio durante el entrenamiento ni la selección');
  mc.innerHTML = `<div class="metric-grid">
      <div class="metric"><span>MAE · error absoluto medio</span><b>${fmt.mxn(best.mae, true)}</b><p>En promedio, el pronóstico diario de un complejo se desvía esa cantidad del valor real.</p></div>
      <div class="metric"><span>RMSE · raíz del error cuadrático medio</span><b>${fmt.mxn(best.rmse, true)}</b><p>Como el MAE, pero penaliza más los errores grandes (días atípicos). Si es mucho mayor que el MAE hay errores grandes ocasionales.</p></div>
      <div class="metric"><span>MAPE · error porcentual medio</span><b>${fmt.pct(best.mape)}</b><p>Error relativo promedio por complejo-día (se excluyen valores reales menores a $1,000). Línea base: ${fmt.pct(base?.mape)}.</p></div>
      <div class="metric"><span>R² · coeficiente de determinación</span><b>${best.r2.toFixed(3)}</b><p>Proporción de la variación del ingreso que explica el modelo (1 = perfecto, 0 = igual que predecir el promedio). Línea base: ${base?.r2.toFixed(3)}.</p></div>
    </div>
    <div class="explain" style="margin-top:12px">
      <div><b>Agregado semanal por complejo:</b> MAPE ${fmt.pct(agg.semanal_por_complejo?.mape)}, R² ${agg.semanal_por_complejo?.r2?.toFixed(3)}. Al sumar días los errores se compensan parcialmente.</div>
      <div><b>Total diario de la cadena:</b> MAPE ${fmt.pct(agg.diario_cadena?.mape)}, R² ${agg.diario_cadena?.r2?.toFixed(3)}.</div>
      <div><b>Modelo de asistencia:</b> MAE ${fmt.int(info.metricas_asistencia_prueba.mae)} personas/día, MAPE ${fmt.pct(info.metricas_asistencia_prueba.mape)}, R² ${info.metricas_asistencia_prueba.r2.toFixed(3)}.</div>
      <div><b>Interpretación honesta:</b> el error restante proviene principalmente del éxito de cada estreno, que no puede conocerse antes de su exhibición. Validación: MAPE ${fmt.pct(bestVal.mape)}; prueba: ${fmt.pct(best.mape)}.</div>
    </div>`;

  const cx = state.meta.complejos.find(c => String(c.complejo_key) === String(sel));
  const ctl = h(`<div class="period-chip">Ámbito de las gráficas: <select id="m-cx" style="border:0;background:none;font-weight:700"><option value="">Toda la cadena</option>${state.meta.complejos.map(c => `<option value="${c.complejo_key}" ${String(c.complejo_key) === String(sel) ? 'selected' : ''}>${esc(c.nombre)}</option>`).join('')}</select></div>`);
  root.appendChild(ctl);
  ctl.querySelector('select').addEventListener('change', e => { state.filtros.complejo = e.target.value; state.filtros.ciudad = ''; root.innerHTML = ''; viewModelo(root, stale); });

  const fc = add(root, `Pronóstico de ingresos · próximos ${info.horizonte_dias} días · ${cx ? cx.nombre : 'toda la cadena'}`, `Últimos 60 días reales y pronóstico con intervalo del ${esc(info.intervalo)}`);
  const g1 = grid(root, 'g-wide');
  const rv = add(g1, 'Ingresos reales vs. estimados (periodo de prueba)', 'Suma diaria del ámbito seleccionado');
  const sc = add(g1, 'Dispersión real vs. estimado', 'Complejo-día; la diagonal es la predicción perfecta');
  const g2 = grid(root, 'g-wide');
  const cmp = add(g2, 'Comparación de modelos', 'El modelo se elige por el MAE en validación y se reporta en prueba');
  const imp = add(g2, 'Importancia de las variables', 'Aumento del MAE al permutar cada variable (validación)');
  const pc = add(root, 'Pronóstico por complejo y alertas de rendimiento', 'Ordena por variación para identificar posibles caídas · la brecha compara lo real vs. lo estimado en los últimos 90 días de prueba');
  const tr = add(root, 'Reentrenar el modelo', '');

  const hist = d.historico, pron = d.pronostico;
  const labels = [...hist.map(r => r.fecha), ...pron.map(r => r.fecha)];
  const p7 = pron.slice(0, 7).reduce((a, r) => a + r.pred, 0), p30 = pron.reduce((a, r) => a + r.pred, 0), a30 = pron.reduce((a, r) => a + r.asistencia, 0);
  fc.insertAdjacentHTML('beforeend', `<div class="metric-grid" style="margin-bottom:10px">
      <div class="metric"><span>Ingreso estimado · próximos 7 días</span><b>${fmt.mxn(p7)}</b></div>
      <div class="metric"><span>Ingreso estimado · próximos 30 días</span><b>${fmt.mxn(p30)}</b></div>
      <div class="metric"><span>Asistencia estimada · 30 días</span><b>${fmt.int(a30)}</b></div>
      <div class="metric"><span>Cambio vs. últimos 30 días reales (incluye estacionalidad)</span><b>${fmt.var(100 * (p30 / hist.slice(-30).reduce((a, r) => a + r.real, 0) - 1))}</b></div></div><div id="fc-chart"></div>`);
  lineChart(fc.querySelector('#fc-chart'), { labels, xFormat: fmt.fecha, yFormat: fmt.mxn, height: 280, marks: [{ at: pron[0]?.fecha, label: 'Inicio del pronóstico' }],
    series: [{ name: 'Real', values: [...hist.map(r => r.real), ...pron.map(() => null)], color: '#0b1f4b', noDots: true },
      { name: 'Pronóstico', values: [...hist.map(() => null), ...pron.map(r => r.pred)], color: PALETTE[1], dashed: true, noDots: true,
        band: [...hist.map(() => null), ...pron.map(r => [r.li, r.ls])] }] });
  lineChart(rv, { labels: d.prueba.map(r => r.fecha), xFormat: fmt.fecha, yFormat: fmt.mxn, height: 280,
    series: [{ name: 'Real', values: d.prueba.map(r => r.real), color: '#0b1f4b', noDots: true }, { name: 'Estimado', values: d.prueba.map(r => r.pred), color: PALETTE[1], noDots: true }] });
  scatter(sc, { points: d.dispersion.map(r => ({ x: r.real, y: r.pred })), diagonal: true, xFormat: fmt.mxn, yFormat: fmt.mxn, xName: 'Real', yName: 'Estimado', xLabel: 'Ingreso real', height: 280, r: 2.6 });
  dataTable(cmp, { search: false, rows: d.metricas.filter(r => r.conjunto !== 'entrenamiento'), initialSort: { key: 'conjunto', dir: -1 }, pageSize: 20, columns: [
    { key: 'modelo', label: 'Modelo', render: r => `${esc(r.modelo)} ${r.seleccionado ? '<span class="tag good">Seleccionado</span>' : ''}` },
    { key: 'conjunto', label: 'Conjunto', format: v => v === 'validacion' ? 'Validación' : 'Prueba' },
    { key: 'mae', label: 'MAE', num: true, format: v => fmt.mxn(v, true) }, { key: 'rmse', label: 'RMSE', num: true, format: v => fmt.mxn(v, true) },
    { key: 'mape', label: 'MAPE', num: true, format: fmt.pct }, { key: 'r2', label: 'R²', num: true, format: v => v?.toFixed(3) }] });
  const im = d.importancia.filter(r => r.importancia > 0).slice(0, 14);
  barChart(imp, { horizontal: true, labels: im.map(r => r.variable), labelWidth: 190, yFormat: v => fmt.mxn(v), series: [{ name: 'Aumento del MAE', values: im.map(r => r.importancia), color: PALETTE[6] }],
    extraTip: i => `<div>${esc(im[i].descripcion)}</div>` });
  dataTable(pc, { rows: d.por_complejo, pageSize: 20, initialSort: { key: 'var_anio_anterior', dir: 1 }, columns: [
    { key: 'nombre', label: 'Complejo' }, { key: 'ciudad', label: 'Ciudad' },
    { key: 'pred7', label: 'Pronóstico 7 días', num: true, format: fmt.mxn }, { key: 'pred30', label: 'Pronóstico 30 días', num: true, format: fmt.mxn },
    { key: 'asis30', label: 'Asistencia 30 d', num: true, format: fmt.int },
    { key: 'var_anio_anterior', label: 'vs. mismo periodo año ant.', num: true, render: r => r.var_anio_anterior == null ? '<span class="muted">sin historial</span>' : `<span class="tag ${r.var_anio_anterior < -10 ? 'bad' : r.var_anio_anterior < 0 ? 'warn' : 'good'}">${fmt.var(r.var_anio_anterior)}</span>` },
    { key: 'var_ultimos30', label: 'vs. últimos 30 días', num: true, format: v => fmt.var(v) },
    { key: 'brecha_prueba', label: 'Brecha real vs. modelo', num: true, render: r => r.brecha_prueba == null ? '—' : `<span class="tag ${r.brecha_prueba < -10 ? 'bad' : r.brecha_prueba > 10 ? 'good' : ''}">${fmt.var(r.brecha_prueba)}</span>` }] });
  tr.innerHTML = `<p class="muted" style="margin-top:0">El entrenamiento lee el mart diario del Data Warehouse, evalúa los modelos con la división cronológica y guarda métricas, predicciones de prueba y pronóstico en las tablas <code>ml_*</code>. Tarda alrededor de 40 segundos.</p>
    <button class="btn primary" type="button" id="m-train">Reentrenar con los datos actuales</button><div class="task-box" id="m-task" style="margin-top:10px;display:none"></div>`;
  tr.querySelector('#m-train').addEventListener('click', async e => {
    e.target.disabled = true;
    const box = tr.querySelector('#m-task'); box.style.display = 'block';
    try {
      await api('/api/modelo/entrenar', { method: 'POST' });
      const t = await pollTask(t => { box.innerHTML = `<b>${esc(t.tipo)}</b> · ${esc(t.mensaje)}<div class="progress"><i style="width:${t.pct}%"></i></div>`; });
      if (t.error) box.innerHTML = `<span class="tag bad">Error</span> ${esc(t.error)}`;
      else { window.dispatchEvent(new Event('cine:meta-refresh')); root.innerHTML = ''; viewModelo(root, stale); }
    } catch (err) { box.innerHTML = `<span class="tag bad">Error</span> ${esc(err.message)}`; e.target.disabled = false; }
  });
}

// ================================================================ INTELIGENCIA DE NEGOCIOS
export async function viewInteligencia(root, stale) {
  const ph = h('<div></div>'); root.appendChild(ph); loading(ph, 'Analizando el Data Warehouse y los resultados del modelo…');
  const d = await api('/api/inteligencia');
  if (stale()) return;
  ph.remove();
  root.appendChild(h(`<div class="intro">Conclusiones para la dirección, generadas a partir del Data Warehouse (año completo más reciente: <b>${d.anio}</b>, comparado con ${d.anio_anterior}) y del modelo predictivo. Cada recomendación muestra el indicador que la respalda. Los impactos son <b>estimaciones</b>, no resultados medidos.</div>`));
  const g1 = grid(root, 'g-wide');
  const hz = add(g1, 'Principales hallazgos', '');
  hz.innerHTML = d.hallazgos.map(x => `<div class="finding ${x.tono}" style="margin-bottom:10px"><h4>${esc(x.titulo)}</h4><p>${esc(x.texto)}</p></div>`).join('');
  const tn = add(g1, 'Tendencia de ingresos', 'Ingreso total por año');
  barChart(tn, { labels: d.tendencia.map(r => String(r.anio)), yFormat: fmt.mxn, series: [{ name: 'Ingreso total', values: d.tendencia.map(r => r.total), color: '#0b1f4b' }],
    extraTip: i => `<div>Asistentes: <b>${fmt.int(d.tendencia[i].asistentes)}</b></div><div>Ocupación: <b>${fmt.pct(d.tendencia[i].ocupacion)}</b></div>` });
  const g2 = grid(root, 'g3');
  const cxTable = (el, rows) => dataTable(el, { search: false, rows, columns: [
    { key: 'nombre', label: 'Complejo', render: r => `${esc(r.nombre.replace('Complejo ', ''))}<br><span class="muted">${esc(r.ciudad)}</span>` },
    { key: 'ingreso', label: `Ingreso ${d.anio}`, num: true, format: fmt.mxn },
    { key: 'variacion', label: 'Var.', num: true, render: r => `<span class="tag ${r.variacion >= 0 ? 'good' : 'bad'}">${fmt.var(r.variacion)}</span>` }] });
  cxTable(add(g2, 'Complejos con mejor rendimiento', 'Mayor ingreso total'), d.mejores_complejos);
  cxTable(add(g2, 'Complejos con menor rendimiento', 'Menor crecimiento anual (complejos comparables)'), d.menores_complejos);
  dataTable(add(g2, 'Películas con mayor impacto comercial', `Top 5 de ${d.anio}`), { search: false, rows: d.peliculas_top, columns: [
    { key: 'titulo', label: 'Película', render: r => `${esc(r.titulo)}<br><span class="muted">${esc(r.genero)} · ${esc(r.tipo_lanzamiento)}</span>` },
    { key: 'ingreso', label: 'Taquilla', num: true, format: fmt.mxn }, { key: 'asis', label: 'Asistentes', num: true, format: fmt.compact }] });
  const g3 = grid(root, 'g3');
  add(g3, 'Comportamiento de la asistencia', '').innerHTML = `<ul class="list">${d.comportamiento.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
  add(g3, 'Cambios en los hábitos de consumo', '').innerHTML = `<ul class="list">${d.habitos.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
  add(g3, 'Resultados del modelo predictivo', '').innerHTML = d.modelo ? `<ul class="list">
      <li>Algoritmo: <b>${esc(d.modelo.algoritmo)}</b>.</li>
      <li>Explica <b>${(100 * d.modelo.r2).toFixed(0)} %</b> de la variación diaria (R² en prueba).</li>
      <li>Error porcentual: <b>${fmt.pct(d.modelo.mape)}</b> diario y <b>${fmt.pct(d.modelo.mape_semanal)}</b> semanal, contra ${fmt.pct(d.modelo.mape_base)} de la línea base.</li>
      <li>${d.alertas.length ? `<b>${d.alertas.length}</b> complejo(s) con posible caída en los próximos 30 días.` : 'Sin alertas de caída para los próximos 30 días.'}</li></ul>` : '<p class="muted">Modelo no entrenado.</p>';
  const g4 = grid(root, 'g2');
  add(g4, 'Oportunidades de mejora', '').innerHTML = `<ul class="list">${d.oportunidades.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
  add(g4, 'Riesgos identificados', '').innerHTML = `<ul class="list">${d.riesgos.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
  const rc = add(root, 'Recomendaciones estratégicas', 'Hallazgo → indicador → interpretación → acción → impacto esperado');
  rc.innerHTML = `<div class="grid g2">${d.recomendaciones.map((r, i) => `<article class="reco">
      <div class="reco-head"><span class="tag ${r.prioridad === 'Alta' ? 'bad' : 'warn'}">Prioridad ${esc(r.prioridad)}</span><span class="tag blue">${esc(r.area)}</span><h4>Recomendación ${i + 1}</h4></div>
      <dl><dt>1. Hallazgo</dt><dd>${esc(r.hallazgo)}</dd><dt>2. Indicador</dt><dd>${esc(r.indicador)}</dd><dt>3. Interpretación</dt><dd>${esc(r.interpretacion)}</dd>
      <dt>4. Acción sugerida</dt><dd>${esc(r.accion)}</dd><dt>5. Impacto esperado</dt><dd>${esc(r.impacto)} <span class="tag warn">${esc(r.tipo_impacto)}</span></dd></dl></article>`).join('')}</div>`;
  dataTable(add(root, 'Próximos estrenos con mayor potencial', 'Calendario de estrenos posterior al último dato · índice basado en el desempeño histórico por tipo de lanzamiento (60 %) y género (40 %)'),
    { search: false, rows: d.proximos_estrenos, columns: [
      { key: 'titulo', label: 'Película' }, { key: 'genero', label: 'Género' }, { key: 'tipo_lanzamiento', label: 'Lanzamiento' },
      { key: 'distribuidora', label: 'Distribuidora' }, { key: 'fecha_estreno', label: 'Estreno', format: v => fmt.fecha(v, true) },
      { key: 'indice_potencial', label: 'Índice de potencial', num: true, render: r => `<span class="bar-cell">${r.indice_potencial}<i style="width:${r.indice_potencial * 0.7}px"></i></span>` }] });
}
