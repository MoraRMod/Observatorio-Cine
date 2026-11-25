// Vistas de análisis: resumen ejecutivo, ventas, taquilla, dulcería, complejos y películas.
import { api, card, dataTable, esc, fmt, h, kpiCard, loading, periodLabel, qs, state } from '../core.js';
import { barChart, heatmap, lineChart, PALETTE, scatter } from '../charts.js';

const C = { taq: PALETTE[0], dul: PALETTE[1], total: '#0b1f4b' };

function grid(root, cls) { const g = h(`<div class="grid ${cls}"></div>`); root.appendChild(g); return g; }
function add(parent, title, sub, cls, actions) { const c = card(title, sub, cls, actions); parent.appendChild(c); return c.querySelector('.card-body'); }
function chip(root, extra = '') { root.appendChild(h(`<span class="period-chip">${esc(periodLabel())}${extra}</span>`)); }
function pendingKpis(root) { const k = h('<div class="kpis"></div>'); root.appendChild(k); loading(k); return k; }

function kpiBlock(el, k) {
  el.innerHTML = [
    kpiCard('Ingresos totales', k.ingresos_totales, fmt.mxn, { hero: true }),
    kpiCard('Ingresos por taquilla', k.ingresos_taquilla, fmt.mxn),
    kpiCard('Ingresos por dulcería', k.ingresos_dulceria, fmt.mxn),
    kpiCard('Boletos vendidos', k.boletos, fmt.compact),
    kpiCard('Asistencia total', k.asistencia, fmt.compact),
    kpiCard('Ocupación promedio', k.ocupacion, fmt.pct),
    kpiCard('Ticket promedio (boleto)', k.ticket_promedio, fmt.mxn2),
    kpiCard('Ingreso por asistente', k.ingreso_por_asistente, fmt.mxn2),
    kpiCard('Margen bruto de dulcería', k.margen_dulceria, fmt.pct),
    kpiCard('Margen bruto dulcería (MXN)', k.margen_dulceria_mxn, fmt.mxn),
  ].join('');
}

function inPeriod(am) {
  const f = state.filtros;
  if (!f.anio) return true;
  const [y, m] = am.split('-').map(Number);
  if (y !== +f.anio) return false;
  if (f.mes) return m === +f.mes;
  if (f.trimestre) return Math.ceil(m / 3) === +f.trimestre;
  return true;
}

// ================================================================ RESUMEN
export async function viewResumen(root, stale) {
  chip(root, ' · KPIs comparados contra el periodo seleccionado en «Comparar con»');
  const kpis = pendingKpis(root);
  const g1 = grid(root, 'g-wide');
  const evo = add(g1, 'Evolución de ingresos mensuales', 'Histórico completo · respeta los filtros de ciudad y complejo');
  const yoy = add(g1, 'Comparación de ingresos por año', 'Ingreso total por mes de cada año');
  const g2 = grid(root, 'g2');
  const cx = add(g2, 'Complejos con mejor rendimiento', 'Ingreso total del periodo');
  const pe = add(g2, 'Películas con mayores ingresos', 'Taquilla del periodo');
  [evo, yoy, cx, pe].forEach(e => loading(e));
  const d = await api('/api/resumen' + qs());
  if (stale()) return;
  kpiBlock(kpis, d.kpis.kpis);
  const ms = d.mensual;
  lineChart(evo, {
    labels: ms.map(r => r.anio_mes), xFormat: fmt.mes, yFormat: fmt.mxn, height: 270,
    series: [{ name: 'Ingreso total', values: ms.map(r => r.total), color: C.total },
      { name: 'Taquilla', values: ms.map(r => r.taquilla), color: C.taq }, { name: 'Dulcería', values: ms.map(r => r.dulceria), color: C.dul }],
  });
  const years = [...new Set(d.anual.map(r => r.anio))];
  const MES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
  lineChart(yoy, {
    labels: MES, yFormat: fmt.mxn, height: 270,
    series: years.map((y, i) => ({ name: String(y), values: MES.map((_, m) => d.anual.find(r => r.anio === y && r.mes === m + 1)?.total ?? null), color: PALETTE[i % 8] })),
  });
  barChart(cx, { horizontal: true, labels: d.complejos.map(r => r.nombre.replace('Complejo ', '')), valueLabels: true, yFormat: fmt.mxn,
    series: [{ name: 'Ingreso total', values: d.complejos.map(r => r.total) }],
    extraTip: i => `<div>Variación: <b>${fmt.var(d.complejos[i].variacion)}</b></div><div>Ocupación: <b>${fmt.pct(d.complejos[i].ocupacion)}</b></div>` });
  barChart(pe, { horizontal: true, labels: d.peliculas.map(r => r.titulo), valueLabels: true, yFormat: fmt.mxn,
    series: [{ name: 'Taquilla', values: d.peliculas.map(r => r.ingreso), color: PALETTE[0] }],
    extraTip: i => `<div>${esc(d.peliculas[i].genero)} · ${esc(d.peliculas[i].tipo_lanzamiento)}</div><div>Asistentes: <b>${fmt.int(d.peliculas[i].asistentes)}</b></div>` });
}

