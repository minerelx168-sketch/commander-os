// announcements.js — เครื่องมือประกาศแจ้งเตือนงานปฏิบัติการ/ซ่อมบำรุงสถานที่
//
// เน้นย้ำ: ตรวจสอบความถูกต้องของวัน/เวลาอย่างเข้มงวดก่อนตั้งประกาศทุกครั้ง
import store from '../data/store.js';
import logger from '../utils/logger.js';
import { assertNotPast, formatThai, now, toISODate } from '../utils/datetime.js';

let seq = 400;
function nextId() {
  return `AN-${++seq}`;
}

// ตั้งประกาศใหม่ — ปฏิเสธถ้าวัน/เวลาไม่ถูกต้องหรืออยู่ในอดีต
export function scheduleAnnouncement({ title, category = 'general', scheduledFor, audience }) {
  if (!title || typeof title !== 'string') {
    throw new Error('ต้องระบุ title ของประกาศ');
  }
  if (!scheduledFor) {
    throw new Error('ต้องระบุ scheduledFor (วัน/เวลาที่จะประกาศ)');
  }
  // ตรวจเข้มงวด: รูปแบบถูกต้อง + ต้องไม่เป็นอดีต (throw DateValidationError ถ้าผิด)
  const when = assertNotPast(scheduledFor, { allowToday: true });

  const record = {
    id: nextId(),
    title,
    category,
    scheduledFor: when.toISOString(),
    scheduledForThai: formatThai(when, { withTime: true }),
    audience: audience || 'ทั้งหมด',
    status: 'scheduled',
    createdAt: new Date().toISOString(),
  };
  store.announcements.scheduled.push(record);
  store.persist('announcements');
  logger.info('announcements', `ตั้งประกาศ "${title}" เวลา ${record.scheduledForThai}`);
  return record;
}

// ส่งประกาศที่ถึงกำหนดแล้ว (scheduledFor <= now)
export function dispatchDueAnnouncements({ reference } = {}) {
  const ref = reference ? new Date(reference) : now();
  const scheduled = store.announcements.scheduled || [];
  const due = scheduled.filter((a) => a.status === 'scheduled' && new Date(a.scheduledFor).getTime() <= ref.getTime());

  const sent = [];
  for (const a of due) {
    a.status = 'sent';
    a.sentAt = new Date().toISOString();
    store.announcements.sent.push(a);
    sent.push({ id: a.id, title: a.title, audience: a.audience });
    logger.info('announcements', `ส่งประกาศ "${a.title}" ไปยัง ${a.audience}`);
  }
  store.announcements.scheduled = scheduled.filter((a) => a.status !== 'sent');
  if (sent.length) store.persist('announcements');
  return { sent, count: sent.length, referenceDate: toISODate(ref) };
}

export function listAnnouncements() {
  return {
    scheduled: store.announcements.scheduled || [],
    sent: store.announcements.sent || [],
  };
}

export const tools = {
  announcement_schedule: {
    description:
      'ตั้งประกาศแจ้งเตือนงานปฏิบัติการ/ซ่อมบำรุงสถานที่ พร้อมตรวจสอบความถูกต้องของวัน/เวลาอย่างเข้มงวด ' +
      '(ปฏิเสธอัตโนมัติถ้ารูปแบบผิดหรือเป็นเวลาในอดีต)',
    parameters: {
      type: 'object',
      required: ['title', 'scheduledFor'],
      properties: {
        title: { type: 'string', description: 'หัวข้อประกาศ' },
        category: { type: 'string', description: 'ประเภท เช่น facility_maintenance, general' },
        scheduledFor: { type: 'string', description: 'วัน/เวลาที่จะประกาศ (ISO datetime)' },
        audience: { type: 'string', description: 'กลุ่มเป้าหมาย' },
      },
    },
    handler: scheduleAnnouncement,
  },
  announcement_dispatch: {
    description: 'ส่งประกาศทั้งหมดที่ถึงกำหนดเวลาแล้ว',
    parameters: {
      type: 'object',
      properties: {
        reference: { type: 'string', description: 'เวลาอ้างอิง (ISO) — ไม่ใส่ = ตอนนี้' },
      },
    },
    handler: dispatchDueAnnouncements,
  },
  announcement_list: {
    description: 'แสดงประกาศที่ตั้งเวลาไว้และที่ส่งแล้ว',
    parameters: { type: 'object', properties: {} },
    handler: listAnnouncements,
  },
};

export default { scheduleAnnouncement, dispatchDueAnnouncements, listAnnouncements, tools };
