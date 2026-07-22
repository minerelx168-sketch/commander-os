// agentLoop.js — วงจรการทำงานอัตโนมัติของ COO Command
//
// รับ directive (หรือรันตามกำหนดเวลา) → คุยกับ LLM (Manus/mock) →
// เรียกเครื่องมือจริง → ป้อนผลกลับ → วนจนเสร็จ → สร้าง COO Operational Brief
import config from '../config.js';
import logger from '../utils/logger.js';
import { SYSTEM_PROMPT } from './systemPrompt.js';
import { getClient } from './llmClient.js';
import { toolSchemas, callTool } from '../tools/index.js';
import { buildBrief } from '../tools/brief.js';
import { checkPipeline } from '../tools/pipeline.js';

const DEFAULT_DIRECTIVE =
  'รันรอบปฏิบัติการประจำ: ตรวจ pipeline, สร้างเอกสารที่ค้าง, ทวงยอดค้างชำระ, ' +
  'ส่งประกาศที่ถึงกำหนด แล้วสรุปเป็น COO Operational Brief';

export async function runAgent({ directive = DEFAULT_DIRECTIVE, provider, maxSteps } = {}) {
  const client = getClient(provider);
  const limit = maxSteps || config.llm.maxSteps;
  const tools = toolSchemas();

  const messages = [
    { role: 'system', content: SYSTEM_PROMPT },
    { role: 'user', content: directive },
  ];

  const actions = []; // บันทึกงานที่ลงมือทำจริงในรอบนี้ (ใช้สร้าง brief)
  let steps = 0;

  logger.info('agent', `เริ่มรอบทำงาน [provider=${client.provider}] directive="${directive}"`);

  while (steps < limit) {
    steps += 1;
    let reply;
    try {
      reply = await client.chat({ messages, tools });
    } catch (err) {
      logger.error('agent', `LLM ล้มเหลว: ${err.message}`);
      actions.push({ tool: 'llm', ok: false, error: err.message, needsApproval: false });
      break;
    }

    // ไม่มี tool call = LLM คิดว่าเสร็จแล้ว
    if (!reply.toolCalls || reply.toolCalls.length === 0) {
      if (reply.content) messages.push({ role: 'assistant', content: reply.content });
      logger.info('agent', `LLM จบรอบที่ step ${steps}`);
      break;
    }

    // บันทึก assistant turn ที่มี tool_calls
    messages.push({
      role: 'assistant',
      content: reply.content || '',
      tool_calls: reply.toolCalls.map((tc) => ({
        id: tc.id,
        type: 'function',
        function: { name: tc.name, arguments: JSON.stringify(tc.arguments || {}) },
      })),
    });

    // เรียกเครื่องมือทีละตัว แล้วป้อนผลกลับ
    for (const tc of reply.toolCalls) {
      const outcome = await callTool(tc.name, tc.arguments);
      actions.push({
        tool: tc.name,
        ok: outcome.ok,
        result: outcome.result,
        error: outcome.error,
        summary: outcome.ok ? outcome.result?.message : outcome.error,
      });
      messages.push({
        role: 'tool',
        tool_call_id: tc.id,
        name: tc.name,
        content: JSON.stringify(outcome.ok ? outcome.result : { error: outcome.error }),
      });
    }
  }

  // สร้าง COO Operational Brief จากงานที่ทำจริง + snapshot pipeline ปัจจุบัน
  let pipelineSnapshot = null;
  try {
    pipelineSnapshot = checkPipeline();
  } catch (err) {
    logger.warn('agent', `ทำ snapshot pipeline ไม่ได้: ${err.message}`);
  }
  const brief = buildBrief({ actions, pipelineSnapshot });

  logger.info('agent', `จบรอบทำงาน: ${actions.length} action, ${brief.blockers.length} blocker`);

  return {
    provider: client.provider,
    directive,
    steps,
    actions,
    brief,
    messages,
  };
}

export default { runAgent };
