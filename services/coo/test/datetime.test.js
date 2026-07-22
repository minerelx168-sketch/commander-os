import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  parseStrict, assertNotPast, daysBetween, daysOverdue, addDays,
  toISODate, formatThai, DateValidationError,
} from '../src/utils/datetime.js';

test('parseStrict รับ ISO date และ datetime', () => {
  assert.equal(toISODate(parseStrict('2026-07-21')), '2026-07-21');
  assert.equal(toISODate(parseStrict('2026-07-21T10:30:00Z')), '2026-07-21');
});

test('parseStrict ปฏิเสธรูปแบบผิด', () => {
  assert.throws(() => parseStrict('21/07/2026'), DateValidationError);
  assert.throws(() => parseStrict('not-a-date'), DateValidationError);
  assert.throws(() => parseStrict(12345), DateValidationError);
});

test('parseStrict ปฏิเสธวันที่ไม่มีจริง (roll-over)', () => {
  assert.throws(() => parseStrict('2026-02-30'), DateValidationError);
  assert.throws(() => parseStrict('2026-13-01'), DateValidationError);
});

test('assertNotPast ปฏิเสธอดีต ยอมรับวันนี้/อนาคต', () => {
  const ref = '2026-07-21';
  assert.throws(() => assertNotPast('2026-07-20', { reference: ref }), DateValidationError);
  assert.doesNotThrow(() => assertNotPast('2026-07-21', { reference: ref }));
  assert.doesNotThrow(() => assertNotPast('2026-08-01', { reference: ref }));
});

test('daysBetween และ daysOverdue คำนวณถูก', () => {
  assert.equal(daysBetween('2026-07-01', '2026-07-21'), 20);
  assert.equal(daysBetween('2026-07-21', '2026-07-01'), -20);
  assert.equal(daysOverdue('2026-07-05', '2026-07-21'), 16);
});

test('addDays ทำงานข้ามเดือนถูก', () => {
  assert.equal(toISODate(addDays('2026-07-30', 5)), '2026-08-04');
});

test('formatThai แสดงพุทธศักราช', () => {
  assert.equal(formatThai('2026-07-21'), '21 กรกฎาคม 2569');
});
