// Data Warehouse (arquitectura, modelo en estrella, diccionario, validaciones) y Procesos ETL.
import { api, card, dataTable, esc, fmt, h, loading, pollTask } from '../core.js';
import { barChart } from '../charts.js';

function add(parent, title, sub, cls) { const c = card(title, sub, cls); parent.appendChild(c); return c.querySelector('.card-body'); }

const LAYERS = [
  ['1', 'Fuentes de datos', 'Exportaciones simuladas: catálogos JSON y CSV mensuales de programación, taquilla y dulcería (con errores intencionales).', 'data/sources/'],
  ['2', 'Staging area', 'Copia cruda (texto) de cada extracción para auditar y transformar sin tocar las fuentes.', 'data/staging.sqlite'],
  ['3', 'Transformación ETL', 'Limpieza, deduplicación, validación, normalización, imputación y cálculo de ingresos, márgenes y ocupación.', 'backend/etl/pipeline.py'],
  ['4', 'Data Warehouse', 'Modelo en estrella: 8 dimensiones y 3 tablas de hechos con claves sustitutas e integridad referencial.', 'data/warehouse.sqlite'],
  ['5', 'Data marts', 'Agregados diario por complejo, mensual por película, taquilla por canal y dulcería por producto.', 'tablas mart_*'],
  ['6', 'Capa de BI', 'API FastAPI, motor OLAP, modelo predictivo (scikit-learn) y este tablero.', 'backend/api · frontend/'],
];

function starSVG(t) {
  const n = name => fmt.int(t.find(x => x.tabla === name)?.filas);
  const dims = {
    dim_pelicula: [20, 20, 'título, género, clasificación, estreno, distribuidora'], dim_sala: [20, 140, 'complejo_key (FK), formato, capacidad'],
    dim_horario: [20, 260, 'hora, turno, clasificación del horario'], dim_promocion: [20, 380, 'tipo, % descuento, vigencia'],
    dim_fecha: [770, 40, 'día, semana, mes, trimestre, año, temporada, festivo'], dim_complejo: [770, 175, 'nombre, ciudad, estado, región, tipo'],
    dim_canal: [770, 310, 'nombre, tipo (presencial / digital)'], dim_producto: [770, 430, 'producto, categoría, precio, costo'],
  };
  const facts = {
    fact_funciones: [385, 10, ['capacidad', 'boletos_vendidos', 'asistentes', 'asientos_disponibles', 'porcentaje_ocupacion']],
    fact_ventas_boletos: [385, 190, ['boletos_vendidos', 'precio_unitario', 'descuento_unitario', 'ingreso_total']],
    fact_ventas_dulceria: [385, 370, ['unidades_vendidas', 'precio / costo unitario', 'ingreso_total', 'costo_total', 'margen_bruto']],
  };
  const rel = { fact_funciones: ['dim_fecha', 'dim_complejo', 'dim_pelicula', 'dim_sala', 'dim_horario', 'dim_promocion'],
    fact_ventas_boletos: ['dim_fecha', 'dim_complejo', 'dim_pelicula', 'dim_sala', 'dim_horario', 'dim_canal', 'dim_promocion'],
    fact_ventas_dulceria: ['dim_fecha', 'dim_complejo', 'dim_producto', 'dim_canal'] };
  const DW = 210, DH = 74, FW = 230, FH = 150;
  let edges = '', boxes = '';
  Object.entries(rel).forEach(([f, ds]) => ds.forEach(dn => {
    const [fx, fy] = facts[f], [dx, dy] = dims[dn];
    const left = dx < fx;
    const x1 = left ? fx : fx + FW, y1 = fy + FH / 2, x2 = left ? dx + DW : dx, y2 = dy + DH / 2;
    const mx = (x1 + x2) / 2;
    edges += `<path class="edge" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"/><circle cx="${x2}" cy="${y2}" r="3" fill="#8a93a8"/>`;
  }));
  Object.entries(dims).forEach(([name, [x, y, desc]]) => {
    boxes += `<rect class="box" x="${x}" y="${y}" width="${DW}" height="${DH}" rx="10"/><text class="t" x="${x + 12}" y="${y + 21}">${name}</text>
      <text class="s" x="${x + 12}" y="${y + 38}">PK ${name.replace('dim_', '')}_key · ${n(name)} filas</text>
      <text class="s" x="${x + 12}" y="${y + 55}">${desc.length > 40 ? desc.slice(0, 39) + '…' : desc}</text>`;
  });
  Object.entries(facts).forEach(([name, [x, y, ms]]) => {
    boxes += `<rect class="box fact" x="${x}" y="${y}" width="${FW}" height="${FH}" rx="10"/><text class="t" x="${x + 12}" y="${y + 21}">${name}</text>
      <text class="s" x="${x + 12}" y="${y + 37}">${n(name)} filas · FK a ${rel[name].length} dimensiones</text>
      ${ms.map((m, i) => `<text class="s" x="${x + 12}" y="${y + 58 + i * 17}">◆ ${m}</text>`).join('')}`;
  });
  return `<svg viewBox="0 0 1000 530" role="img" aria-label="Modelo dimensional en estrella con tres tablas de hechos y ocho dimensiones">${edges}${boxes}</svg>`;
}

