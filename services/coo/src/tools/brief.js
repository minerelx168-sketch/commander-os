// brief.js — สร้าง "สรุปการปฏิบัติงาน COO (COO Operational Brief)"
//
// โครงตามนโยบายงดการประชุม: รายงานแบบอซิงโครนัส 3 ส่วน
//   1) ตรวจสอบระบบ (Systems Check)
//   2) สิ่งที่ลงมือทำ (Action Taken)
//   3) อุปสรรค (Blockers) — เฉพาะที่ต้องให้ผู้บริหารอนุมัติ
import { now, formatThai, toISODate } from '../utils/datetime.js';
import { formatTHB } from './pipeline.js';

// สร้าง brief จากบันทึกการทำงานของ agent loop หนึ่งรอบ
// actions: [{ tool, ok, summary, result, error }]
export function buildBrief({ actions = [], pipelineSnapshot = null, reference } = {}) {
  const ref = reference ? new Date(reference) : now();
  const dateThai = formatThai(ref, { withTime: true });

  const systemsCheck = [];
  const actionsTaken = [];
  const blockers = [];

  for (const a of actions) {
    if (!a.ok) {
      blockers.push({
        area: a.tool,
        issue: a.error || 'ทำงานไม่สำเร็จ',
        needsApproval: a.needsApproval ?? true,
      });
      continue;
    }
    switch (a.tool) {
      case 'document_generate': {
        const n = a.result?.count ?? 0;
        if (n > 0) {
          systemsCheck.push(`สร้างและจัดเก็บเอกสารสำเร็จ ${n} ฉบับ`);
          actionsTaken.push(a.result.generated.map((g) => `${g.typeLabel} → ${g.filename}`).join(', '));
        }
        break;
      }
      case 'pipeline_send_reminder': {
        const n = a.result?.count ?? 0;
        if (n > 0) actionsTaken.push(`ส่งข้อความแจ้งเตือนยอดค้างชำระ ${n} ราย`);
        break;
      }
      case 'pipeline_check': {
        systemsCheck.push(
          `ตรวจ pipeline: บัญชีเกินกำหนด ${a.result.overdueCount} ราย รวม ${a.result.totalOverdueAmountText}`
        );
        break;
      }
      case 'announcement_schedule': {
        actionsTaken.push(`ตั้งประกาศ "${a.result.title}" (${a.result.scheduledForThai})`);
        break;
      }
      case 'announcement_dispatch': {
        const n = a.result?.count ?? 0;
        if (n > 0) actionsTaken.push(`ส่งประกาศที่ถึงกำหนด ${n} รายการ`);
        break;
      }
      default:
        if (a.summary) actionsTaken.push(a.summary);
    }
  }

  // เพิ่ม blocker เชิงธุรกิจจาก snapshot pipeline (เช่น ยอดค้างสูงผิดปกติ)
  if (pipelineSnapshot) {
    const heavy = (pipelineSnapshot.overdue || []).filter((o) => o.overdueDays >= 14);
    if (heavy.length) {
      blockers.push({
        area: 'debt_collection',
        issue:
          `มีบัญชีค้างชำระเกิน 14 วัน ${heavy.length} ราย (${heavy.map((h) => h.id).join(', ')}) ` +
          `— เกินกรอบการทวงถามอัตโนมัติ ควรพิจารณาขั้นตอนทางกฎหมาย/ปรับโครงสร้างหนี้`,
        needsApproval: true,
      });
    }
  }

  if (systemsCheck.length === 0) systemsCheck.push('ระบบอัตโนมัติทำงานปกติ ไม่มีรายการที่ต้องประมวลผล');
  if (actionsTaken.length === 0) actionsTaken.push('ไม่มีการดำเนินการที่ต้องบันทึกในรอบนี้');

  const brief = {
    title: 'สรุปการปฏิบัติงาน COO (COO Operational Brief)',
    date: toISODate(ref),
    dateThai,
    systemsCheck,
    actionsTaken,
    blockers,
    generatedAt: new Date().toISOString(),
  };
  brief.text = renderBriefText(brief);
  return brief;
}

// เรนเดอร์เป็นข้อความอ่านง่ายสำหรับส่งให้ CEO/ผู้บริหาร
export function renderBriefText(brief) {
  const lines = [];
  lines.push(`📋 ${brief.title}`);
  lines.push(`ประจำวันที่ ${brief.dateThai}`);
  lines.push('');
  lines.push('[ตรวจสอบระบบ (Systems Check)]');
  brief.systemsCheck.forEach((s) => lines.push(`  • ${s}`));
  lines.push('');
  lines.push('[สิ่งที่ลงมือทำ (Action Taken)]');
  brief.actionsTaken.forEach((s) => lines.push(`  • ${s}`));
  lines.push('');
  lines.push('[อุปสรรค (Blockers)]');
  if (brief.blockers.length === 0) {
    lines.push('  • ไม่มี — ไม่มีรายการที่ต้องขออนุมัติจากผู้บริหาร');
  } else {
    brief.blockers.forEach((b) => lines.push(`  • [${b.area}] ${b.issue}`));
  }
  return lines.join('\n');
}

export const tools = {
  coo_brief: {
    description:
      'สร้าง "สรุปการปฏิบัติงาน COO (COO Operational Brief)" แบบอซิงโครนัส 3 ส่วน: ' +
      'ตรวจสอบระบบ / สิ่งที่ลงมือทำ / อุปสรรคที่ต้องขออนุมัติ',
    parameters: {
      type: 'object',
      properties: {
        actions: { type: 'array', description: 'รายการงานที่ทำในรอบนี้', items: { type: 'object' } },
      },
    },
    handler: buildBrief,
  },
};

export default { buildBrief, renderBriefText, tools };
