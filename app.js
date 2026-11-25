const fmt = new Intl.NumberFormat('es-MX');
const $ = (id) => document.getElementById(id);
const displayState = (state) => state === 'México' ? 'Estado de México' : state;
let complexes = [];
let selectedState = '';
let searchText = '';

function render() {
  const byState = selectedState ? complexes.filter(item => item.state === selectedState) : complexes;
  const filtered = byState.filter(item => (item.name + ' ' + item.city).toLocaleLowerCase('es-MX').includes(searchText));
  $('complex-count').textContent = fmt.format(byState.length);
  $('screen-count').textContent = fmt.format(byState.reduce((sum, item) => sum + item.screens, 0));
  $('state-count').textContent = fmt.format(new Set(byState.map(item => item.state)).size);
  $('metric-area').textContent = selectedState || 'Directorio SIC · México';
  $('result-count').textContent = fmt.format(filtered.length) + ' REGISTROS';
  $('complex-table').replaceChildren();
  if (!filtered.length) {
    const tr = document.createElement('tr'), td = document.createElement('td');
    td.colSpan = 3; td.textContent = 'No se encontraron complejos.'; tr.append(td); $('complex-table').append(tr);
  } else {
    const fragment = document.createDocumentFragment();
    filtered.forEach(item => {
      const tr = document.createElement('tr');
      [item.name, item.state, fmt.format(item.screens)].forEach(value => { const td = document.createElement('td'); td.textContent = value; tr.append(td); });
      fragment.append(tr);
    });
    $('complex-table').append(fragment);
  }
  const counts = new Map();
  complexes.forEach(item => counts.set(item.state, (counts.get(item.state) || 0) + 1));
  const top = [...counts.entries()].sort((a,b) => b[1] - a[1]).slice(0,8);
  const max = top[0]?.[1] || 1;
  $('bar-chart').replaceChildren();
  top.forEach(([state, count]) => {
    const row = document.createElement('div'); row.className = 'bar-row';
    const label = document.createElement('span'); label.textContent = state;
    const track = document.createElement('div'); track.className = 'bar-track';
    const fill = document.createElement('div'); fill.className = 'bar-fill'; fill.style.width = (count / max * 100) + '%';
    const number = document.createElement('b'); number.textContent = fmt.format(count);
    track.append(fill); row.append(label, track, number); $('bar-chart').append(row);
  });
  $('bar-chart').setAttribute('aria-label', 'Complejos por entidad, top 8 nacional: ' + top.map(([state, count]) => state + ' ' + fmt.format(count)).join(', '));
}

async function load() {
  try {
    const response = await fetch('./data/complejos.json');
    if (!response.ok) throw new Error('No se pudo abrir el archivo de datos.');
    complexes = (await response.json()).map(item => ({ ...item, state: displayState(item.state) }));
    complexes.sort((a,b) => a.name.localeCompare(b.name, 'es-MX'));
    [...new Set(complexes.map(item => item.state))].sort((a,b) => a.localeCompare(b,'es-MX')).forEach(state => {
      const option = document.createElement('option'); option.value = option.textContent = state; $('state-filter').append(option);
    });
    $('state-filter').addEventListener('change', event => { selectedState = event.target.value; render(); });
    $('search-filter').addEventListener('input', event => { searchText = event.target.value.trim().toLocaleLowerCase('es-MX'); render(); });
    render();
  } catch(error) {
    $('complex-table').innerHTML = '<tr><td colspan="3">No se pudo cargar el directorio. Abre el sitio mediante un servidor local.</td></tr>';
    const status = document.createElement('p'); status.className = 'chart-status is-error'; status.textContent = error.message;
    $('bar-chart').replaceChildren(status);
  }
}
load();

