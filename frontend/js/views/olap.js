// Análisis multidimensional (OLAP): roll-up, drill-down, slice, dice y pivot sobre el modelo en estrella.
import { api, byFormat, card, esc, fmt, h, loading, errorBox } from '../core.js';
import { barChart, SEQ } from '../charts.js';

const S = { medida: 'ingreso_taquilla', filas: 'anio', columnas: '', filtros: {}, ruta: [], op: 'Consulta inicial' };
let META = null;

const PRESETS = [
  { op: 'Roll-up', txt: 'Ingresos de taquilla por año', s: { medida: 'ingreso_taquilla', filas: 'anio', columnas: '', filtros: {}, ruta: [] } },
  { op: 'Drill-down', txt: '2025 → meses', s: { medida: 'ingreso_taquilla', filas: 'mes', columnas: '', filtros: { anio: ['2025'] }, ruta: [{ dim: 'anio', valor: '2025' }] } },
  { op: 'Slice', txt: 'Sólo Monterrey, ocupación por turno', s: { medida: 'ocupacion', filas: 'turno', columnas: 'dia_semana', filtros: { ciudad: ['Monterrey'] }, ruta: [] } },
  { op: 'Dice', txt: 'Terror y Suspenso · CDMX · 2025', s: { medida: 'asistentes', filas: 'pelicula', columnas: '', filtros: { genero: ['Terror', 'Suspenso'], ciudad: ['Ciudad de México'], anio: ['2025'] }, ruta: [] } },
  { op: 'Pivot', txt: 'Canal × año (boletos)', s: { medida: 'boletos', filas: 'canal', columnas: 'anio', filtros: {}, ruta: [] } },
  { op: 'Dice', txt: 'Margen por categoría · app · 2024-2025', s: { medida: 'margen_pct', filas: 'categoria', columnas: 'anio', filtros: { canal: ['Aplicación móvil'], anio: ['2024', '2025'] }, ruta: [] } },
];

function hierarchyOf(dim) {
  for (const [name, levels] of Object.entries(META.jerarquias)) { const i = levels.indexOf(dim); if (i >= 0) return { name, levels, i }; }
  return null;
}
const dimLabel = k => META.dimensiones.find(d => d.clave === k)?.etiqueta || k;
const medida = () => META.medidas.find(m => m.clave === S.medida);