// ================================================================ VENTAS
export async function viewVentas(root, stale) {
  chip(root);
  const g1 = grid(root, 'g2');
  const mix = add(g1, 'Ventas por taquilla frente a dulcería', 'Ingreso mensual por línea de negocio (histórico)');
  const tk = add(g1, 'Evolución del ticket promedio', 'Precio promedio por boleto y gasto en dulcería por asistente');
  const g2 = grid(root, 'g2');
  const ci = add(g2, 'Ingresos por ciudad', 'Ingreso total del periodo');
  const dw = add(g2, 'Entre semana vs. fin de semana', 'Ingreso promedio diario de la cadena por día de la semana');
  const tbl = add(root, 'Comparativo lunes-jueves vs. viernes-domingo', '');
  [mix, tk, ci, dw, tbl].forEach(e => loading(e));
  const d = await api('/api/ventas' + qs());
  if (stale()) return;
  const ms = d.mensual;
  barChart(mix, { labels: ms.map(r => r.anio_mes), labelFormat: fmt.mes, stacked: true, yFormat: fmt.mxn, height: 270,
    series: [{ name: 'Taquilla', values: ms.map(r => r.taquilla), color: C.taq }, { name: 'Dulcería', values: ms.map(r => r.dulceria), color: C.dul }],
    extraTip: i => `<div class="muted">Dulcería = ${fmt.pct(100 * ms[i].dulceria / ms[i].total)} del total</div>` });
  lineChart(tk, { labels: ms.map(r => r.anio_mes), xFormat: fmt.mes, yFormat: fmt.mxn2, zero: false, height: 270,
    series: [{ name: 'Ticket promedio por boleto', values: ms.map(r => r.ticket_promedio), color: C.taq },
      { name: 'Dulcería por asistente', values: ms.map(r => r.gasto_dulceria_asistente), color: C.dul }] });
  barChart(ci, { horizontal: true, labels: d.ciudades.map(r => r.ciudad), stacked: true, yFormat: fmt.mxn,
    series: [{ name: 'Taquilla', values: d.ciudades.map(r => r.taquilla), color: C.taq }, { name: 'Dulcería', values: d.ciudades.map(r => r.dulceria), color: C.dul }],
    extraTip: i => `<div>Complejos: <b>${d.ciudades[i].complejos}</b> · Ocupación: <b>${fmt.pct(d.ciudades[i].ocupacion)}</b></div>` });
  const pd = d.semana.por_dia;
  barChart(dw, { labels: pd.map(r => r.nombre_dia), yFormat: fmt.mxn, stacked: true,
    series: [{ name: 'Taquilla', values: pd.map(r => r.taquilla_dia), color: C.taq }, { name: 'Dulcería', values: pd.map(r => r.dulceria_dia), color: C.dul }],
    extraTip: i => `<div>Ocupación: <b>${fmt.pct(pd[i].ocupacion)}</b></div><div>Asistentes/día: <b>${fmt.int(pd[i].asistentes_dia)}</b></div>` });
  dataTable(tbl, { search: false, rows: d.semana.por_tipo, columns: [
    { key: 'tipo', label: 'Tipo de día' }, { key: 'dias', label: 'Días', num: true, format: fmt.int },
    { key: 'total', label: 'Ingreso total', num: true, format: fmt.mxn }, { key: 'ingreso_dia', label: 'Ingreso promedio diario', num: true, format: fmt.mxn },
    { key: 'ocupacion', label: 'Ocupación', num: true, format: fmt.pct }, { key: 'gasto_dulceria', label: 'Dulcería por asistente', num: true, format: fmt.mxn2 }] });
}