// ---------------------------------------------------------------------------
// Datos sintéticos del Data Warehouse (API de la plataforma BI)
// ---------------------------------------------------------------------------
const MONTHS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
const money = value => {
  if (value == null) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e9) return '$' + (value / 1e9).toLocaleString('es-MX', { maximumFractionDigits: 2 }) + ' mmd';
  if (abs >= 1e6) return '$' + (value / 1e6).toLocaleString('es-MX', { maximumFractionDigits: 1 }) + ' M';
  return '$' + fmt.format(Math.round(value));
};
const pct = value => value == null ? '—' : value.toLocaleString('es-MX', { maximumFractionDigits: 1 }) + ' %';
const variation = (v, unit = '%') => v == null ? '' : (v >= 0 ? '▲ +' : '▼ −') + Math.abs(v).toLocaleString('es-MX', { maximumFractionDigits: 1 }) + (unit === 'pp' ? ' pp' : ' %');

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error('La API respondió ' + response.status);
  return response.json();
}

function drawSynthetic(months) {
  const key = $('synthetic-view').value;
  const labels = { boletos: 'Boletos por mes', taquilla: 'Ingreso de taquilla por mes', dulceria: 'Ingreso de dulcería por mes', ocupacion: 'Ocupación promedio por mes' };
  const show = v => key === 'boletos' ? fmt.format(v) + ' boletos' : key === 'ocupacion' ? pct(v) : money(v);
  $('synthetic-chart-title').textContent = labels[key];
  const max = Math.max(...months.map(m => m[key]));
  const chart = $('synthetic-chart');
  chart.style.gridTemplateColumns = `repeat(${months.length}, minmax(0, 1fr))`;
  chart.style.gap = months.length > 24 ? '3px' : '10px';
  chart.replaceChildren();
  months.forEach((m, index) => {
    const [year, month] = m.anio_mes.split('-');
    const column = document.createElement('div'); column.className = 'synthetic-month';
    const bar = document.createElement('div'); bar.className = 'synthetic-bar';
    if (year % 2 === 0) bar.classList.add('is-alt');
    bar.style.height = (m[key] / max * 165) + 'px';
    bar.title = `${MONTHS[month - 1]} ${year}: ${show(m[key])} · dato sintético`;
    const label = document.createElement('span');
    label.textContent = month === '01' ? year : (months.length > 24 ? '' : MONTHS[month - 1]);
    column.append(bar, label); chart.append(column);
  });
  chart.setAttribute('aria-label', labels[key] + ', datos sintéticos de ' + months[0].anio_mes + ' a ' + months[months.length - 1].anio_mes);
}

const BI_VIEWS = [
  ['resumen', 'Resumen ejecutivo', 'Los 10 KPI principales comparados contra el periodo anterior.'],
  ['ventas', 'Ventas y rendimiento', 'Taquilla frente a dulcería, ticket promedio, ciudades y días de la semana.'],
  ['taquilla', 'Análisis de taquilla', 'Películas, géneros, ocupación por horario, formatos, canales y promociones.'],
  ['dulceria', 'Análisis de dulcería', 'Categorías, productos, márgenes y gasto por asistente.'],
  ['complejos', 'Complejos y películas', 'Tablas con búsqueda y ordenamiento del rendimiento detallado.'],
  ['olap', 'Análisis multidimensional OLAP', 'Roll-up, drill-down, slice, dice y pivot sobre el cubo.'],
  ['modelo', 'Modelo predictivo', 'Pronóstico de ingresos a 7 y 30 días con métricas de evaluación.'],
  ['inteligencia', 'Inteligencia de negocios', 'Hallazgos, riesgos y recomendaciones estratégicas.'],
  ['dw', 'Data Warehouse', 'Arquitectura por capas, modelo en estrella y diccionario de datos.'],
  ['etl', 'Procesos ETL', 'Bitácora de cargas, registros rechazados y carga incremental.'],
];

