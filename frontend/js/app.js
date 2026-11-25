// Enrutador de la SPA y filtros globales.
import { api, errorBox, state } from './core.js';
import { viewResumen, viewVentas, viewTaquilla, viewDulceria, viewComplejos } from './views/dashboard.js';
import { viewOlap } from './views/olap.js';
import { viewModelo, viewInteligencia } from './views/modelo.js';
import { viewDW, viewETL } from './views/dw.js';

const VIEWS = {
  resumen: { title: 'Resumen ejecutivo', eyebrow: 'Indicadores clave de la cadena', fn: viewResumen, filters: true },
  ventas: { title: 'Ventas y rendimiento', eyebrow: 'Comportamiento de ingresos', fn: viewVentas, filters: true },
  taquilla: { title: 'Análisis de taquilla', eyebrow: 'Películas, horarios, formatos y canales', fn: viewTaquilla, filters: true },
  dulceria: { title: 'Análisis de dulcería', eyebrow: 'Productos, márgenes y consumo por asistente', fn: viewDulceria, filters: true },
  complejos: { title: 'Complejos y películas', eyebrow: 'Rendimiento detallado', fn: viewComplejos, filters: true },
  olap: { title: 'Análisis multidimensional OLAP', eyebrow: 'Roll-up · Drill-down · Slice · Dice · Pivot', fn: viewOlap, filters: false },
  modelo: { title: 'Modelo predictivo', eyebrow: 'Minería de datos · Pronóstico de ingresos', fn: viewModelo, filters: false },
  inteligencia: { title: 'Inteligencia de negocios', eyebrow: 'Hallazgos y recomendaciones para la dirección', fn: viewInteligencia, filters: false },
  dw: { title: 'Data Warehouse', eyebrow: 'Arquitectura, modelo en estrella y diccionario de datos', fn: viewDW, filters: false },
  etl: { title: 'Procesos ETL', eyebrow: 'Extracción, transformación y carga', fn: viewETL, filters: false },
};
const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
const form = document.getElementById('filters');
let renderSeq = 0;

function fillFilters() {
  const m = state.meta;
  const sel = n => form.elements[n];
  sel('anio').innerHTML = '<option value="">Todos</option>' + m.anios.map(y => `<option>${y}</option>`).join('');
  sel('mes').innerHTML = '<option value="">—</option>' + MESES.map((n, i) => `<option value="${i + 1}">${n}</option>`).join('');
  sel('ciudad').innerHTML = '<option value="">Todas</option>' + m.ciudades.map(c => `<option>${c}</option>`).join('');
  fillComplejos();
  const last = m.anios.filter(y => m.hasta >= `${y}-12-31`).pop() || m.anios[m.anios.length - 1];
  state.filtros.anio = String(last);
  syncForm();
}
function fillComplejos() {
  const c = state.filtros.ciudad;
  form.elements.complejo.innerHTML = '<option value="">Todos</option>' + state.meta.complejos
    .filter(x => !c || x.ciudad === c).map(x => `<option value="${x.complejo_key}">${x.nombre}</option>`).join('');
}
function syncForm() {
  for (const [k, v] of Object.entries(state.filtros)) if (form.elements[k]) form.elements[k].value = v;
  const noYear = !state.filtros.anio;
  form.elements.trimestre.disabled = noYear || !!state.filtros.mes;
  form.elements.mes.disabled = noYear || !!state.filtros.trimestre;
  form.elements.comparar.disabled = noYear;
}
form.addEventListener('change', e => {
  const n = e.target.name;
  state.filtros[n] = e.target.value;
  if (n === 'anio' && !e.target.value) { state.filtros.trimestre = ''; state.filtros.mes = ''; }
  if (n === 'ciudad') { state.filtros.complejo = ''; fillComplejos(); }
  if (n === 'complejo' && e.target.value) {
    const cx = state.meta.complejos.find(x => String(x.complejo_key) === e.target.value);
    if (cx) state.filtros.ciudad = cx.ciudad;
  }
  syncForm();
  route();
});

async function route() {
  const name = (location.hash.replace('#/', '') || 'resumen').split('?')[0];
  const v = VIEWS[name] || VIEWS.resumen;
  document.querySelectorAll('#nav a').forEach(a => a.classList.toggle('active', a.dataset.view === name));
  document.getElementById('view-title').textContent = v.title;
  document.getElementById('view-eyebrow').textContent = v.eyebrow;
  document.title = `${v.title} · Cine BI`;
  form.classList.toggle('is-hidden', !v.filters);
  const root = document.getElementById('view');
  const seq = ++renderSeq;
  root.innerHTML = '';
  try {
    await v.fn(root, () => seq !== renderSeq);
  } catch (err) {
    console.error(err);
    if (seq === renderSeq) errorBox(root, err);
  }
  document.getElementById('sidebar').classList.remove('open');
}

document.getElementById('menu-btn').addEventListener('click', () => {
  const sb = document.getElementById('sidebar');
  sb.classList.toggle('open');
  document.getElementById('menu-btn').setAttribute('aria-expanded', sb.classList.contains('open'));
});
window.addEventListener('hashchange', route);
window.addEventListener('cine:meta-refresh', async () => { state.meta = await api('/api/meta'); updateFooter(); });

function updateFooter() {
  const m = state.meta;
  document.getElementById('data-label').textContent = m.etiqueta;
  document.getElementById('footer-info').textContent =
    `Datos del ${m.desde} al ${m.hasta} · Última carga ETL: ${m.ultima_etl ? `#${m.ultima_etl.run_id} (${m.ultima_etl.estado}, ${m.ultima_etl.fin})` : '—'} · ` +
    `Modelo: ${m.modelo ? m.modelo.algoritmo + ' (' + m.modelo.entrenado_en.replace('T', ' ') + ')' : 'sin entrenar'}`;
}

(async function init() {
  try {
    state.meta = await api('/api/meta');
    fillFilters();
    updateFooter();
    route();
  } catch (err) {
    document.getElementById('view-title').textContent = 'Error de conexión';
    errorBox(document.getElementById('view'), err);
  }
})();
