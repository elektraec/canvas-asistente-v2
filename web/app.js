import { studentStatus, makeTemplate, assertManifest } from './core.js';
const $ = id => document.getElementById(id);
let manifest = null, grades = null, ticket = null, report = null, demo = false, busy = false;
const log = message => { $('log').textContent += `\n${new Date().toLocaleTimeString('es-EC')} · ${message}`; };
function notify(message, error = false) { $('notice').textContent = message; $('notice').hidden = false; $('notice').classList.toggle('error', error); log(message); }
function invalidate() { ticket = null; $('register').disabled = true; $('validation-status').textContent = 'Valida contra Canvas antes de registrar.'; }
function saveBlob(blob, name) { const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
function saveJSON(value, name) { saveBlob(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }), name); }
async function action(fn) { if (busy) return; busy = true; document.body.setAttribute('aria-busy', 'true'); document.querySelectorAll('.connection-actions button').forEach(b => b.disabled = true); try { await fn(); } catch (e) { notify(e.message || 'No se pudo completar la operación.', true); } finally { busy = false; document.body.removeAttribute('aria-busy'); document.querySelectorAll('.connection-actions button').forEach(b => b.disabled = false); $('register').disabled = !ticket; $('report').disabled = !report; } }
function cell(tr, value) { const td = tr.insertCell(); td.textContent = value ?? '—'; return td; }
function render() {
  const rows = manifest?.submissions || [], filter = $('status-filter').value, search = $('search').value.trim().toLocaleLowerCase();
  const counts = { all: rows.length, submitted: 0, missing: 0, graded: 0 };
  rows.forEach(s => { if (studentStatus(s) === 'Entregado') counts.submitted++; else if (!s.excused) counts.missing++; if (s.score != null) counts.graded++; });
  for (const [key, value] of Object.entries(counts)) $(`count-${key}`).textContent = manifest ? value : '—';
  $('assignment-title').textContent = manifest?.assignment_title || 'Entregas de la tarea';
  $('assignment-meta').textContent = manifest ? `${demo ? 'EJEMPLO FICTICIO · ' : ''}Curso ${manifest.course_id} · Tarea ${manifest.assignment_id} · ${rows.length} registros` : 'Abre un ZIP para comenzar a trabajar.';
  $('rubric-count').textContent = manifest ? `${manifest.rubric?.length || 0} criterios de rúbrica` : 'Sin rúbrica cargada';
  $('template').disabled = !manifest?.rubric?.length;
  const visible = rows.filter(s => {
    const match = `${s.student_name} ${s.user_id}`.toLocaleLowerCase().includes(search);
    return match && (filter === 'all' || filter === 'submitted' && studentStatus(s) === 'Entregado' || filter === 'missing' && !s.excused && studentStatus(s) !== 'Entregado' || filter === 'graded' && s.score != null || filter === 'excused' && s.excused);
  });
  $('submissions').replaceChildren();
  visible.forEach(s => {
    const tr = document.createElement('tr'), nameCell = tr.insertCell(), wrap = document.createElement('div'), avatar = document.createElement('span'), name = document.createElement('span');
    wrap.className = 'student-name'; avatar.className = 'avatar'; avatar.textContent = String(s.student_name || '?').split(/\s+/).map(x => x[0]).slice(0, 2).join('').toUpperCase(); name.textContent = s.student_name || `Estudiante ${s.user_id}`; wrap.append(avatar, name); nameCell.append(wrap);
    cell(tr, s.user_id); const badge = document.createElement('span'); badge.textContent = studentStatus(s); badge.className = `status ${s.score != null ? 'graded' : studentStatus(s) === 'Entregado' ? 'submitted' : ''}`; tr.insertCell().append(badge); cell(tr, s.score); cell(tr, s.attachments?.length || 0); $('submissions').append(tr);
  });
  $('visible-count').textContent = `${visible.length} estudiantes`;
  $('empty').hidden = visible.length > 0;
  if (manifest && !visible.length) { $('empty').querySelector('h3').textContent = rows.length ? 'No hay coincidencias' : 'Este paquete no contiene estudiantes'; $('empty').querySelector('p').textContent = rows.length ? 'Prueba otro nombre o cambia el filtro de estado.' : 'Consulta los registros de la tarea en Canvas.'; }
}
function displayGrades(rows = [], zeros = []) { $('grade-rows').replaceChildren(); for (const [list, operation] of [[rows, 'Registrar rúbrica'], [zeros, 'Cero por no entrega']]) list.forEach(r => { const tr = document.createElement('tr'); [r.student_name || r.user?.name, r.user_id, operation.startsWith('Cero') ? 0 : r.total, operation].forEach(v => cell(tr, v)); $('grade-rows').append(tr); }); }
function showView(id) { document.querySelectorAll('.view').forEach(v => v.hidden = v.id !== id); document.querySelectorAll('.nav').forEach(b => b.classList.toggle('active', b.dataset.view === id)); $('breadcrumb').textContent = { deliveries: 'Entregas', grades: 'Evaluaciones', guide: 'Guía de uso' }[id]; }
document.querySelectorAll('[data-view]').forEach(b => b.onclick = () => showView(b.dataset.view));
$('search').oninput = render; $('status-filter').onchange = render;
for (const id of ['assignment-url', 'canvas-token', 'bridge-url', 'bridge-key', 'include-zeros']) $(id).addEventListener('input', invalidate);
function loadManifest(data, example = false) { assertManifest(data); manifest = data; demo = example; invalidate(); render(); $('assignment-url').value = `${data.canvas_base}/courses/${data.course_id}/assignments/${data.assignment_id}`; showView('deliveries'); }
$('open-zip').onclick = () => $('zip-file').click();
$('zip-file').onchange = () => action(async () => {
  const file = $('zip-file').files[0]; if (!file) return;
  if (file.size > 300 * 1024 * 1024) throw Error('Este ZIP supera 300 MB. Ábrelo con la aplicación de escritorio.');
  if (!globalThis.JSZip) throw Error('No se cargó el lector ZIP. Recarga la página.');
  const zip = await JSZip.loadAsync(file); const entry = zip.file('resumen_entregas.json');
  if (!entry) throw Error('El ZIP no contiene resumen_entregas.json de Asistente Canvas.');
  // Limit inflated manifest size before parsing untrusted packages.
  if (entry._data?.uncompressedSize > 20 * 1024 * 1024) throw Error('El resumen del ZIP es demasiado grande.');
  loadManifest(JSON.parse(await entry.async('string'))); notify(`Paquete abierto: ${file.name}. ${manifest.warnings?.length || 0} advertencias de descarga.`); $('zip-file').value = '';
});
$('template').onclick = () => action(async () => { if (!manifest) throw Error('Primero abre un paquete.'); saveJSON(makeTemplate(manifest), `plantilla_calificaciones_${manifest.assignment_id}${demo ? '_EJEMPLO' : ''}.json`); notify('Plantilla creada con los IDs de la rúbrica. Los puntajes están vacíos: completa y revisa la evaluación antes de importarla.'); });
$('open-grades').onclick = () => $('grades-file').click();
$('grades-file').onchange = () => action(async () => { const file = $('grades-file').files[0]; if (!file) return; if (file.size > 20 * 1024 * 1024) throw Error('El JSON supera 20 MB.'); const data = JSON.parse(await file.text()); if (data?.schema_version !== 2 || !Array.isArray(data.grades) || data.grades.some(r => !r || typeof r !== 'object')) throw Error('El archivo debe ser un JSON de evaluaciones con schema_version 2 y una lista grades.'); grades = data; invalidate(); displayGrades(grades.grades); notify(`${grades.grades.length} evaluaciones importadas. Falta validarlas contra Canvas.`); $('grades-file').value = ''; });
function connection() { const base = new URL($('bridge-url').value); if (!['127.0.0.1', 'localhost'].includes(base.hostname) || base.protocol !== 'http:' || base.username || base.password) throw Error('El servidor debe ser HTTP local (127.0.0.1 o localhost).'); if (!$('bridge-key').value) { $('connector').open = true; throw Error('Ejecuta python web_server.py y conecta la clave de sesión en «servidor local».'); } return base.origin; }
async function api(path, extra = {}, binary = false) { const base = connection(); let res; try { res = await fetch(`${base}/api/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Bridge-Key': $('bridge-key').value }, body: JSON.stringify({ url: $('assignment-url').value.trim(), token: $('canvas-token').value.trim(), ...extra }), credentials: 'omit', redirect: 'error' }); } catch { throw Error('No se pudo conectar al servidor local. Comprueba que está ejecutándose y permite el acceso a la red local en el navegador.'); } if (!res.ok) { const e = await res.json().catch(() => ({})); throw Error(e.error || `Error del servidor (${res.status}).`); } return binary ? res.blob() : res.json(); }
$('download').onclick = () => action(async () => { notify('Consultando Canvas y descargando evidencias…'); const blob = await api('export', {}, true); const zip = await JSZip.loadAsync(blob); loadManifest(JSON.parse(await zip.file('resumen_entregas.json').async('string'))); saveBlob(blob, `canvas_tarea_${manifest.assignment_id}.zip`); notify(`ZIP descargado. Advertencias: ${manifest.warnings?.length || 0}.`); });
$('validate').onclick = () => action(async () => { invalidate(); if (demo) throw Error('El ejemplo es ficticio. Abre un paquete real antes de conectar con Canvas.'); if (!grades && !$('include-zeros').checked) throw Error('Abre un JSON aprobado o selecciona ceros para faltantes.'); const r = await api('validate', { grades, include_zeros: $('include-zeros').checked }); displayGrades(r.rows, r.zeros); ticket = r.ticket; $('validation-status').textContent = `${r.rows.length} evaluaciones · ${r.zeros.length} ceros propuestos · ${r.errors.length} errores`; notify([...r.errors, ...r.warnings, r.ticket ? 'Validación completada. Revisa la vista previa antes de registrar.' : 'Registro bloqueado: revisa los errores o la ausencia de filas elegibles.'].join('\n'), r.errors.length > 0); });
$('register').onclick = () => { if (!ticket || busy) return; $('confirm-count').textContent = `${$('grade-rows').rows.length} calificaciones. Verifica también la política de publicación configurada en Canvas.`; $('reviewed').checked = false; $('confirmation').value = ''; $('confirm-submit').disabled = true; $('confirm-dialog').showModal(); };
for (const id of ['reviewed', 'confirmation']) $(id).oninput = () => $('confirm-submit').disabled = !$('reviewed').checked || $('confirmation').value !== 'REGISTRAR';
$('confirm-dialog').addEventListener('close', () => { if ($('confirm-dialog').returnValue !== 'register' || !$('reviewed').checked || $('confirmation').value !== 'REGISTRAR') return; const approved = ticket; invalidate(); action(async () => { notify('Registrando y verificando cada evaluación…'); report = await api('register', { ticket: approved, confirmation: 'REGISTRAR' }); displayGrades([]); notify(report.results.map(r => `${r.user_id}: ${r.status} ${r.detail || ''}`).join('\n') || 'No se registraron cambios.'); saveJSON(report, `reporte_canvas_${Date.now()}.json`); }); });
$('report').onclick = () => { if (report) saveJSON(report, `reporte_canvas_${Date.now()}.json`); };
$('demo').onclick = () => { grades = null; report = null; $('report').disabled = true; displayGrades([]); loadManifest({ schema_version: 2, canvas_base: 'https://canvas.example.edu', course_id: 101, assignment_id: 204, assignment_title: 'Proyecto final · Diseño de una solución', max_points: 10, rubric: [{ id: 'ejemplo_c1', points: 6, description: 'Análisis y propuesta', ratings: [] }, { id: 'ejemplo_c2', points: 4, description: 'Presentación de evidencias', ratings: [] }], submissions: [ ['Sofía Andrade', 'submitted', null], ['Mateo Benítez', 'submitted', 9], ['Valentina Castro', 'unsubmitted', null], ['Lucas Delgado', 'submitted', null], ['Camila Espinosa', 'submitted', 8.5], ['Daniel Flores', 'unsubmitted', null] ].map(([name, state, score], i) => ({ user_id: 1001 + i, student_name: name, workflow_state: state, submission_type: state === 'submitted' ? 'online_upload' : null, score, attachments: state === 'submitted' ? [{ name: 'evidencia.pdf' }] : [] })), warnings: [] }, true); notify('Modo de ejemplo: todos los nombres, IDs y resultados son ficticios. No se conectará con Canvas.'); };
if (['127.0.0.1', 'localhost'].includes(location.hostname)) { $('bridge-url').value = location.origin; fetch('/api/session', { credentials: 'omit' }).then(r => r.ok ? r.json() : null).then(data => { if (data?.key) { $('bridge-key').value = data.key; log('Servidor local conectado.'); } }).catch(() => {}); }
render();
