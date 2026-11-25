// Utilidades compartidas: API, formatos, estado global de filtros y componentes de interfaz.

export const state = { meta: null, filtros: { anio: '', trimestre: '', mes: '', ciudad: '', complejo: '', comparar: 'anterior' } };

export async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  let body = null;
  try { body = await res.json(); } catch { /* sin cuerpo */ }
  if (!res.ok) throw new Error(body?.detail || `Error ${res.status} al consultar ${path}`);
  return body;
}

export function qs(extra = {}) {
  const p = new URLSearchParams();
  Object.entries({ ...state.filtros, ...extra }).forEach(([k, v]) => { if (v !== '' && v != null) p.set(k, v); });
  const s = p.toString();
  return s ? '?' + s : '';
}

// ------------------------------------------------------------------ formatos
const nf = new Intl.NumberFormat('es-MX');
const nf1 = new Intl.NumberFormat('es-MX', { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat('es-MX', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
export const fmt = {
  int: v => v == null ? '—' : nf.format(Math.round(v)),
  dec: v => v == null ? '—' : nf1.format(v),
  pct: v => v == null ? '—' : nf1.format(v) + ' %',
  mxn: (v, full) => {
    if (v == null) return '—';
    if (full) return '$' + nf.format(Math.round(v));
    const a = Math.abs(v);
    if (a >= 1e9) return '$' + nf1.format(v / 1e9) + ' mmd';
    if (a >= 1e6) return '$' + nf1.format(v / 1e6) + ' M';
    if (a >= 1e3) return '$' + nf.format(Math.round(v / 1e3)) + ' mil';
    return '$' + nf.format(Math.round(v));
  },
  mxn2: v => v == null ? '—' : '$' + nf2.format(v),
  compact: v => {
    if (v == null) return '—';
    const a = Math.abs(v);
    if (a >= 1e6) return nf1.format(v / 1e6) + ' M';
    if (a >= 1e3) return nf.format(Math.round(v / 1e3)) + ' mil';
    return nf.format(Math.round(v));
  },
  var: (v, unit = '%') => v == null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + nf1.format(Math.abs(v)) + (unit === 'pp' ? ' pp' : ' %'),
  mes: (am, full) => {
    if (!am) return '';
    const [y, m] = am.split('-');
    const n = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'][+m - 1];
    return full ? `${n} ${y}` : `${n} ${y.slice(2)}`;
  },
  fecha: (d, full) => {
    if (!d) return '';
    const [y, m, dd] = d.split('-');
    return full ? `${dd}/${m}/${y}` : `${+dd} ${['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'][+m - 1]}`;
  },
};
export const byFormat = f => ({ mxn: fmt.mxn, mxn2: fmt.mxn2, int: fmt.int, pct: fmt.pct })[f] || fmt.dec;

export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ------------------------------------------------------------------ componentes
export function h(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }

export function kpiCard(label, k, format, opts = {}) {
  const v = k?.variacion, up = v > 0, unit = k?.unidad_variacion;
  const good = opts.inverse ? !up : up;
  const trend = v == null ? '' : `<span class="trend ${Math.abs(v) < 0.05 ? 'flat' : good ? 'up' : 'down'}" title="Variación contra el periodo de comparación">
      <svg viewBox="0 0 12 12" aria-hidden="true"><path d="${Math.abs(v) < 0.05 ? 'M2 6h8' : up ? 'M2 9 6 3l4 6' : 'M2 3l4 6 4-6'}"/></svg>${fmt.var(v, unit)}</span>`;
  return `<article class="kpi ${opts.hero ? 'kpi-hero' : ''}">
      <span class="kpi-label">${esc(label)}</span>
      <strong class="kpi-value">${format(k?.actual)}</strong>
      <span class="kpi-foot">${trend}<span class="kpi-prev">${k?.anterior != null ? 'Anterior: ' + format(k.anterior) : 'Sin periodo de comparación'}</span></span>
    </article>`;
}

export function card(title, sub = '', cls = '', actions = '') {
  return h(`<section class="card ${cls}"><header class="card-head"><div><h3>${esc(title)}</h3>${sub ? `<p>${sub}</p>` : ''}</div>${actions}</header><div class="card-body"></div></section>`);
}

export function loading(el, msg = 'Consultando el Data Warehouse…') { el.innerHTML = `<div class="loading"><span class="spinner"></span>${esc(msg)}</div>`; }
export function errorBox(el, err) { el.innerHTML = `<div class="error-box"><b>No se pudo cargar la información.</b><span>${esc(err.message || err)}</span></div>`; }

// Tabla con búsqueda, ordenamiento y paginación simple
export function dataTable(container, { columns, rows, search = true, pageSize = 15, initialSort, onRow }) {
  let sortKey = initialSort?.key ?? null, sortDir = initialSort?.dir ?? -1, q = '', page = 0;
  container.innerHTML = '';
  const wrap = h(`<div class="dt">${search ? `<div class="dt-tools"><input type="search" placeholder="Buscar…" aria-label="Buscar en la tabla"><span class="dt-count"></span></div>` : ''}
    <div class="dt-scroll"><table><thead><tr></tr></thead><tbody></tbody></table></div><div class="dt-pager"></div></div>`);
  container.appendChild(wrap);
  const thr = wrap.querySelector('thead tr'), tb = wrap.querySelector('tbody'), pager = wrap.querySelector('.dt-pager');
  columns.forEach(c => {
    const th = document.createElement('th');
    th.innerHTML = `<button type="button">${esc(c.label)}<span class="sort"></span></button>`;
    if (c.num) th.className = 'num';
    th.querySelector('button').addEventListener('click', () => { sortDir = sortKey === c.key ? -sortDir : (c.num ? -1 : 1); sortKey = c.key; page = 0; draw(); });
    thr.appendChild(th);
  });
  if (search) wrap.querySelector('input').addEventListener('input', e => { q = e.target.value.toLowerCase(); page = 0; draw(); });
  function draw() {
    let data = rows.filter(r => !q || columns.some(c => String(c.text ? c.text(r) : r[c.key] ?? '').toLowerCase().includes(q)));
    if (sortKey) data = [...data].sort((a, b) => { const x = a[sortKey], y = b[sortKey]; return (x == null) - (y == null) || (x > y ? 1 : x < y ? -1 : 0) * sortDir; });
    [...thr.children].forEach((th, i) => th.querySelector('.sort').textContent = columns[i].key === sortKey ? (sortDir > 0 ? '▲' : '▼') : '');
    const pages = Math.max(1, Math.ceil(data.length / pageSize));
    page = Math.min(page, pages - 1);
    tb.innerHTML = data.slice(page * pageSize, (page + 1) * pageSize).map((r, i) =>
      `<tr data-i="${i}">${columns.map(c => `<td class="${c.num ? 'num' : ''}">${c.render ? c.render(r) : esc(c.format ? c.format(r[c.key]) : r[c.key])}</td>`).join('')}</tr>`).join('')
      || `<tr><td colspan="${columns.length}" class="muted">Sin resultados.</td></tr>`;
    if (onRow) [...tb.children].forEach((tr, i) => { tr.classList.add('clickable'); tr.addEventListener('click', () => onRow(data[page * pageSize + i])); });
    const cnt = wrap.querySelector('.dt-count'); if (cnt) cnt.textContent = `${fmt.int(data.length)} registros`;
    pager.innerHTML = pages > 1 ? `<button type="button" ${page === 0 ? 'disabled' : ''} data-p="-1">‹ Anterior</button><span>Página ${page + 1} de ${pages}</span><button type="button" ${page >= pages - 1 ? 'disabled' : ''} data-p="1">Siguiente ›</button>` : '';
    pager.querySelectorAll('button').forEach(b => b.addEventListener('click', () => { page += +b.dataset.p; draw(); }));
  }
  draw();
}

export function periodLabel() {
  const f = state.filtros;
  const meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  let p = !f.anio ? 'Todo el histórico' : f.mes ? `${meses[f.mes - 1]} ${f.anio}` : f.trimestre ? `T${f.trimestre} ${f.anio}` : `Año ${f.anio}`;
  const cx = f.complejo ? state.meta.complejos.find(c => String(c.complejo_key) === String(f.complejo))?.nombre : f.ciudad || 'Toda la cadena';
  return `${p} · ${cx}`;
}

export async function pollTask(onUpdate) {
  for (;;) {
    const t = await api('/api/tarea');
    onUpdate(t);
    if (!t.activo) return t;
    await new Promise(r => setTimeout(r, 1200));
  }
}
