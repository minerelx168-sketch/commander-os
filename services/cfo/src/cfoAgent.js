// The CFO agent brain. Wraps Claude for (a) the Executive Financial Brief and
// (b) interactive chat. Numbers always come from the deterministic engine and are
// passed to Claude as ground truth; Claude only interprets and prioritises.
// If no API key is present, a deterministic fallback keeps the system fully
// operational (autonomous monitoring never depends on the network).

import Anthropic from '@anthropic-ai/sdk';
import { config, hasClaude } from './config.js';
import { memoryContext } from './memory.js';

const SYSTEM_PROMPT = `คุณคือ "CFO Command" — AI ประธานเจ้าหน้าที่บริหารฝ่ายการเงิน (Chief Financial Officer) ที่ทำงานอัตโนมัติ
บทบาท: เรดาร์ทางการเงินที่ปกป้องสภาพคล่องของทุกโปรเจคธุรกิจ โดยไม่ต้องอาศัยการประชุม

กฎเหล็ก:
- ตัวเลขทุกตัวมาจากข้อมูลจริงที่ให้ไว้เท่านั้น ห้ามคาดเดาหรือแต่งตัวเลขเด็ดขาด หากข้อมูลไม่พอ ให้ระบุว่าขาดข้อมูลอะไร
- ให้ความสำคัญกับ "กระแสเงินสด (Cash Flow)" เป็นอันดับหนึ่ง
- ไม่ต้องอธิบายทฤษฎีการเงิน รายงานเฉพาะผลลัพธ์และข้อเสนอที่นำไปใช้ได้จริง
- กระชับ ตรงประเด็น เหมาะกับผู้บริหารที่มีเวลาจำกัด (async ไม่ประชุม)

รูปแบบรายงาน "CFO Executive Financial Brief" (ใช้หัวข้อเหล่านี้):
[Cash Flow Status] — สถานะเงินสดปัจจุบันและ runway
[P&L Snapshot] — กำไร/ขาดทุนล่าสุดของแต่ละโปรเจค
[Red Flags & Alerts] — เรื่องด่วนที่ต้องตัดสินใจทันที (จัดลำดับความรุนแรง)
[Action Recommendations] — คำแนะนำบริหารเงิน/หมุนกำไรที่ทำได้ทันที`;

function client() {
  return new Anthropic({ apiKey: config.apiKey });
}

// ---- Executive brief ----
export async function generateBrief(analysis) {
  const mem = memoryContext();
  const payload = {
    as_of: analysis.asOf,
    currency: config.currency,
    portfolio: analysis.portfolio,
    projects: analysis.projects,
    memory: mem,
  };

  if (!hasClaude()) {
    return { source: 'fallback', text: fallbackBrief(analysis, mem) };
  }

  const user = `นี่คือผลวิเคราะห์การเงินล่าสุด (ตัวเลขคำนวณมาแล้ว ถือเป็นข้อเท็จจริง):

\`\`\`json
${JSON.stringify(payload, null, 2)}
\`\`\`

จงออก "CFO Executive Financial Brief" ตามรูปแบบที่กำหนด กระชับ ใช้ตัวเลขจากข้อมูลนี้เท่านั้น
- ใน [Red Flags & Alerts] ให้ใช้ข้อมูล alerts ที่คำนวณมา และถ้ามี recurringAlerts ใน memory ให้ระบุว่าเป็นปัญหาที่เกิดซ้ำ
- ถ้ามี recentFeedback จากผู้บริหาร ให้นำมาพิจารณาในคำแนะนำ`;

  try {
    const msg = await client().messages.create({
      model: config.model,
      max_tokens: 2000,
      system: SYSTEM_PROMPT,
      messages: [{ role: 'user', content: user }],
    });
    return { source: 'claude', text: msg.content.map((b) => (b.type === 'text' ? b.text : '')).join('') };
  } catch (err) {
    return { source: 'fallback', text: fallbackBrief(analysis, mem), error: String(err.message || err) };
  }
}