export async function viewDW(root, stale) {
  const ph = h('<div></div>'); root.appendChild(ph); loading(ph);
  const [d, val, dir] = await Promise.all([api('/api/dw/esquema'), api('/api/dw/validaciones'), api('/api/publico/directorio')]);
  if (stale()) return;
  ph.remove();
  add(root, 'Arquitectura de Business Intelligence implementada', 'Flujo de los datos por capas').innerHTML =
    `<div class="layer-flow">${LAYERS.map(l => `<div class="layer"><em>CAPA ${l[0]}</em><b>${l[1]}</b>${l[2]}<div class="muted" style="margin-top:6px;font-size:11px"><code>${l[3]}</code></div></div>`).join('')}</div>`;
  const star = add(root, 'Modelo dimensional en estrella (constelación de hechos)', 'Tres tablas de hechos comparten dimensiones conformadas (fecha, complejo, canal). Diagrama generado con los conteos reales del DW.', 'diagram');
  star.innerHTML = starSVG(d.tablas);
  const g = h('<div class="grid g2"></div>'); root.appendChild(g);
  const sum = add(g, 'Tablas del almacén', `Tamaño del archivo: ${fmt.dec(d.tamano_mb)} MB · haz clic para ver el diccionario de datos`);
  const vb = add(g, 'Validación de calidad e integridad', 'Pruebas ejecutadas en vivo contra el Data Warehouse');
  vb.innerHTML = val.map(c => `<div class="check"><span class="tag ${c.ok ? 'good' : 'bad'}">${c.ok ? '✓ OK' : '✗ FALLA'}</span><div><b>${esc(c.prueba)}</b><br><span class="muted">${esc(c.detalle)}</span></div></div>`).join('');
  const dict = add(root, 'Diccionario de datos', 'Selecciona una tabla');
  const showDict = t => {
    dict.parentElement.querySelector('h3').textContent = `Diccionario de datos · ${t.tabla}`;
    dict.innerHTML = `<p style="margin-top:0">${esc(t.descripcion || '')}${t.grano ? `<br><b>Grano:</b> ${esc(t.grano)}` : ''}</p><div class="dict"></div>`;
    dataTable(dict.querySelector('.dict'), { search: false, pageSize: 40, rows: t.columnas, columns: [
      { key: 'nombre', label: 'Columna', render: c => `<code>${esc(c.nombre)}</code>` }, { key: 'tipo', label: 'Tipo' },
      { key: 'pk', label: 'Clave', render: c => (c.pk ? '<span class="tag blue">PK</span> ' : '') + (c.fk ? `<span class="tag">FK → ${esc(c.fk)}</span>` : '') },
      { key: 'nulo', label: 'Nulos', render: c => c.nulo ? 'Sí' : 'No' }, { key: 'comentario', label: 'Descripción', render: c => esc(c.comentario || '') }] });
  };
  dataTable(sum, { search: true, pageSize: 25, rows: d.tablas, onRow: showDict, initialSort: { key: 'capa', dir: 1 }, columns: [
    { key: 'tabla', label: 'Tabla', render: t => `<code>${esc(t.tabla)}</code>` }, { key: 'capa', label: 'Capa' },
    { key: 'filas', label: 'Filas', num: true, format: fmt.int }, { key: 'grano', label: 'Grano', render: t => `<span class="muted" style="white-space:normal">${esc(t.grano || '')}</span>` }] });
  showDict(d.tablas.find(t => t.tabla === 'fact_funciones'));
  const g2 = h('<div class="grid g2"></div>'); root.appendChild(g2);
  const pub = add(g2, 'Información pública verificable (contexto)', 'Se usa sólo como referencia; no se mezcla con los datos sintéticos');
  pub.innerHTML = `<ul class="list">${d.contexto_publico.map(x => `<li>${esc(x.dato)} <span class="muted">— ${esc(x.fuente)}</span></li>`).join('')}</ul>`;
  const dirc = add(g2, 'Directorio público de complejos (SIC)', `${fmt.int(dir.length)} complejos de la cadena registrados por entidad federativa · fuente verificable conservada del proyecto original`);
  const counts = {};
  dir.forEach(c => { const s = c.state === 'México' ? 'Estado de México' : c.state; counts[s] = (counts[s] || 0) + 1; });
  const topS = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10);
  dirc.innerHTML = '<div id="dir-chart"></div><div id="dir-table" style="margin-top:10px"></div>';
  barChart(dirc.querySelector('#dir-chart'), { horizontal: true, valueLabels: true, labels: topS.map(x => x[0]), yFormat: fmt.int, series: [{ name: 'Complejos', values: topS.map(x => x[1]) }] });
  dataTable(dirc.querySelector('#dir-table'), { pageSize: 8, rows: dir.map(c => ({ ...c, state: c.state === 'México' ? 'Estado de México' : c.state })), columns: [
    { key: 'name', label: 'Complejo' }, { key: 'city', label: 'Municipio' }, { key: 'state', label: 'Entidad' }, { key: 'screens', label: 'Pantallas', num: true, format: fmt.int }] });
}