// ================================================================ TAQUILLA
export async function viewTaquilla(root, stale) {
  chip(root);
  const g1 = grid(root, 'g2');
  const pi = add(g1, 'Películas con mayores ingresos', 'Top 10 por taquilla');
  const pa = add(g1, 'Películas con mayor asistencia', 'Top 10 por asistentes');
  const hm = add(root, 'Ocupación por horario', 'Porcentaje de butacas vendidas según día de la semana y hora de inicio de la función');
  const g2 = grid(root, 'g2');
  const ge = add(g2, 'Ventas por género cinematográfico', 'Taquilla del periodo; el tooltip muestra ocupación y asistentes por función');
  const de = add(g2, 'Ciclo de vida de una película', 'Asistentes promedio por función según la semana en cartelera');
  const g3 = grid(root, 'g2');
  const ch = add(g3, 'Boletos por canal de venta', 'Participación mensual (histórico) · digitalización del consumo');
  const fo = add(g3, 'Formatos de sala', 'Ingreso, precio promedio y ocupación por formato');
  const pr = add(root, 'Promociones', 'Ocupación y asistencia por función con cada promoción');
  [pi, pa, hm, ge, de, ch, fo, pr].forEach(e => loading(e));
  const d = await api('/api/taquilla' + qs());
  if (stale()) return;
  const filmTip = arr => i => `<div>${esc(arr[i].genero)} · ${esc(arr[i].clasificacion)} · ${esc(arr[i].tipo_lanzamiento)}</div><div>Estreno: ${fmt.fecha(arr[i].fecha_estreno, true)}</div><div>Ocupación: <b>${fmt.pct(arr[i].ocupacion)}</b></div>`;
  barChart(pi, { horizontal: true, valueLabels: true, labels: d.peliculas_ingreso.map(r => r.titulo), yFormat: fmt.mxn,
    series: [{ name: 'Taquilla', values: d.peliculas_ingreso.map(r => r.ingreso) }], extraTip: filmTip(d.peliculas_ingreso) });
  barChart(pa, { horizontal: true, valueLabels: true, labels: d.peliculas_asistencia.map(r => r.titulo), yFormat: fmt.compact,
    series: [{ name: 'Asistentes', values: d.peliculas_asistencia.map(r => r.asistentes), color: PALETTE[2] }], extraTip: filmTip(d.peliculas_asistencia) });
  const days = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];
  const hours = [...new Set(d.horario.map(r => r.hora_num))].sort((a, b) => a - b);
  const cell = (di, hr) => d.horario.find(r => r.dia_semana === di + 1 && r.hora_num === hr);
  heatmap(hm, { rows: days, cols: hours.map(x => `${x}:00`), metric: 'Ocupación',
    values: days.map((_, i) => hours.map(hr => cell(i, hr)?.ocupacion ?? null)), format: fmt.pct, cellFormat: v => Math.round(v),
    extraTip: (i, j) => { const c = cell(i, hours[j]); return c ? `<div>Funciones: <b>${fmt.int(c.funciones)}</b></div><div>Asistentes/función: <b>${fmt.dec(c.asistentes_funcion)}</b></div>` : ''; } });
  barChart(ge, { labels: d.generos.map(r => r.genero), yFormat: fmt.mxn, rotate: true,
    series: [{ name: 'Taquilla', values: d.generos.map(r => r.ingreso) }],
    extraTip: i => `<div>Ocupación: <b>${fmt.pct(d.generos[i].ocupacion)}</b></div><div>Asistentes/función: <b>${fmt.dec(d.generos[i].asistentes_funcion)}</b></div><div>Películas: ${d.generos[i].peliculas}</div>` });
  const tipos = ['Blockbuster', 'Comercial', 'Independiente / Nacional', 'Arte y ensayo'].filter(t => d.semanas.some(r => r.tipo_lanzamiento === t));
  lineChart(de, { labels: Array.from({ length: 10 }, (_, i) => i + 1), xFormat: (v, full) => full ? `Semana ${v}` : `S${v}`, yFormat: fmt.int,
    series: tipos.map((t, i) => ({ name: t, values: Array.from({ length: 10 }, (_, k) => d.semanas.find(r => r.tipo_lanzamiento === t && r.semana === k + 1)?.asistentes_funcion ?? null), color: PALETTE[i] })) });
  const months = [...new Set(d.canales.map(r => r.anio_mes))];
  const chans = [...new Set(d.canales.map(r => r.canal))];
  const tot = months.map(m => d.canales.filter(r => r.anio_mes === m).reduce((a, r) => a + r.valor, 0));
  barChart(ch, { labels: months, labelFormat: fmt.mes, stacked: true, max: 100, yFormat: v => Math.round(v) + ' %', height: 270,
    series: ['Taquilla', 'Kiosko de autoservicio', 'Aplicación móvil', 'Página web'].filter(c => chans.includes(c)).map((c, i) => ({
      name: c, color: PALETTE[[0, 3, 1, 2][i]], format: v => fmt.pct(v),
      values: months.map((m, k) => 100 * (d.canales.find(r => r.anio_mes === m && r.canal === c)?.valor || 0) / tot[k]) })) });
  dataTable(fo, { search: false, rows: d.formatos, initialSort: { key: 'ingreso', dir: -1 }, columns: [
    { key: 'formato', label: 'Formato' }, { key: 'salas', label: 'Salas', num: true, format: fmt.int },
    { key: 'boletos', label: 'Boletos', num: true, format: fmt.int }, { key: 'ingreso', label: 'Ingreso', num: true, format: fmt.mxn },
    { key: 'precio_promedio', label: 'Precio prom.', num: true, format: fmt.mxn2 }, { key: 'ocupacion', label: 'Ocupación', num: true, format: fmt.pct }] });
  dataTable(pr, { search: false, rows: d.promociones, columns: [
    { key: 'promocion', label: 'Promoción' }, { key: 'tipo', label: 'Tipo' },
    { key: 'descuento_pct', label: 'Descuento', num: true, format: v => fmt.pct(100 * v) },
    { key: 'funciones', label: 'Funciones', num: true, format: fmt.int }, { key: 'boletos', label: 'Boletos', num: true, format: fmt.int },
    { key: 'ocupacion', label: 'Ocupación', num: true, format: fmt.pct }, { key: 'asistentes_funcion', label: 'Asistentes/función', num: true, format: fmt.dec }] });
}