// ---- Interactive chat ----
export async function chat(history, userMessage, analysis) {
  const mem = memoryContext();
  if (!hasClaude()) {
    return {
      source: 'fallback',
      text: 'โหมด offline: ยังไม่ได้ตั้งค่า ANTHROPIC_API_KEY จึงตอบเชิงสนทนาไม่ได้ '
        + 'แต่ระบบยังวิเคราะห์ตัวเลขและแจ้งเตือนอัตโนมัติได้ปกติ — ดูสรุปได้ที่การ์ด Brief ด้านบน '
        + 'ตั้งค่า key ใน .env เพื่อเปิดโหมดสนทนา/สั่งการเต็มรูปแบบ',
    };
  }
  const context = `บริบทการเงินปัจจุบัน (ข้อเท็จจริง ใช้ตอบคำถาม):
\`\`\`json
${JSON.stringify({ portfolio: analysis.portfolio, projects: analysis.projects, memory: mem }, null, 2)}
\`\`\``;

  const messages = [
    { role: 'user', content: context },
    { role: 'assistant', content: 'รับทราบข้อมูลการเงินล่าสุดแล้ว พร้อมตอบและให้คำแนะนำ' },
    ...history.slice(-10).map((m) => ({ role: m.role, content: m.content })),
    { role: 'user', content: userMessage },
  ];

  try {
    const msg = await client().messages.create({
      model: config.model,
      max_tokens: 1500,
      system: SYSTEM_PROMPT,
      messages,
    });
    return { source: 'claude', text: msg.content.map((b) => (b.type === 'text' ? b.text : '')).join('') };
  } catch (err) {
    return { source: 'error', text: `เกิดข้อผิดพลาดในการเรียก Claude: ${String(err.message || err)}` };
  }
}

// ---- Deterministic fallback brief (no network) ----
function n(x) { return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(x); }

function fallbackBrief(analysis, mem) {
  const cur = config.currency;
  const L = [];
  L.push(`# CFO Executive Financial Brief — ${analysis.asOf}`);
  L.push(`(โหมด deterministic — ไม่ได้ใช้ LLM; ตั้งค่า ANTHROPIC_API_KEY เพื่อเปิดบทวิเคราะห์เชิงบริบท)`);
  L.push('');
  L.push('## [Cash Flow Status]');
  L.push(`- เงินสดรวมทุกโปรเจค: **${n(analysis.portfolio.totalCash)} ${cur}**`);
  L.push(`- เงินสดต่ำสุดที่คาดการณ์ (${config.projectionDays} วัน): **${n(analysis.portfolio.projectedMinCash)} ${cur}**`);
  for (const p of analysis.projects) {
    const rw = p.runway.status === 'burning'
      ? `runway ~${p.runway.runwayMonths} เดือน (เผาเงิน ${n(Math.abs(p.runway.monthlyNet))}/เดือน)`
      : 'กระแสเงินสดเป็นบวก';
    L.push(`  - ${p.name}: ${n(p.currentCash)} ${cur} — ${rw}`);
  }
  L.push('');
  L.push('## [P&L Snapshot]');
  for (const p of analysis.projects) {
    const c = p.pnl.current;
    L.push(`- **${p.name}** (MTD ${c.period}): รายรับ ${n(c.revenue)} | ต้นทุนผันแปร ${n(c.variableCost)} | ต้นทุนคงที่ ${n(c.fixedCost)} → กำไรสุทธิ **${n(c.netProfit)} ${cur}**${c.netMarginPct !== null ? ` (${c.netMarginPct}%)` : ''}`);
  }
  L.push('');
  L.push('## [Red Flags & Alerts]');
  const allAlerts = analysis.projects.flatMap((p) => p.alerts.map((a) => ({ ...a, project: p.name })));
  const order = { critical: 0, warning: 1, info: 2 };
  allAlerts.sort((a, b) => order[a.severity] - order[b.severity]);
  if (!allAlerts.length) L.push('- ไม่มีสัญญาณเตือนในเกณฑ์ปัจจุบัน ✅');
  for (const a of allAlerts) {
    const tag = a.severity === 'critical' ? '🔴' : a.severity === 'warning' ? '🟠' : '🔵';
    const recur = mem.recurringAlerts.some((r) => r.startsWith(a.code)) ? ' _(เกิดซ้ำ)_' : '';
    L.push(`- ${tag} **[${a.project}]** ${a.message}${recur}`);
  }
  L.push('');
  L.push('## [Action Recommendations]');
  const recs = allAlerts.filter((a) => a.severity !== 'info').slice(0, 6);
  if (!recs.length) L.push('- คงวินัยการเงินปัจจุบัน และพิจารณานำกระแสเงินสดส่วนเกินไปหมุนต่อ');
  for (const a of recs) L.push(`- **[${a.project}]** ${a.recommendation}`);
  return L.join('\n');
}