// ================================================================ ETL
export async function viewETL(root, stale) {
  const ph = h('<div></div>'); root.appendChild(ph); loading(ph);
  const d = await api('/api/etl');
  if (stale()) return;
  ph.remove();
  root.appendChild(h(`<div class="intro"><b>Extract:</b> detecta archivos nuevos o modificados por checksum MD5 y los copia al <i>staging</i>. <b>Transform:</b> elimina duplicados, valida fechas, horas, claves y cantidades, normaliza canales y SKU, unifica formatos de fecha, imputa precios faltantes y calcula ingresos, descuentos, costos, márgenes y ocupación. <b>Load:</b> inserta en el Data Warehouse con integridad referencial; cada mes se reemplaza completo (borrar e insertar), por lo que repetir la carga no duplica datos. Después se actualizan los data marts y, si hubo cambios, se reentrena el modelo.</div>`));
  const ctl = add(root, 'Ejecutar procesos', `Meses disponibles en las fuentes: ${d.meses_fuente[0]} a ${d.meses_fuente[d.meses_fuente.length - 1]} (${d.meses_fuente.length})`);
  ctl.innerHTML = `<div class="actions">
      <button class="btn primary" data-act="incremental" type="button">Ejecutar carga incremental</button>
      <button class="btn" data-act="completa" type="button">Reconstruir el DW completo (~1 min)</button>
      <button class="btn" data-act="nuevo" type="button" ${d.siguiente_mes ? '' : 'disabled'}>Simular nueva extracción: ${d.siguiente_mes || 'límite alcanzado'}</button></div>
    <p class="muted" style="font-size:12.5px">«Simular nueva extracción» genera las exportaciones del siguiente mes (datos sintéticos de ${d.siguiente_mes || '—'}), ejecuta la carga incremental y reentrena el modelo; demuestra la actualización incremental del almacén.</p>
    <div class="task-box" id="etl-task" style="display:${d.tarea.activo ? 'block' : 'none'}"></div>`;
  const box = ctl.querySelector('#etl-task');
  const showTask = t => { box.style.display = 'block'; box.innerHTML = `<b>${esc(t.tipo || '')}</b> · ${esc(t.mensaje)}${t.error ? ` <span class="tag bad">${esc(t.error)}</span>` : ''}<div class="progress"><i style="width:${t.pct}%"></i></div>`; };
  const watch = async () => {
    ctl.querySelectorAll('button').forEach(b => b.disabled = true);
    const t = await pollTask(showTask);
    if (!t.error) {
      const r = t.resultado || {};
      const e = r.etl || {};
      box.innerHTML = `<span class="tag ${e.estado === 'EXITOSO' ? 'good' : 'blue'}">${esc(e.estado || 'Terminado')}</span> ${esc(e.mensaje || '')} ${r.modelo ? ` · Modelo reentrenado: ${esc(r.modelo.algoritmo)}` : ''} · ${e.duracion_seg ?? ''} s`;
      window.dispatchEvent(new Event('cine:meta-refresh'));
      setTimeout(() => { if (!stale()) { root.innerHTML = ''; viewETL(root, stale); } }, 2500);
    } else ctl.querySelectorAll('button').forEach(b => b.disabled = false);
  };
  ctl.querySelectorAll('button[data-act]').forEach(b => b.addEventListener('click', async () => {
    const act = b.dataset.act;
    if (act === 'completa' && !confirm('Se eliminarán y reconstruirán todas las tablas del Data Warehouse a partir de las fuentes. ¿Continuar?')) return;
    try {
      if (act === 'nuevo') await api('/api/etl/nuevo-mes', { method: 'POST' });
      else await api('/api/etl/ejecutar', { method: 'POST', body: JSON.stringify({ modo: act }) });
      watch();
    } catch (err) { showTask({ tipo: 'Error', mensaje: err.message, pct: 0 }); }
  }));
  if (d.tarea.activo) watch();

  const log = add(root, 'Bitácora de ejecuciones ETL', 'Haz clic en una ejecución para ver el detalle por fuente y los registros rechazados');
  const det = add(root, 'Detalle de la ejecución', '');
  const showRun = async r => {
    det.parentElement.querySelector('h3').textContent = `Detalle de la ejecución #${r.run_id} · ${r.modo} · ${r.estado}`;
    const detalle = r.detalle ? JSON.parse(r.detalle) : {};
    const rows = Object.entries(detalle).map(([fuente, v]) => ({ fuente, ...v }));
    const motivos = d.rechazos_resumen.filter(x => x.run_id === r.run_id);
    det.innerHTML = `<p style="margin-top:0">${esc(r.mensaje || '')}</p><div class="grid g2"><div id="det-src"></div><div id="det-rej"></div></div><div id="det-sample" style="margin-top:12px"></div>`;
    dataTable(det.querySelector('#det-src'), { search: false, rows, columns: [
      { key: 'fuente', label: 'Fuente' }, { key: 'extraidos', label: 'Extraídos', num: true, format: fmt.int }, { key: 'transformados', label: 'Transformados', num: true, format: fmt.int },
      { key: 'cargados', label: 'Cargados', num: true, format: fmt.int }, { key: 'rechazados', label: 'Rechazados', num: true, format: fmt.int }, { key: 'corregidos', label: 'Corregidos', num: true, format: fmt.int }] });
    const rj = det.querySelector('#det-rej');
    if (!motivos.length) rj.innerHTML = '<p class="muted">Sin registros rechazados en esta ejecución.</p>';
    else dataTable(rj, { search: false, rows: motivos, onRow: async m => {
      const s = await api(`/api/etl/rechazos/${r.run_id}?motivo=${encodeURIComponent(m.motivo)}&limite=15`);
      det.querySelector('#det-sample').innerHTML = `<b>Muestra de registros rechazados · ${esc(m.motivo)}</b><pre class="json">${esc(s.map(x => x.archivo + '  ' + x.registro).join('\n'))}</pre>`;
    }, columns: [{ key: 'fuente', label: 'Fuente' }, { key: 'motivo', label: 'Motivo del rechazo (clic = ver muestra)' }, { key: 'n', label: 'Registros', num: true, format: fmt.int }] });
  };
  dataTable(log, { search: false, rows: d.ejecuciones, pageSize: 10, onRow: showRun, columns: [
    { key: 'run_id', label: '#', num: true }, { key: 'inicio', label: 'Fecha de ejecución', format: v => v?.replace('T', ' ') },
    { key: 'modo', label: 'Modo' }, { key: 'estado', label: 'Estado', render: r => `<span class="tag ${r.estado === 'EXITOSO' ? 'good' : r.estado === 'ERROR' ? 'bad' : 'blue'}">${esc(r.estado)}</span>` },
    { key: 'archivos_procesados', label: 'Archivos', num: true, format: fmt.int }, { key: 'extraidos', label: 'Extraídos', num: true, format: fmt.int },
    { key: 'transformados', label: 'Transformados', num: true, format: fmt.int }, { key: 'cargados', label: 'Cargados', num: true, format: fmt.int },
    { key: 'rechazados', label: 'Rechazados', num: true, format: fmt.int }, { key: 'corregidos', label: 'Corregidos', num: true, format: fmt.int },
    { key: 'duracion_seg', label: 'Tiempo (s)', num: true, format: fmt.dec }] });
  const firstOk = d.ejecuciones.find(r => r.estado === 'EXITOSO') || d.ejecuciones[0];
  if (firstOk) showRun(firstOk);
  dataTable(add(root, 'Control de archivos cargados', 'Checksum MD5 de cada archivo de origen; base de la carga incremental'), { rows: d.archivos, pageSize: 10, columns: [
    { key: 'archivo', label: 'Archivo', render: r => `<code>${esc(r.archivo)}</code>` }, { key: 'filas', label: 'Filas', num: true, format: fmt.int },
    { key: 'checksum', label: 'MD5', render: r => `<code class="muted">${esc(r.checksum.slice(0, 12))}…</code>` }, { key: 'run_id', label: 'Ejecución', num: true },
    { key: 'cargado_en', label: 'Cargado en', format: v => v?.replace('T', ' ') }] });
}
