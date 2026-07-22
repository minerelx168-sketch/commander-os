// pipeline.js — เครื่องมือด้านตรวจสอบ pipeline และการทวงหนี้/ยอดค้าง
import store from '../data/store.js';
import logger from '../utils/logger.js';
import { daysOverdue, now, toISODate, formatThai } from '../utils/datetime.js';

// จัดรูปแบบตัวเลขเงินบาทให้แม่นยำ (สำคัญต่อความถูกต้องทางการเงิน)
export function formatTHB(amount) {
  if (typeof amount !== 'number' || !Number.isFinite(amount)) {
    throw new Error(`จำนวนเงินไม่ถูกต้อง: ${amount}`);
  }
  return `${amount.toLocaleString('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} บาท`;
}

// ตรวจสอบสถานะ pipeline: หาบัญชีเกินกำหนด + สรุปยอด
export function checkPipeline({ reference } = {}) {
  const ref = reference || toISODate(now());
  const accounts = store.pipeline.accounts || [];
  const overdue = [];
  let totalOverdueAmount = 0;

  for (const acc of accounts) {
    const overdueDays = daysOverdue(acc.dueDate, ref);
    if (overdueDays > 0) {
      overdue.push({
        id: acc.id,
        customer: acc.customer,
        installment: acc.installment,
        dueDate: acc.dueDate,
        overdueDays,
        lastReminderAt: acc.lastReminderAt,
      });
      totalOverdueAmount += acc.installment;
    }
  }

  overdue.sort((a, b) => b.overdueDays - a.overdueDays);

  const leads = store.pipeline.leads || [];
  const leadValueByStage = {};
  for (const l of leads) {
    leadValueByStage[l.stage] = (leadValueByStage[l.stage] || 0) + l.value;
  }

  const result = {
    reference: ref,
    accountCount: accounts.length,
    overdueCount: overdue.length,
    totalOverdueAmount,
    totalOverdueAmountText: formatTHB(totalOverdueAmount),
    overdue,
    leads: { count: leads.length, valueByStage: leadValueByStage },
  };
  logger.info('pipeline', `ตรวจ pipeline: พบบัญชีเกินกำหนด ${overdue.length} ราย รวม ${result.totalOverdueAmountText}`);
  return result;
}

// ร่างและ "ส่ง" ข้อความแจ้งเตือนไปยังลูกค้าที่เกินกำหนด (idempotent ต่อวัน)
export function sendReminder({ accountId, dryRun = false, minOverdueDays = 1 } = {}) {
  const accounts = store.pipeline.accounts || [];
  const targets = accountId
    ? accounts.filter((a) => a.id === accountId)
    : accounts.filter((a) => daysOverdue(a.dueDate, now()) >= minOverdueDays);

  if (targets.length === 0) {
    return { sent: [], skipped: [], message: 'ไม่มีบัญชีที่ต้องแจ้งเตือน' };
  }

  const today = toISODate(now());
  const sent = [];
  const skipped = [];

  for (const acc of targets) {
    // กันส่งซ้ำในวันเดียวกัน
    if (acc.lastReminderAt && toISODate(acc.lastReminderAt) === today) {
      skipped.push({ id: acc.id, reason: 'แจ้งเตือนไปแล้ววันนี้' });
      continue;
    }
    const overdueDays = daysOverdue(acc.dueDate, now());
    const message =
      `เรียน ${acc.customer}\n` +
      `บัญชี ${acc.id} (${acc.product}) มียอดผ่อนชำระ ${formatTHB(acc.installment)} ` +
      `ครบกำหนดวันที่ ${formatThai(acc.dueDate)} ซึ่งเลยกำหนดมาแล้ว ${overdueDays} วัน\n` +
      `กรุณาชำระเพื่อหลีกเลี่ยงค่าปรับ ขอบพระคุณค่ะ`;

    if (!dryRun) {
      acc.lastReminderAt = new Date().toISOString();
    }
    sent.push({ id: acc.id, customer: acc.customer, phone: acc.phone, overdueDays, message, dryRun });
    logger.info('pipeline', `ส่งแจ้งเตือน ${acc.id} (${acc.customer}) เกินกำหนด ${overdueDays} วัน${dryRun ? ' [dryRun]' : ''}`);
  }

  if (!dryRun && sent.length) store.persist('pipeline');
  return { sent, skipped, count: sent.length };
}

export const tools = {
  pipeline_check: {
    description: 'ตรวจสอบสถานะ pipeline การขาย/ปฏิบัติการ และหาบัญชีที่เกินกำหนดชำระ (overdue) พร้อมสรุปยอด',
    parameters: {
      type: 'object',
      properties: {
        reference: { type: 'string', description: 'วันที่อ้างอิงรูปแบบ YYYY-MM-DD (ไม่ใส่ = วันนี้)' },
      },
    },
    handler: checkPipeline,
  },
  pipeline_send_reminder: {
    description: 'ร่างและส่งข้อความแจ้งเตือนทวงยอดค้างชำระไปยังลูกค้าที่เกินกำหนด (กันส่งซ้ำในวันเดียวกันอัตโนมัติ)',
    parameters: {
      type: 'object',
      properties: {
        accountId: { type: 'string', description: 'รหัสบัญชีเฉพาะราย (ไม่ใส่ = ทุกบัญชีที่เกินกำหนด)' },
        minOverdueDays: { type: 'number', description: 'ส่งเฉพาะที่เกินกำหนดอย่างน้อยกี่วัน (default 1)' },
        dryRun: { type: 'boolean', description: 'true = ร่างข้อความอย่างเดียวไม่บันทึกสถานะ' },
      },
    },
    handler: sendReminder,
  },
};

export default { checkPipeline, sendReminder, formatTHB, tools };
