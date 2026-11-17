import test from 'node:test';
import assert from 'node:assert/strict';
import { makeTemplate, studentStatus, assertManifest } from '../web/core.js';
const manifest = { canvas_base: 'https://canvas.example.edu', course_id: 1, assignment_id: 2,
  rubric: [{ id: 'real-criterion' }], submissions: [
    { user_id: 10, student_name: 'A', workflow_state: 'submitted', submission_type: 'online_upload', score: null },
    { user_id: 11, workflow_state: 'unsubmitted', score: null },
    { user_id: 12, workflow_state: 'graded', submission_type: 'online_text_entry', score: 8 },
    { user_id: 13, workflow_state: 'submitted', submission_type: 'online_upload', excused: true }
  ] };
test('only submitted, ungraded, non-excused students enter a blank template', () => {
  const template = makeTemplate(manifest);
  assert.equal(template.schema_version, 2);
  assert.deepEqual(template.grades.map(r => r.user_id), [10]);
  assert.equal(template.grades[0].total, null);
  assert.deepEqual(template.grades[0].criteria, [{criterion_id: 'real-criterion', points: null, rating_id: null, comment: ''}]);
});
test('status distinguishes graded work, excused and missing with previous score', () => {
  assert.equal(studentStatus(manifest.submissions[2]), 'Entregado');
  assert.equal(studentStatus(manifest.submissions[3]), 'Exonerado');
  assert.equal(studentStatus({ score: 0 }), 'Sin entrega / nota previa');
});
test('reject malformed packages and credential-bearing Canvas origins', () => {
  for (const base of ['http://canvas.example.edu', 'https://token@canvas.example.edu', 'https://canvas.example.edu/path', 'https://canvas.example.edu?token=x']) assert.throws(() => assertManifest({...manifest, canvas_base: base}));
  assert.throws(() => assertManifest({...manifest, submissions: [null]}));
  assert.throws(() => makeTemplate({...manifest, rubric: []}));
});
