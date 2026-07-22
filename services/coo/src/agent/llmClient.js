// llmClient.js — อะแดปเตอร์เชื่อม LLM แบบ pluggable
//
// รองรับ 2 provider:
//   • "manus" — ยิงไปที่ endpoint แบบ OpenAI Chat Completions (Manus/OpenRouter/ฯลฯ)
//   • "mock"  — ตัววางแผนภายในแบบ deterministic ทำให้ระบบเป็น autonomous ทันที
//              โดยไม่ต้องมี API key (เดินตาม operational playbook)
import config from '../config.js';
import logger from '../utils/logger.js';

// ── โครงสร้างคำตอบมาตรฐานที่ agent loop เข้าใจ ──
// { content: string, toolCalls: [{ id, name, arguments }] }

// ─────────────────────────────────────────────────────────────
// Manus / OpenAI-compatible provider
// ─────────────────────────────────────────────────────────────
async function manusChat({ messages, tools }) {
  if (!config.llm.apiKey) {
    throw new Error('ไม่ได้ตั้ง MANUS_API_KEY — ตั้งค่าใน .env หรือใช้ LLM_PROVIDER=mock');
  }
  const body = {
    model: config.llm.model,
    messages,
    tools,
    tool_choice: 'auto',
    temperature: 0.2,
  };
  const res = await fetch(config.llm.apiUrl, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${config.llm.apiKey}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const t = await res.text().catch(() => '');
    throw new Error(`Manus API error ${res.status}: ${t.slice(0, 300)}`);
  }
  const data = await res.json();
  const msg = data.choices?.[0]?.message || {};
  const toolCalls = (msg.tool_calls || []).map((tc) => ({
    id: tc.id,
    name: tc.function?.name,
    arguments: safeParse(tc.function?.arguments),
  }));
  return { content: msg.content || '', toolCalls, raw: data };
}

function safeParse(s) {
  if (!s) return {};
  if (typeof s === 'object') return s;
  try {
    return JSON.parse(s);
  } catch {
    return {};
  }
}

// ─────────────────────────────────────────────────────────────
// Mock provider — ตัววางแผนภายในแบบ deterministic
// เดินตาม playbook: ตรวจ pipeline → สร้างเอกสาร → ทวงยอดค้าง → ส่งประกาศ → จบ
// ตัดสินขั้นถัดไปจากจำนวน tool result ที่มีอยู่ใน messages แล้ว
// ─────────────────────────────────────────────────────────────
const PLAYBOOK = [
  { name: 'pipeline_check', arguments: {} },
  { name: 'document_generate', arguments: {} },
  { name: 'pipeline_send_reminder', arguments: { minOverdueDays: 1 } },
  { name: 'announcement_dispatch', arguments: {} },
];

async function mockChat({ messages }) {
  const executed = messages.filter((m) => m.role === 'tool').length;
  if (executed < PLAYBOOK.length) {
    const step = PLAYBOOK[executed];
    return {
      content: '',
      toolCalls: [{ id: `mock-${executed}`, name: step.name, arguments: step.arguments }],
    };
  }
  // จบ playbook — ไม่มี tool call เพิ่ม ให้ loop ไปสร้าง brief
  return { content: 'ดำเนินการตาม playbook ครบแล้ว พร้อมสรุป COO Operational Brief', toolCalls: [] };
}

// ─────────────────────────────────────────────────────────────
export function getClient(provider = config.llm.provider) {
  if (provider === 'manus') {
    logger.debug('llm', `ใช้ provider: manus (${config.llm.apiUrl})`);
    return { chat: manusChat, provider: 'manus' };
  }
  logger.debug('llm', 'ใช้ provider: mock (internal planner)');
  return { chat: mockChat, provider: 'mock' };
}

export default { getClient };