// ================================================================ DULCERÍA
export async function viewDulceria(root, stale) {
  chip(root);
  const kpis = pendingKpis(root);
  const g1 = grid(root, 'g2');
  const ca = add(g1, 'Ingresos y margen por categoría', 'Ingreso del periodo; el tooltip muestra el margen bruto');
  const pr = add(g1, 'Productos más vendidos', 'Top 12 por unidades');
  const g2 = grid(root, 'g2');
  const mix = add(g2, 'Mezcla de categorías en el tiempo', 'Participación mensual en el ingreso de dulcería (histórico) · cambios en hábitos de consumo');
  const ch = add(g2, 'Canales de venta de dulcería', 'Participación mensual del ingreso (histórico)');
  const g3 = grid(root, 'g2');
  const gx = add(g3, 'Gasto en dulcería por asistente', 'Por complejo, en el periodo');
  const sc = add(g3, 'Asistencia vs. ingreso de dulcería', 'Cada punto es un complejo en un día (muestra sistemática)');
  const tb = add(root, 'Catálogo y desempeño de productos', '');
  [ca, pr, mix, ch, gx, sc, tb].forEach(e => loading(e));
  const d = await api('/api/dulceria' + qs());
  if (stale()) return;
  const k = d.kpis.kpis;
  const gasto = { actual: k.ingresos_dulceria.actual / k.asistencia.actual, anterior: k.ingresos_dulceria.anterior && k.ingresos_dulceria.anterior / k.asistencia.anterior, unidad_variacion: '%' };
  if (gasto.anterior) gasto.variacion = 100 * (gasto.actual / gasto.anterior - 1);
  kpis.innerHTML = [kpiCard('Ingresos por dulcería', k.ingresos_dulceria, fmt.mxn, { hero: true }), kpiCard('Margen bruto (MXN)', k.margen_dulceria_mxn, fmt.mxn),
    kpiCard('Margen bruto (%)', k.margen_dulceria, fmt.pct), kpiCard('Gasto por asistente', gasto, fmt.mxn2), kpiCard('Asistencia', k.asistencia, fmt.compact)].join('');
  barChart(ca, { horizontal: true, labels: d.categorias.map(r => r.categoria), stacked: true, yFormat: fmt.mxn, valueLabels: true,
    series: [{ name: 'Margen bruto', values: d.categorias.map(r => r.margen), color: PALETTE[2] }, { name: 'Costo', values: d.categorias.map(r => r.costo), color: '#b9b5a8' }],
    extraTip: i => `<div>Margen: <b>${fmt.pct(d.categorias[i].margen_pct)}</b></div><div>Unidades: <b>${fmt.int(d.categorias[i].unidades)}</b></div>` });
  const top = d.productos.slice(0, 12);
  barChart(pr, { horizontal: true, labels: top.map(r => r.nombre), valueLabels: true, yFormat: fmt.compact,
    series: [{ name: 'Unidades', values: top.map(r => r.unidades), color: PALETTE[1] }],
    extraTip: i => `<div>${esc(top[i].categoria)}</div><div>Ingreso: <b>${fmt.mxn(top[i].ingreso)}</b></div><div>Margen: <b>${fmt.pct(top[i].margen_pct)}</b></div>` });
  const months = [...new Set(d.categorias_mensual.map(r => r.anio_mes))];
  const cats = ['Palomitas', 'Bebidas', 'Combos', 'Alimentos', 'Dulces', 'VIP'].filter(c => d.categorias_mensual.some(r => r.categoria === c));
  const tm = months.map(m => d.categorias_mensual.filter(r => r.anio_mes === m).reduce((a, r) => a + r.ingreso, 0));
  barChart(mix, { labels: months, labelFormat: fmt.mes, stacked: true, max: 100, yFormat: v => Math.round(v) + ' %', height: 270,
    series: cats.map((c, i) => ({ name: c, color: PALETTE[i], format: fmt.pct, values: months.map((m, j) => 100 * (d.categorias_mensual.find(r => r.anio_mes === m && r.categoria === c)?.ingreso || 0) / tm[j]) })) });
  const cm = [...new Set(d.canales.map(r => r.anio_mes))];
  const chs = [...new Set(d.canales.map(r => r.canal))];
  const tc = cm.map(m => d.canales.filter(r => r.anio_mes === m).reduce((a, r) => a + r.valor, 0));
  barChart(ch, { labels: cm, labelFormat: fmt.mes, stacked: true, max: 100, yFormat: v => Math.round(v) + ' %', height: 270,
    series: chs.map((c, i) => ({ name: c, color: PALETTE[[3, 1, 6][i] ?? i], format: fmt.pct, values: cm.map((m, j) => 100 * (d.canales.find(r => r.anio_mes === m && r.canal === c)?.valor || 0) / tc[j]) })) });
  const cx = [...d.complejos].sort((a, b) => b.gasto_dulceria_asistente - a.gasto_dulceria_asistente);
  barChart(gx, { horizontal: true, labels: cx.map(r => r.nombre.replace('Complejo ', '')), valueLabels: true, yFormat: fmt.mxn2,
    series: [{ name: 'Gasto por asistente', values: cx.map(r => r.gasto_dulceria_asistente), color: PALETTE[1] }],
    extraTip: i => `<div>${esc(cx[i].tipo_complejo)} · ${esc(cx[i].ciudad)}</div><div>Margen: <b>${fmt.pct(cx[i].margen_dulceria)}</b></div>` });
  const types = [...new Set(d.dispersion.map(r => r.tipo_complejo))];
  scatter(sc, { points: d.dispersion.map(r => ({ x: r.asistentes, y: r.ingreso_dulceria, label: `${r.complejo} · ${String(r.fecha_key).replace(/(\d{4})(\d{2})(\d{2})/, '$3/$2/$1')}`, group: r.tipo_complejo })),
    xFormat: fmt.compact, yFormat: fmt.mxn, xName: 'Asistentes', yName: 'Dulcería', xLabel: 'Asistentes por día', height: 290 });
  sc.insertAdjacentHTML('beforeend', `<p class="muted" style="margin:6px 0 0;font-size:12px">Correlación de Pearson (todas las observaciones del periodo): <b>${d.correlacion != null ? d.correlacion.toFixed(3) : '—'}</b>. ${types.length > 1 ? 'Los complejos Premium venden más por asistente (servicio en sala VIP).' : ''}</p>`);
  dataTable(tb, { rows: d.productos, pageSize: 10, initialSort: { key: 'ingreso', dir: -1 }, columns: [
    { key: 'sku', label: 'SKU' }, { key: 'nombre', label: 'Producto' }, { key: 'categoria', label: 'Categoría' },
    { key: 'precio_lista', label: 'Precio vigente', num: true, format: fmt.mxn2 }, { key: 'unidades', label: 'Unidades', num: true, format: fmt.int },
    { key: 'ingreso', label: 'Ingreso', num: true, format: fmt.mxn }, { key: 'margen', label: 'Margen', num: true, format: fmt.mxn },
    { key: 'margen_pct', label: 'Margen %', num: true, format: fmt.pct }] });
}

