export function studentStatus(s) {
  if (s.excused) return 'Exonerado';
  if (s.submitted_at || ['submitted', 'graded'].includes(s.workflow_state) && s.submission_type != null && s.submission_type !== 'none') return 'Entregado';
  return s.score != null ? 'Sin entrega / nota previa' : 'Sin entrega';
}
export function assertManifest(m) {
  if (!m || typeof m !== 'object' || !Array.isArray(m.submissions) || !m.course_id || !m.assignment_id) throw Error('El paquete no contiene un manifiesto válido de Canvas.');
  const base = new URL(m.canvas_base);
  if (base.protocol !== 'https:' || base.username || base.password || base.port || base.pathname !== '/' || base.search || base.hash) throw Error('El servidor Canvas del paquete debe ser un origen HTTPS válido.');
  if (!/^\d+$/.test(String(m.course_id)) || !/^\d+$/.test(String(m.assignment_id))) throw Error('Identificadores de tarea inválidos.');
  if (m.submissions.some(s => !s || typeof s !== 'object' || !s.user_id)) throw Error('Hay estudiantes con registros inválidos.');
  if (m.rubric != null && (!Array.isArray(m.rubric) || m.rubric.some(r => !r || r.id == null))) throw Error('La rúbrica del paquete es inválida.');
}
export function makeTemplate(m) {
  assertManifest(m);
  if (!m.rubric?.length) throw Error('La tarea no tiene rúbrica.');
  return { schema_version: 2, canvas_base: m.canvas_base, course_id: m.course_id, assignment_id: m.assignment_id, assignment_title: m.assignment_title, grades: m.submissions.filter(s => studentStatus(s) === 'Entregado' && s.score == null).map(s => ({ user_id: s.user_id, student_name: s.student_name, total: null, comment: '', criteria: m.rubric.map(r => ({ criterion_id: r.id, points: null, rating_id: null, comment: '' })) })) };
}
