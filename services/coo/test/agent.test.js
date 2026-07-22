import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import store from '../src/data/store.js';
import { runAgent } from '../src/agent/agentLoop.js';
import { buildBrief } from '../src/tools/brief.js';

beforeEach(() => store.loadSeedOnly());

test('runAgent (mock) เดินครบ playbook และสร้าง brief', async () => {
  const r = await runAgent({ provider: 'mock' });
  assert.equal(r.provider, 'mock');
  assert.ok(r.actions.length >= 4, 'ต้องมี action อย่างน้อย 4 จาก playbook');
  assert.ok(r.brief.text.includes('COO Operational Brief'));
  assert.ok(Array.isArray(r.brief.systemsCheck));
  assert.ok(Array.isArray(r.brief.actionsTaken));
});

test('buildBrief สร้าง blocker เมื่อมีบัญชีค้างเกิน 14 วัน', () => {
  const snap = { overdue: [{ id: 'LN-9', overdueDays: 30 }] };
  const b = buildBrief({ actions: [], pipelineSnapshot: snap });
  assert.ok(b.blockers.length >= 1);
  assert.match(b.blockers[0].issue, /14 วัน/);
});

test('buildBrief ที่ไม่มี action ยังได้โครง 3 ส่วน', () => {
  const b = buildBrief({ actions: [] });
  assert.ok(b.systemsCheck.length >= 1);
  assert.ok(b.actionsTaken.length >= 1);
  assert.equal(b.blockers.length, 0);
  assert.ok(b.text.includes('Systems Check'));
  assert.ok(b.text.includes('Action Taken'));
  assert.ok(b.text.includes('Blockers'));
});

test('agent ที่ล้มเหลวใน tool กลายเป็น blocker', () => {
  const b = buildBrief({ actions: [{ tool: 'document_generate', ok: false, error: 'boom' }] });
  assert.ok(b.blockers.some((x) => x.issue.includes('boom')));
});