// ================================================================ COMPLEJOS Y PELÍCULAS
export async function viewComplejos(root, stale) {
  chip(root, ' · Haz clic en un complejo para ver su evolución');
  const t1 = add(root, 'Rendimiento por complejo', 'Variación contra el periodo de comparación');
  const detail = add(root, 'Evolución mensual del complejo seleccionado', 'Selecciona un complejo en la tabla');
  const t2 = add(root, 'Películas exhibidas', 'Búsqueda por título, género o distribuidora');
  [t1, t2].forEach(e => loading(e));
  detail.innerHTML = '<div class="chart-empty">Selecciona un complejo en la tabla superior.</div>';
  const d = await api('/api/complejos-peliculas' + qs());
  if (stale()) return;
  const maxT = Math.max(...d.complejos.map(r => r.total));
  const showDetail = async r => {
    detail.parentElement.querySelector('h3').textContent = `Evolución mensual · ${r.nombre}`;
    loading(detail);
    const s = await api(`/api/complejo/${r.complejo_key}/serie`);
    lineChart(detail, { labels: s.map(x => x.anio_mes), xFormat: fmt.mes, yFormat: fmt.mxn, height: 240,
      series: [{ name: 'Taquilla', values: s.map(x => x.taquilla), color: C.taq }, { name: 'Dulcería', values: s.map(x => x.dulceria), color: C.dul }] });
    detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };
  dataTable(t1, { rows: d.complejos, pageSize: 20, initialSort: { key: 'total', dir: -1 }, onRow: showDetail, columns: [
    { key: 'nombre', label: 'Complejo' }, { key: 'ciudad', label: 'Ciudad' },
    { key: 'tipo_complejo', label: 'Tipo', render: r => `<span class="tag ${r.tipo_complejo === 'Premium' ? 'blue' : ''}">${esc(r.tipo_complejo)}</span>` },
    { key: 'num_salas', label: 'Salas', num: true, format: fmt.int },
    { key: 'total', label: 'Ingreso total', num: true, render: r => `<span class="bar-cell">${fmt.mxn(r.total)}<i style="width:${60 * r.total / maxT}px"></i></span>` },
    { key: 'variacion', label: 'Variación', num: true, render: r => r.variacion == null ? '—' : `<span class="tag ${r.variacion >= 0 ? 'good' : 'bad'}">${fmt.var(r.variacion)}</span>` },
    { key: 'taquilla', label: 'Taquilla', num: true, format: fmt.mxn }, { key: 'dulceria', label: 'Dulcería', num: true, format: fmt.mxn },
    { key: 'asistentes', label: 'Asistentes', num: true, format: fmt.int }, { key: 'ocupacion', label: 'Ocupación', num: true, format: fmt.pct },
    { key: 'ticket_promedio', label: 'Ticket', num: true, format: fmt.mxn2 }, { key: 'gasto_dulceria_asistente', label: 'Dulcería/asist.', num: true, format: fmt.mxn2 },
    { key: 'ingreso_por_sala', label: 'Ingreso/sala', num: true, format: fmt.mxn }] });
  dataTable(t2, { rows: d.peliculas, pageSize: 15, initialSort: { key: 'ingreso', dir: -1 }, columns: [
    { key: 'titulo', label: 'Película' }, { key: 'genero', label: 'Género' }, { key: 'clasificacion', label: 'Clasif.' },
    { key: 'tipo_lanzamiento', label: 'Lanzamiento' }, { key: 'distribuidora', label: 'Distribuidora' },
    { key: 'fecha_estreno', label: 'Estreno', format: v => fmt.fecha(v, true) }, { key: 'funciones', label: 'Funciones', num: true, format: fmt.int },
    { key: 'asistentes', label: 'Asistentes', num: true, format: fmt.int }, { key: 'ingreso', label: 'Taquilla', num: true, format: fmt.mxn },
    { key: 'ocupacion', label: 'Ocupación', num: true, format: fmt.pct }, { key: 'asistentes_funcion', label: 'Asist./función', num: true, format: fmt.dec }] });
}
