import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import store from '../src/data/store.js';
import { checkPipeline, sendReminder, formatTHB } from '../src/tools/pipeline.js';
import { generateDocuments, listDocuments } from '../src/tools/documents.js';
import { scheduleAnnouncement } from '../src/tools/announcements.js';
import { callTool, listTools } from '../src/tools/index.js';

beforeEach(() => store.loadSeedOnly());

test('formatTHB จัดรูปแบบเงินสองตำแหน่ง', () => {
  assert.equal(formatTHB(12500), '12,500.00 บาท');
  assert.throws(() => formatTHB('abc'));
});

test('checkPipeline หาบัญชีเกินกำหนดด้วยวันอ้างอิงคงที่', () => {
  const r = checkPipeline({ reference: '2026-07-21' });
  assert.ok(r.overdueCount >= 3);
  assert.ok(r.totalOverdueAmount > 0);
  // เรียงจากเกินกำหนดมากสุดก่อน
  assert.ok(r.overdue[0].overdueDays >= r.overdue[1].overdueDays);
});

test('generateDocuments สร้างจากคิวและตั้งชื่อไฟล์มาตรฐาน', () => {
  const r = generateDocuments({});
  assert.ok(r.count >= 1);
  assert.match(r.generated[0].filename, /\.pdf$/);
  // สร้างซ้ำต้องไม่มีของ pending เหลือ
  assert.equal(listDocuments().pending.length, 0);
});

test('sendReminder กันส่งซ้ำในวันเดียวกัน', () => {
  const first = sendReminder({ accountId: 'LN-1001' });
  assert.equal(first.count, 1);
  const second = sendReminder({ accountId: 'LN-1001' });
  assert.equal(second.count, 0);
  assert.equal(second.skipped.length, 1);
});

test('scheduleAnnouncement ปฏิเสธวันในอดีต', () => {
  assert.throws(() => scheduleAnnouncement({ title: 'ทดสอบ', scheduledFor: '2020-01-01T08:00:00Z' }));
});

test('callTool คืน error แบบมีโครงสร้างเมื่อไม่พบเครื่องมือ', async () => {
  const r = await callTool('ไม่มีจริง', {});
  assert.equal(r.ok, false);
  assert.match(r.error, /ไม่พบ/);
});

test('listTools ครอบคลุมเครื่องมือหลักครบ', () => {
  const names = listTools().map((t) => t.name);
  for (const n of ['pipeline_check', 'pipeline_send_reminder', 'document_generate', 'announcement_schedule', 'coo_brief']) {
    assert.ok(names.includes(n), `ต้องมี ${n}`);
  }
});
