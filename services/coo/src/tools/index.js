// index.js — ทะเบียนเครื่องมือกลาง (tool registry)
//
// รวมเครื่องมือทั้งหมดเข้าเป็นทะเบียนเดียว ให้ agent loop และ Manus เรียกใช้ได้
// พร้อม export JSON schema แบบ OpenAI/Manus function-calling
import pipeline from './pipeline.js';
import documents from './documents.js';
import announcements from './announcements.js';
import brief from './brief.js';
import logger from '../utils/logger.js';

const modules = [pipeline, documents, announcements, brief];

// รวมทุก tool: { name -> { description, parameters, handler } }
export const registry = {};
for (const m of modules) {
  for (const [name, def] of Object.entries(m.tools || {})) {
    if (registry[name]) throw new Error(`เครื่องมือชื่อซ้ำ: ${name}`);
    registry[name] = def;
  }
}

export function listTools() {
  return Object.entries(registry).map(([name, def]) => ({
    name,
    description: def.description,
    parameters: def.parameters,
  }));
}

// รูปแบบ tools สำหรับ LLM (OpenAI/Manus function-calling schema)
export function toolSchemas() {
  return listTools().map((t) => ({
    type: 'function',
    function: { name: t.name, description: t.description, parameters: t.parameters },
  }));
}

// เรียกใช้เครื่องมือหนึ่งตัว คืนผลลัพธ์แบบมาตรฐาน { ok, tool, result | error }
export async function callTool(name, args = {}) {
  const def = registry[name];
  if (!def) {
    return { ok: false, tool: name, error: `ไม่พบเครื่องมือชื่อ "${name}"` };
  }
  try {
    const result = await def.handler(args || {});
    return { ok: true, tool: name, result };
  } catch (err) {
    logger.error('tools', `เรียก ${name} ล้มเหลว: ${err.message}`);
    return { ok: false, tool: name, error: err.message, code: err.code };
  }
}

export default { registry, listTools, toolSchemas, callTool };