async function loadSynthetic() {
  try {
    const meta = await getJSON('/api/meta');
    const year = meta.anios.filter(y => meta.hasta >= `${y}-12-31`).pop() || meta.anios[meta.anios.length - 1];
    const data = await getJSON('/api/resumen?anio=' + year);
    const months = data.mensual.map(m => ({ ...m, ocupacion: m.ocupacion }));
    const total = key => months.reduce((sum, m) => sum + m[key], 0);
    $('dw-badge').textContent = `MODELO SINTÉTICO · ${meta.complejos.length} COMPLEJOS · ${meta.desde.slice(0, 4)}–${meta.hasta.slice(0, 4)}`;
    $('synthetic-revenue').textContent = money(total('total'));
    $('synthetic-revenue-note').textContent = `Taquilla + dulcería, ${meta.desde.slice(0, 4)}–${meta.hasta.slice(0, 4)}`;
    $('synthetic-tickets').textContent = fmt.format(total('boletos'));
    $('synthetic-functions-note').textContent = fmt.format(total('funciones')) + ' funciones registradas';
    $('synthetic-occupancy').textContent = pct(100 * total('boletos') / total('capacidad'));
    $('synthetic-view').addEventListener('change', () => drawSynthetic(months));
    drawSynthetic(months);
    renderBI(meta, data, year);
  } catch (error) {
    const msg = 'No se pudieron leer los datos del Data Warehouse. Inicia la plataforma con «python run.py» y abre http://localhost:8765.';
    const status = document.createElement('p'); status.className = 'chart-status is-error'; status.textContent = msg;
    $('synthetic-chart').replaceChildren(status);
    $('bi-status').textContent = msg;
    renderBI(null, null, null);
  }
}

function renderBI(meta, data, year) {
  const k = data?.kpis.kpis;
  const top = data?.complejos?.[0], film = data?.peliculas?.[0];
  if (k) {
    $('bi-kpis').innerHTML = [
      ['INGRESOS ' + year, money(k.ingresos_totales.actual), variation(k.ingresos_totales.variacion)],
      ['ASISTENCIA ' + year, fmt.format(k.asistencia.actual), variation(k.asistencia.variacion)],
      ['OCUPACIÓN ' + year, pct(k.ocupacion.actual), variation(k.ocupacion.variacion, 'pp')],
      ['MARGEN DULCERÍA', pct(k.margen_dulceria.actual), variation(k.margen_dulceria.variacion, 'pp')],
    ].map(([label, value, v]) => `<article class="metric is-synthetic"><span>${label}</span><strong>${value}</strong><small>${v ? v + ' vs. año anterior' : ''}</small></article>`).join('');
  }
  const facts = k ? {
    resumen: `${money(k.ingresos_totales.actual)} en ${year}`,
    ventas: `Ticket promedio ${money(k.ticket_promedio.actual).replace(' M', '')}`,
    taquilla: film ? `Top: «${film.titulo}»` : '',
    dulceria: `${money(k.ingresos_dulceria.actual)} · margen ${pct(k.margen_dulceria.actual)}`,
    complejos: top ? `Líder: ${top.nombre.replace('Complejo ', '')}` : '',
    olap: '5 operaciones · 21 dimensiones',
    modelo: meta?.modelo ? meta.modelo.algoritmo : '',
    inteligencia: 'Recomendaciones con indicador',
    dw: '8 dimensiones · 3 hechos · 4 marts',
    etl: meta?.ultima_etl ? `Última carga #${meta.ultima_etl.run_id}: ${meta.ultima_etl.estado.toLowerCase()}` : '',
  } : {};
  $('bi-list').innerHTML = BI_VIEWS.map(([view, title, desc], i) => `
    <li><a class="bi-item" href="/bi#/${view}">
      <span class="bi-num">${String(i + 1).padStart(2, '0')}</span>
      <span class="bi-text"><b>${title}</b><span>${desc}</span>${facts[view] ? `<em>${facts[view].replace(/[<>&]/g, '')}</em>` : ''}</span>
      <span class="bi-arrow" aria-hidden="true">↗</span></a></li>`).join('');
}
loadSynthetic();
