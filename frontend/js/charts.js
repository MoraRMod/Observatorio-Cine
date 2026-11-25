// Biblioteca ligera de gráficas SVG (sin dependencias externas, funciona sin internet).
// Formas: líneas (con banda opcional), barras verticales/horizontales (agrupadas o apiladas),
// mapa de calor y dispersión.  Todas incluyen tooltip al pasar el cursor y leyenda (≥ 2 series).

export const PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'];
export const SEQ = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];

const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, parent) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
};

let tip;
function tooltip() {
  if (!tip) { tip = document.createElement('div'); tip.className = 'chart-tip'; document.body.appendChild(tip); }
  return tip;
}
function showTip(evt, html) {
  const t = tooltip(); t.innerHTML = html; t.style.display = 'block';
  const r = t.getBoundingClientRect();
  let x = evt.clientX + 14, y = evt.clientY + 14;
  if (x + r.width > window.innerWidth - 8) x = evt.clientX - r.width - 14;
  if (y + r.height > window.innerHeight - 8) y = evt.clientY - r.height - 14;
  t.style.left = x + 'px'; t.style.top = y + 'px';
}
function hideTip() { if (tip) tip.style.display = 'none'; }
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function niceTicks(min, max, count = 5) {
  if (min === max) { max = min + 1; }
  const span = max - min, step0 = span / count, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= count) || 10 * mag;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step, out = [];
  for (let v = lo; v <= hi + step / 2; v += step) out.push(+v.toFixed(10));
  return out;
}

function legend(container, series) {
  if (series.length < 2) return;
  const lg = document.createElement('div'); lg.className = 'chart-legend';
  series.forEach((s, i) => {
    const it = document.createElement('span'); it.className = 'lg-item';
    it.innerHTML = `<i style="background:${s.color || PALETTE[i % 8]}${s.dashed ? ';background:repeating-linear-gradient(90deg,' + (s.color || PALETTE[i]) + ' 0 4px,transparent 4px 7px)' : ''}"></i>${esc(s.name)}`;
    lg.appendChild(it);
  });
  container.appendChild(lg);
}

function frame(container, opts) {
  container.innerHTML = '';
  container.classList.add('chart');
  const width = Math.max(260, container.clientWidth || 600);
  const height = opts.height || 260;
  const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, width: '100%', height, role: 'img', 'aria-label': opts.label || '' });
  container.appendChild(svg);
  return { svg, width, height };
}

function observe(container, draw) {
  draw();
  if (container._ro) container._ro.disconnect();
  let w = container.clientWidth;
  container._ro = new ResizeObserver(() => { if (Math.abs(container.clientWidth - w) > 8) { w = container.clientWidth; draw(); } });
  container._ro.observe(container);
}

function empty(container, msg = 'Sin datos para los filtros seleccionados.') {
  container.innerHTML = `<div class="chart-empty">${msg}</div>`;
}