export async function viewOlap(root) {
  root.appendChild(h(`<div class="intro"><b>Consultas OLAP (ROLAP) sobre el modelo en estrella.</b> Elige una medida (hecho) y las dimensiones de filas y columnas.
    <b>Drill-down</b>: haz clic en un valor de la primera columna para bajar un nivel en su jerarquía (Año → Trimestre → Mes → Día; Región → Ciudad → Complejo; Género → Película; Categoría → Producto).
    <b>Roll-up</b>: sube de nivel. <b>Slice</b>: un filtro. <b>Dice</b>: varios filtros combinados. <b>Pivot</b>: intercambia filas y columnas.
    El motor elige automáticamente la tabla más pequeña que puede responder (data mart o tabla de hechos).</div>`));
  const ctlCard = card('Constructor de consultas', 'Los resultados se actualizan al cambiar cualquier control');
  root.appendChild(ctlCard);
  const body = ctlCard.querySelector('.card-body');
  loading(body);
  META = META || await api('/api/olap/meta');
  body.innerHTML = `
    <div class="olap-ctl">
      <label class="ctl">Medida<select id="o-medida"></select></label>
      <label class="ctl">Filas<select id="o-filas"></select></label>
      <label class="ctl">Columnas<select id="o-columnas"></select></label>
      <label class="ctl">Orden de filas<select id="o-orden"><option value="valor">Natural / por valor</option><option value="etiqueta">Alfabético</option></select></label>
      <div class="actions"><button class="btn" id="o-pivot" type="button" title="Intercambiar filas y columnas">⇄ Pivot</button><button class="btn" id="o-rollup" type="button">↑ Roll-up</button><button class="btn" id="o-reset" type="button">Reiniciar</button></div>
    </div>
    <div class="op-row"><b style="font-size:12.5px">Filtros (slice / dice):</b><div class="chips" id="o-chips"></div></div>
    <div class="filter-add" style="margin-top:8px">
      <label class="ctl">Dimensión<select id="o-fdim"></select></label>
      <label class="ctl">Valor<select id="o-fval"><option value="">—</option></select></label>
      <button class="btn" id="o-fadd" type="button">+ Agregar filtro</button>
    </div>
    <div class="op-row"><b style="font-size:12.5px">Ejemplos:</b>${PRESETS.map((p, i) => `<button class="btn" data-preset="${i}" type="button"><span class="op-pill">${p.op}</span> ${esc(p.txt)}</button>`).join('')}</div>`;
  const res = card('Resultado', '');
  root.appendChild(res);
  const chartCard = card('Visualización', 'Total por fila');
  root.appendChild(chartCard);
  const $ = id => body.querySelector('#' + id);

  function fillMedidas() {
    const groups = {};
    META.medidas.forEach(m => (groups[m.hecho_nombre] ||= []).push(m));
    $('o-medida').innerHTML = Object.entries(groups).map(([g, ms]) => `<optgroup label="${esc(g)}">${ms.map(m => `<option value="${m.clave}">${esc(m.etiqueta)}</option>`).join('')}</optgroup>`).join('');
    $('o-medida').value = S.medida;
  }
  function dimOptions(allowEmpty, value) {
    const ok = new Set(medida().dimensiones);
    const groups = {};
    META.dimensiones.filter(d => ok.has(d.clave)).forEach(d => (groups[d.grupo] ||= []).push(d));
    return (allowEmpty ? '<option value="">(ninguna)</option>' : '') + Object.entries(groups).map(([g, ds]) =>
      `<optgroup label="${esc(g)}">${ds.map(d => `<option value="${d.clave}" ${d.clave === value ? 'selected' : ''}>${esc(d.etiqueta)}</option>`).join('')}</optgroup>`).join('');
  }
  function fillDims() {
    const ok = new Set(medida().dimensiones);
    if (!ok.has(S.filas)) S.filas = 'anio';
    if (S.columnas && !ok.has(S.columnas)) S.columnas = '';
    Object.keys(S.filtros).forEach(k => { if (!ok.has(k)) delete S.filtros[k]; });
    $('o-filas').innerHTML = dimOptions(false, S.filas);
    $('o-columnas').innerHTML = dimOptions(true, S.columnas);
    const fd = $('o-fdim').value;
    $('o-fdim').innerHTML = dimOptions(false, ok.has(fd) ? fd : 'ciudad');
    loadValues();
  }
  async function loadValues() {
    const dim = $('o-fdim').value;
    $('o-fval').innerHTML = '<option>Cargando…</option>';
    const vals = await api('/api/olap/valores/' + dim);
    $('o-fval').innerHTML = vals.map(v => `<option>${esc(v)}</option>`).join('');
  }
  function chips() {
    const entries = Object.entries(S.filtros).flatMap(([k, vs]) => vs.map(v => [k, v]));
    $('o-chips').innerHTML = entries.length ? entries.map(([k, v]) => `<span class="chip">${esc(dimLabel(k))}: <b>${esc(v)}</b><button type="button" data-k="${k}" data-v="${esc(v)}" aria-label="Quitar filtro">×</button></span>`).join('')
      : '<span class="muted" style="font-size:12.5px">Sin filtros: se analiza todo el cubo.</span>';
    $('o-chips').querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
      S.filtros[b.dataset.k] = S.filtros[b.dataset.k].filter(x => x !== b.dataset.v);
      if (!S.filtros[b.dataset.k].length) delete S.filtros[b.dataset.k];
      S.ruta = S.ruta.filter(r => S.filtros[r.dim]?.includes(r.valor));
      S.op = Object.keys(S.filtros).length > 1 ? 'Dice' : Object.keys(S.filtros).length ? 'Slice' : 'Consulta sin filtros';
      run();
    }));
  }

  async function run() {
    chips();
    const rb = res.querySelector('.card-body');
    loading(rb, 'Ejecutando consulta multidimensional…');
    try {
      const r = await api('/api/olap', { method: 'POST', body: JSON.stringify({ medida: S.medida, filas: S.filas, columnas: S.columnas || null, filtros: S.filtros, orden: $('o-orden').value }) });
      renderResult(r);
    } catch (e) { errorBox(rb, e); chartCard.querySelector('.card-body').innerHTML = ''; }
  }

  function renderResult(r) {
    const f = byFormat(r.medida.formato);
    const rb = res.querySelector('.card-body');
    res.querySelector('h3').textContent = `${r.medida.etiqueta} por ${r.filas.etiqueta}${r.columnas ? ' × ' + r.columnas.etiqueta : ''}`;
    res.querySelector('.card-head p')?.remove();
    res.querySelector('.card-head div').insertAdjacentHTML('beforeend', `<p><span class="op-pill">${esc(S.op)}</span> &nbsp;Hecho: <b>${esc(r.hecho.nombre)}</b> · Resuelto desde <b>${esc(r.fuente.tabla)}</b> (${esc(r.fuente.tipo)}) · ${r.ms} ms</p>`);
    const hi = hierarchyOf(S.filas);
    const canDrill = hi && hi.i < hi.levels.length - 1;
    const crumbs = S.ruta.length ? `<div class="breadcrumb">Ruta de drill-down: <button type="button" data-crumb="-1">Inicio</button>${S.ruta.map((c, i) => `› <button type="button" data-crumb="${i}">${esc(dimLabel(c.dim))}: ${esc(c.valor)}</button>`).join('')}</div>` : '';
    const cells = r.datos.flatMap(d => r.columnas ? r.encabezados.map(c => d.celdas[c]) : []).filter(v => v != null);
    const lo = Math.min(...cells), hiV = Math.max(...cells);
    const shade = v => { if (v == null || !r.columnas) return ''; const k = Math.min(6, Math.floor((v - lo) / ((hiV - lo) || 1) * 7)); return `style="background:${SEQ[k]};${k >= 4 ? 'color:#fff' : ''}"`; };
    const totalCol = r.columnas ? `<th class="num">Total</th>` : '';
    rb.innerHTML = `${crumbs}
      <div class="dt-scroll" style="margin-top:8px;max-height:520px"><table class="pivot">
        <thead><tr><th>${esc(r.filas.etiqueta)}${canDrill ? ' <span class="muted">(clic = drill-down)</span>' : ''}</th>${r.columnas ? r.encabezados.map(c => `<th class="num">${esc(c)}</th>`).join('') : `<th class="num">${esc(r.medida.etiqueta)}</th>`}${totalCol}${r.medida.aditiva ? '<th class="num">% del total</th>' : ''}</tr></thead>
        <tbody>${r.datos.map(d => `<tr><td class="${canDrill ? 'drill' : ''}" data-v="${esc(d.clave)}">${esc(d.clave ?? '(vacío)')}</td>${r.columnas ? r.encabezados.map(c => `<td class="num" ${shade(d.celdas[c])}>${f(d.celdas[c])}</td>`).join('') + `<td class="num tot">${f(d.total)}</td>` : `<td class="num">${f(d.total)}</td>`}${r.medida.aditiva ? `<td class="num">${fmt.pct(100 * d.total / r.total)}</td>` : ''}</tr>`).join('')}</tbody>
        <tfoot><tr><td>Total</td>${r.columnas ? r.totales_columna.map(v => `<td class="num">${f(v)}</td>`).join('') : ''}<td class="num">${f(r.total)}</td>${r.medida.aditiva ? '<td class="num">100 %</td>' : ''}</tr></tfoot>
      </table></div>
      ${r.truncado ? '<p class="muted">Se muestran las primeras 400 filas.</p>' : ''}${r.columnas_omitidas ? `<p class="muted">Se muestran 15 columnas; ${r.columnas_omitidas} se omiten (aplica un filtro para verlas).</p>` : ''}
      ${!r.medida.aditiva ? '<p class="muted" style="font-size:12px">Medida no aditiva: los totales se recalculan con los componentes (no se suman los porcentajes ni los promedios).</p>' : ''}
      <div class="actions" style="margin-top:10px"><button class="btn" type="button" id="o-csv">Exportar CSV</button></div>
      <details style="margin-top:8px"><summary>Ver SQL generado</summary><pre class="sqlbox">${esc(r.sql)}</pre></details>`;
    rb.querySelectorAll('td.drill').forEach(td => td.addEventListener('click', () => {
      const v = td.dataset.v;
      S.filtros[S.filas] = [v];
      S.ruta.push({ dim: S.filas, valor: v, prev: S.filas });
      S.filas = hi.levels[hi.i + 1];
      S.op = 'Drill-down';
      $('o-filas').value = S.filas;
      run();
    }));
    rb.querySelectorAll('[data-crumb]').forEach(b => b.addEventListener('click', () => {
      const i = +b.dataset.crumb;
      const removed = S.ruta.slice(i + 1);
      removed.forEach(c => delete S.filtros[c.dim]);
      S.filas = removed.length ? removed[0].prev : S.filas;
      S.ruta = S.ruta.slice(0, i + 1);
      S.op = 'Roll-up';
      fillDims(); run();
    }));
    rb.querySelector('#o-csv').addEventListener('click', () => {
      const head = [r.filas.etiqueta, ...(r.columnas ? r.encabezados : [r.medida.etiqueta]), ...(r.columnas ? ['Total'] : [])];
      const lines = [head, ...r.datos.map(d => [d.clave, ...(r.columnas ? r.encabezados.map(c => d.celdas[c] ?? '') : [d.total]), ...(r.columnas ? [d.total] : [])])];
      const csv = lines.map(l => l.map(x => `"${String(x ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
      const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv' })); a.download = 'consulta_olap.csv'; a.click();
    });
    const cb = chartCard.querySelector('.card-body');
    const data = r.datos.slice(0, 30);
    const timeLike = ['anio', 'trimestre', 'mes', 'fecha', 'dia_semana', 'hora', 'turno'].includes(r.filas.clave);
    barChart(cb, { horizontal: !timeLike, labels: data.map(d => d.clave), yFormat: f, valueLabels: !timeLike, rotate: timeLike && data.length > 12,
      series: [{ name: r.medida.etiqueta, values: data.map(d => d.total) }],
      onClick: canDrill ? (lb) => { S.filtros[S.filas] = [lb]; S.ruta.push({ dim: S.filas, valor: lb, prev: S.filas }); S.filas = hi.levels[hi.i + 1]; S.op = 'Drill-down'; $('o-filas').value = S.filas; run(); } : null });
    chartCard.querySelector('.card-head p').textContent = data.length < r.datos.length ? `Total por fila (primeras ${data.length})` : 'Total por fila' + (canDrill ? ' · clic en una barra para hacer drill-down' : '');
  }

  fillMedidas(); fillDims();
  $('o-medida').addEventListener('change', e => { S.medida = e.target.value; S.op = 'Cambio de medida'; fillDims(); run(); });
  $('o-filas').addEventListener('change', e => { S.filas = e.target.value; S.ruta = []; S.op = 'Cambio de dimensión'; run(); });
  $('o-columnas').addEventListener('change', e => { S.columnas = e.target.value; S.op = S.columnas ? 'Tabla cruzada' : 'Cambio de dimensión'; run(); });
  $('o-orden').addEventListener('change', run);
  $('o-fdim').addEventListener('change', loadValues);
  $('o-fadd').addEventListener('click', () => {
    const k = $('o-fdim').value, v = $('o-fval').value;
    if (!v) return;
    S.filtros[k] = [...new Set([...(S.filtros[k] || []), v])];
    S.op = Object.keys(S.filtros).length > 1 || S.filtros[k].length > 1 ? 'Dice' : 'Slice';
    run();
  });
  $('o-pivot').addEventListener('click', () => {
    if (!S.columnas) { S.columnas = S.filas === 'anio' ? 'ciudad' : 'anio'; }
    [S.filas, S.columnas] = [S.columnas, S.filas];
    S.ruta = []; S.op = 'Pivot'; fillDims(); run();
  });
  $('o-rollup').addEventListener('click', () => {
    const hi = hierarchyOf(S.filas);
    if (S.ruta.length) {
      const last = S.ruta.pop(); delete S.filtros[last.dim]; S.filas = last.prev;
    } else if (hi && hi.i > 0) S.filas = hi.levels[hi.i - 1];
    else return;
    S.op = 'Roll-up'; fillDims(); run();
  });
  $('o-reset').addEventListener('click', () => { Object.assign(S, { medida: 'ingreso_taquilla', filas: 'anio', columnas: '', filtros: {}, ruta: [], op: 'Consulta inicial' }); fillMedidas(); fillDims(); run(); });
  body.querySelectorAll('[data-preset]').forEach(b => b.addEventListener('click', () => {
    const p = PRESETS[+b.dataset.preset];
    Object.assign(S, JSON.parse(JSON.stringify(p.s)), { op: p.op });
    S.ruta = S.ruta.map(r => ({ ...r, prev: r.dim }));
    fillMedidas(); fillDims(); run();
  }));
  run();
}
