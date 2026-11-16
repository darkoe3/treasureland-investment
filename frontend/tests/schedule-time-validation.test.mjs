import assert from 'node:assert/strict';
import test from 'node:test';
import { emptyScheduleForm, validateScheduleForm } from '../lib/game-schedule-operations.js';

test('time validation compares mixed precision clock values and rejects invalid clocks', () => {
  assert.equal(emptyScheduleForm().weekday, '');
  const form = { ...emptyScheduleForm(), game: '1', closing_time: '12:30', draw_time: '12:30:00' };
  assert.match(validateScheduleForm(form), /weekday/);
  const scheduled = { ...form, weekday: '1' };
  assert.match(validateScheduleForm(scheduled), /later/);
  assert.equal(validateScheduleForm({ ...scheduled, draw_time: '12:30:01' }), '');
  for (const closing_time of ['24:00', '12:60', 'bad', '12:00Z', '12:00+01:00']) {
    assert.match(validateScheduleForm({ ...scheduled, closing_time }), /valid/);
  }
  assert.match(validateScheduleForm({ ...scheduled, closing_time: '', draw_time: '' }), /require both/);
  assert.equal(validateScheduleForm({ ...scheduled, is_whole_day: true, closing_time: '', draw_time: '' }), '');
});