// ------------------------------------------------------------------ líneas
export function lineChart(container, opts) {
  const { labels, series, yFormat = v => v, xFormat = v => v, height = 260 } = opts;
  if (!labels?.length) return empty(container);
  observe(container, () => {
    const { svg, width } = frame(container, opts);
    const m = { t: 14, r: 16, b: 30, l: opts.left || 64 };
    const all = series.flatMap(s => [...s.values, ...(s.band ? s.band.flat() : [])]).filter(v => v != null && isFinite(v));
    let ymin = opts.zero === false ? Math.min(...all) : Math.min(0, ...all), ymax = Math.max(...all);
    if (opts.zero === false) { const pad = (ymax - ymin) * 0.08; ymin -= pad; ymax += pad; }
    const ticks = niceTicks(ymin, ymax, 5);
    ymin = ticks[0]; ymax = ticks[ticks.length - 1];
    const X = i => m.l + (labels.length === 1 ? (width - m.l - m.r) / 2 : i * (width - m.l - m.r) / (labels.length - 1));
    const Y = v => m.t + (1 - (v - ymin) / (ymax - ymin || 1)) * (height - m.t - m.b);
    const g = el('g', {}, svg);
    ticks.forEach(t => {
      el('line', { x1: m.l, x2: width - m.r, y1: Y(t), y2: Y(t), class: 'grid' }, g);
      el('text', { x: m.l - 8, y: Y(t) + 4, 'text-anchor': 'end', class: 'axis' }, g).textContent = yFormat(t);
    });
    const every = Math.ceil(labels.length / Math.max(2, Math.floor((width - m.l - m.r) / 70)));
    labels.forEach((lb, i) => {
      if (i % every === 0 || i === labels.length - 1 && labels.length < 40)
        el('text', { x: X(i), y: height - 8, 'text-anchor': 'middle', class: 'axis' }, g).textContent = xFormat(lb);
    });
    (opts.marks || []).forEach(mk => {   // líneas verticales de referencia
      const i = labels.indexOf(mk.at); if (i < 0) return;
      el('line', { x1: X(i), x2: X(i), y1: m.t, y2: height - m.b, class: 'ref-line' }, g);
      el('text', { x: X(i) + 4, y: m.t + 10, class: 'axis ref-label' }, g).textContent = mk.label;
    });
    series.forEach((s, si) => {
      const color = s.color || PALETTE[si % 8];
      if (s.band) {
        const pts = s.band.map((b, i) => b && b[0] != null ? [X(i), Y(b[0]), Y(b[1])] : null).filter(Boolean);
        if (pts.length) el('path', { d: 'M' + pts.map(p => `${p[0]},${p[2]}`).join('L') + 'L' + pts.reverse().map(p => `${p[0]},${p[1]}`).join('L') + 'Z',
          fill: color, opacity: 0.14 }, g);
      }
      let d = '', pen = false;
      s.values.forEach((v, i) => {
        if (v == null || !isFinite(v)) { pen = false; return; }
        d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(v).toFixed(1); pen = true;
      });
      el('path', { d, fill: 'none', stroke: color, 'stroke-width': s.width || 2, 'stroke-dasharray': s.dashed ? '5 4' : null,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, g);
      if (labels.length <= 16 && !s.noDots) s.values.forEach((v, i) => v != null && el('circle', { cx: X(i), cy: Y(v), r: 3, fill: color, stroke: 'var(--surface)', 'stroke-width': 1.5 }, g));
    });
    // crosshair + tooltip
    const cross = el('line', { y1: m.t, y2: height - m.b, class: 'crosshair', visibility: 'hidden' }, g);
    const dots = series.map((s, si) => el('circle', { r: 4.5, fill: s.color || PALETTE[si % 8], stroke: 'var(--surface)', 'stroke-width': 2, visibility: 'hidden' }, g));
    const hit = el('rect', { x: m.l, y: m.t, width: width - m.l - m.r, height: height - m.t - m.b, fill: 'transparent' }, g);
    hit.addEventListener('mousemove', e => {
      const box = svg.getBoundingClientRect(), px = (e.clientX - box.left) * width / box.width;
      const i = Math.max(0, Math.min(labels.length - 1, Math.round((px - m.l) / ((width - m.l - m.r) / Math.max(1, labels.length - 1)))));
      cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('visibility', 'visible');
      let html = `<b>${esc(xFormat(labels[i], true))}</b>`;
      series.forEach((s, si) => {
        const v = s.values[i];
        if (v == null) { dots[si].setAttribute('visibility', 'hidden'); return; }
        dots[si].setAttribute('cx', X(i)); dots[si].setAttribute('cy', Y(v)); dots[si].setAttribute('visibility', 'visible');
        html += `<div><i style="background:${s.color || PALETTE[si % 8]}"></i>${esc(s.name)}: <b>${esc((s.format || yFormat)(v, true))}</b></div>`;
        if (s.band && s.band[i]) html += `<div class="muted">Intervalo: ${esc(yFormat(s.band[i][0], true))} – ${esc(yFormat(s.band[i][1], true))}</div>`;
      });
      showTip(e, html);
    });
    hit.addEventListener('mouseleave', () => { hideTip(); cross.setAttribute('visibility', 'hidden'); dots.forEach(d => d.setAttribute('visibility', 'hidden')); });
    legend(container, series);
  });
}

// ------------------------------------------------------------------ barras
export function barChart(container, opts) {
  const { labels, series, yFormat = v => v, horizontal = false, stacked = false } = opts;
  if (!labels?.length) return empty(container);
  observe(container, () => {
    const height = opts.height || (horizontal ? Math.max(120, labels.length * (series.length > 1 && !stacked ? 30 : 26) + 40) : 260);
    const { svg, width } = frame(container, { ...opts, height });
    const sums = labels.map((_, i) => stacked ? series.reduce((a, s) => a + Math.max(0, s.values[i] || 0), 0) : Math.max(...series.map(s => s.values[i] || 0)));
    const mins = labels.map((_, i) => Math.min(0, ...series.map(s => s.values[i] || 0)));
    const ticks = niceTicks(Math.min(0, ...mins), opts.max ?? (Math.max(...sums, 0) || 1), horizontal ? 4 : 5);
    const vmin = ticks[0], vmax = ticks[ticks.length - 1];
    const g = el('g', {}, svg);
    const fmtLabel = opts.labelFormat || (v => v);
    if (horizontal) {
      const lw = Math.min(opts.labelWidth || 170, width * 0.42);
      const m = { t: 8, r: opts.valueLabels ? 70 : 16, b: 24, l: lw };
      const V = v => m.l + (v - vmin) / (vmax - vmin) * (width - m.l - m.r);
      const band = (height - m.t - m.b) / labels.length;
      ticks.forEach(t => { el('line', { x1: V(t), x2: V(t), y1: m.t, y2: height - m.b, class: 'grid' }, g); el('text', { x: V(t), y: height - 6, 'text-anchor': 'middle', class: 'axis' }, g).textContent = yFormat(t); });
      labels.forEach((lb, i) => {
        const y0 = m.t + i * band;
        const t = el('text', { x: m.l - 8, y: y0 + band / 2 + 4, 'text-anchor': 'end', class: 'axis cat' }, g);
        const s = String(fmtLabel(lb)); t.textContent = s.length > lw / 6.6 ? s.slice(0, Math.floor(lw / 6.6) - 1) + '…' : s;
        let acc = 0;
        const n = stacked ? 1 : series.length, bh = Math.min(22, (band - 6) / n);
        series.forEach((se, si) => {
          const v = se.values[i] || 0, color = se.color || (opts.colorBy ? opts.colorBy(lb, i) : PALETTE[si % 8]);
          const x0 = stacked ? V(acc) : V(Math.min(0, v)), w = Math.abs(V(v) - V(0)) - (stacked && si < series.length - 1 ? 2 : 0);
          const y = stacked ? y0 + (band - bh) / 2 : y0 + (band - bh * n) / 2 + si * bh;
          const r = el('rect', { x: x0, y: y + 1, width: Math.max(0, w), height: Math.max(1, bh - 2), rx: 3, fill: color }, g);
          r.addEventListener('mousemove', e => showTip(e, `<b>${esc(fmtLabel(lb))}</b><div><i style="background:${color}"></i>${esc(se.name)}: <b>${esc((se.format || yFormat)(v, true))}</b></div>${opts.extraTip ? opts.extraTip(i) : ''}`));
          r.addEventListener('mouseleave', hideTip);
          if (opts.onClick) { r.style.cursor = 'pointer'; r.addEventListener('click', () => opts.onClick(lb, i)); }
          if (stacked) acc += v;
        });
        if (opts.valueLabels) el('text', { x: V(stacked ? acc : Math.max(...series.map(s => s.values[i] || 0))) + 6, y: y0 + band / 2 + 4, class: 'axis value' }, g).textContent = yFormat(stacked ? acc : series[0].values[i]);
      });
    } else {
      const m = { t: 12, r: 12, b: opts.rotate ? 58 : 30, l: opts.left || 64 };
      const V = v => m.t + (1 - (v - vmin) / (vmax - vmin)) * (height - m.t - m.b);
      const band = (width - m.l - m.r) / labels.length;
      ticks.forEach(t => { el('line', { x1: m.l, x2: width - m.r, y1: V(t), y2: V(t), class: 'grid' }, g); el('text', { x: m.l - 8, y: V(t) + 4, 'text-anchor': 'end', class: 'axis' }, g).textContent = yFormat(t); });
      const every = Math.ceil(labels.length / Math.max(2, Math.floor((width - m.l - m.r) / (opts.rotate ? 22 : 54))));
      labels.forEach((lb, i) => {
        const x0 = m.l + i * band;
        if (i % every === 0) {
          const t = el('text', { x: x0 + band / 2, y: height - (opts.rotate ? 44 : 10), 'text-anchor': opts.rotate ? 'end' : 'middle', class: 'axis',
            transform: opts.rotate ? `rotate(-40 ${x0 + band / 2} ${height - 44})` : null }, g);
          t.textContent = fmtLabel(lb);
        }
        let acc = 0;
        const n = stacked ? 1 : series.length, bw = Math.min(48, (band * 0.78) / n);
        series.forEach((se, si) => {
          const v = se.values[i] || 0, color = se.color || PALETTE[si % 8];
          const x = stacked ? x0 + (band - bw) / 2 : x0 + (band - bw * n) / 2 + si * bw;
          const top = stacked ? V(acc + v) : V(Math.max(0, v)), bottom = stacked ? V(acc) : V(Math.min(0, v));
          const r = el('rect', { x: x + 1, y: top, width: Math.max(1, bw - 2), height: Math.max(0, bottom - top - (stacked && si > 0 ? 2 : 0)), rx: 3, fill: color }, g);
          r.addEventListener('mousemove', e => {
            let html = `<b>${esc(fmtLabel(lb, true))}</b>`;
            series.forEach((s2, k) => { html += `<div><i style="background:${s2.color || PALETTE[k % 8]}"></i>${esc(s2.name)}: <b>${esc((s2.format || yFormat)(s2.values[i] || 0, true))}</b></div>`; });
            showTip(e, html + (opts.extraTip ? opts.extraTip(i) : ''));
          });
          r.addEventListener('mouseleave', hideTip);
          if (opts.onClick) { r.style.cursor = 'pointer'; r.addEventListener('click', () => opts.onClick(lb, i)); }
          if (stacked) acc += v;
        });
      });
      el('line', { x1: m.l, x2: width - m.r, y1: V(0), y2: V(0), class: 'baseline' }, g);
    }
    legend(container, series);
  });
}

// ------------------------------------------------------------------ mapa de calor
export function heatmap(container, opts) {
  const { rows, cols, values, format = v => v, height } = opts;
  if (!rows?.length) return empty(container);
  observe(container, () => {
    const h = height || rows.length * 30 + 40;
    const { svg, width } = frame(container, { ...opts, height: h });
    const m = { t: 22, r: 8, b: 6, l: 92 };
    const cw = (width - m.l - m.r) / cols.length, ch = (h - m.t - m.b) / rows.length;
    const flat = values.flat().filter(v => v != null);
    const lo = Math.min(...flat), hi = Math.max(...flat);
    const g = el('g', {}, svg);
    cols.forEach((c, j) => { if (cw > 22 || j % 2 === 0) el('text', { x: m.l + j * cw + cw / 2, y: 14, 'text-anchor': 'middle', class: 'axis' }, g).textContent = c; });
    rows.forEach((r, i) => {
      el('text', { x: m.l - 8, y: m.t + i * ch + ch / 2 + 4, 'text-anchor': 'end', class: 'axis cat' }, g).textContent = r;
      cols.forEach((c, j) => {
        const v = values[i][j];
        const k = v == null ? -1 : Math.min(SEQ.length - 1, Math.floor((v - lo) / ((hi - lo) || 1) * SEQ.length));
        const rect = el('rect', { x: m.l + j * cw + 1, y: m.t + i * ch + 1, width: cw - 2, height: ch - 2, rx: 3,
          fill: v == null ? 'var(--grid)' : SEQ[k] }, g);
        if (cw > 34 && v != null) el('text', { x: m.l + j * cw + cw / 2, y: m.t + i * ch + ch / 2 + 4, 'text-anchor': 'middle',
          class: 'cell-label', fill: k >= 4 ? '#fff' : 'var(--ink)' }, g).textContent = opts.cellFormat ? opts.cellFormat(v) : format(v);
        rect.addEventListener('mousemove', e => showTip(e, `<b>${esc(r)} · ${esc(c)}</b><div>${esc(opts.metric || 'Valor')}: <b>${v == null ? 'sin funciones' : esc(format(v, true))}</b></div>${opts.extraTip ? opts.extraTip(i, j) : ''}`));
        rect.addEventListener('mouseleave', hideTip);
      });
    });
    const lg = document.createElement('div'); lg.className = 'chart-legend seq';
    lg.innerHTML = `<span>${esc(format(lo))}</span>${SEQ.map(c => `<i style="background:${c}"></i>`).join('')}<span>${esc(format(hi))}</span>`;
    container.appendChild(lg);
  });
}

// ------------------------------------------------------------------ dispersión
export function scatter(container, opts) {
  const { points, xFormat = v => v, yFormat = v => v, height = 300 } = opts;
  if (!points?.length) return empty(container);
  observe(container, () => {
    const { svg, width } = frame(container, { ...opts, height });
    const m = { t: 12, r: 16, b: 36, l: opts.left || 66 };
    const xs = points.map(p => p.x), ys = points.map(p => p.y);
    let xmax = Math.max(...xs), ymax = Math.max(...ys);
    if (opts.diagonal) xmax = ymax = Math.max(xmax, ymax);
    const xt = niceTicks(0, xmax, 5), yt = niceTicks(0, ymax, 5);
    const X = v => m.l + v / xt[xt.length - 1] * (width - m.l - m.r), Y = v => m.t + (1 - v / yt[yt.length - 1]) * (height - m.t - m.b);
    const g = el('g', {}, svg);
    yt.forEach(t => { el('line', { x1: m.l, x2: width - m.r, y1: Y(t), y2: Y(t), class: 'grid' }, g); el('text', { x: m.l - 8, y: Y(t) + 4, 'text-anchor': 'end', class: 'axis' }, g).textContent = yFormat(t); });
    xt.forEach(t => el('text', { x: X(t), y: height - 18, 'text-anchor': 'middle', class: 'axis' }, g).textContent = xFormat(t));
    if (opts.xLabel) el('text', { x: (m.l + width - m.r) / 2, y: height - 2, 'text-anchor': 'middle', class: 'axis axis-title' }, g).textContent = opts.xLabel;
    if (opts.yLabel) el('text', { x: m.l, y: m.t - 2, class: 'axis axis-title' }, g).textContent = '';
    if (opts.diagonal) el('line', { x1: X(0), y1: Y(0), x2: X(xt[xt.length - 1]), y2: Y(xt[xt.length - 1]), class: 'ref-line' }, g);
    const groups = [...new Set(points.map(p => p.group || ''))];
    points.forEach(p => {
      const color = p.group ? PALETTE[groups.indexOf(p.group) % 8] : PALETTE[0];
      const c = el('circle', { cx: X(p.x), cy: Y(p.y), r: opts.r || 3.2, fill: color, 'fill-opacity': 0.55, stroke: 'var(--surface)', 'stroke-width': 0.8 }, g);
      c.addEventListener('mousemove', e => showTip(e, `${p.label ? `<b>${esc(p.label)}</b>` : ''}<div>${esc(opts.xName || 'x')}: <b>${esc(xFormat(p.x, true))}</b></div><div>${esc(opts.yName || 'y')}: <b>${esc(yFormat(p.y, true))}</b></div>`));
      c.addEventListener('mouseleave', hideTip);
    });
    if (groups.length > 1) legend(container, groups.map((gname, i) => ({ name: gname, color: PALETTE[i % 8] })));
  });
}
