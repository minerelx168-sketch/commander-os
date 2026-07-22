// ─────────────────────────────────────────────────────────────
// datetime.js — การตรวจสอบวัน/เวลาอย่างเข้มงวด
//
// เหตุผลของโมดูลนี้: บทบาท COO กำหนดให้ "ตรวจสอบความถูกต้องของวันและ
// เวลาอย่างเข้มงวดทุกครั้ง" และ "รักษาความถูกต้องแม่นยำระดับสูงสุด"
// โดยเฉพาะข้อมูลการเงินและวันที่ ทุกจุดที่ระบบยุ่งกับวันเวลาให้เรียกผ่านนี่
// ─────────────────────────────────────────────────────────────

export class DateValidationError extends Error {
  constructor(message) {
    super(message);
    this.name = 'DateValidationError';
    this.code = 'INVALID_DATETIME';
  }
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ISO_DATETIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:\d{2})?$/;

// เวลาปัจจุบัน (แยกออกมาเป็นฟังก์ชันเพื่อให้ทดสอบได้ง่ายและ inject ได้)
export function now() {
  return new Date();
}

// แปลง input เป็น Date พร้อมตรวจความถูกต้องแบบเข้มงวด
// รับได้ทั้ง "YYYY-MM-DD" และ ISO datetime เต็ม
export function parseStrict(input) {
  if (input instanceof Date) {
    if (Number.isNaN(input.getTime())) throw new DateValidationError('Date object ไม่ถูกต้อง (Invalid Date)');
    return input;
  }
  if (typeof input !== 'string') {
    throw new DateValidationError(`วันที่ต้องเป็น string หรือ Date ไม่ใช่ ${typeof input}`);
  }
  const s = input.trim();
  if (!ISO_DATE.test(s) && !ISO_DATETIME.test(s)) {
    throw new DateValidationError(
      `รูปแบบวันที่ไม่ถูกต้อง: "${input}" — ต้องเป็น YYYY-MM-DD หรือ ISO datetime`
    );
  }
  const d = new Date(ISO_DATE.test(s) ? `${s}T00:00:00` : s);
  if (Number.isNaN(d.getTime())) {
    throw new DateValidationError(`วันที่แปลงค่าไม่ได้: "${input}"`);
  }
  // กันกรณีวันที่เกินจริง เช่น 2026-02-30 ที่ JS จะ roll over ให้เงียบ ๆ
  if (ISO_DATE.test(s)) {
    const [y, m, day] = s.split('-').map(Number);
    if (d.getFullYear() !== y || d.getMonth() + 1 !== m || d.getDate() !== day) {
      throw new DateValidationError(`วันที่ไม่มีอยู่จริงในปฏิทิน: "${input}"`);
    }
  }
  return d;
}

// ยืนยันว่า "วันที่นี้ต้องไม่อยู่ในอดีต" (ใช้กับประกาศ/นัดหมาย/กำหนดส่ง)
export function assertNotPast(input, { allowToday = true, reference = now() } = {}) {
  const d = parseStrict(input);
  const ref = parseStrict(reference);
  const startOfRefDay = new Date(ref.getFullYear(), ref.getMonth(), ref.getDate());
  const cmp = allowToday ? startOfRefDay.getTime() : ref.getTime();
  if (d.getTime() < cmp) {
    throw new DateValidationError(
      `วันที่ "${toISODate(d)}" อยู่ในอดีต (อ้างอิงปัจจุบัน ${toISO(ref)}) — ปฏิเสธเพื่อกันความผิดพลาด`
    );
  }
  return d;
}

// จำนวนวันเต็มระหว่างสองวัน (b - a) เป็นบวกถ้า b หลัง a
export function daysBetween(a, b) {
  const da = parseStrict(a);
  const db = parseStrict(b);
  const MS = 24 * 60 * 60 * 1000;
  const ua = Date.UTC(da.getFullYear(), da.getMonth(), da.getDate());
  const ub = Date.UTC(db.getFullYear(), db.getMonth(), db.getDate());
  return Math.round((ub - ua) / MS);
}

// จำนวนวันที่เลยกำหนด (overdue) — บวก = เกินกำหนดแล้วกี่วัน
export function daysOverdue(dueDate, reference = now()) {
  return daysBetween(dueDate, reference);
}

export function addDays(input, n) {
  const d = parseStrict(input);
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

export function toISODate(input) {
  const d = parseStrict(input);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export function toISO(input) {
  return parseStrict(input).toISOString();
}

const TH_MONTHS = [
  'มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน',
  'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม',
];

// รูปแบบวันที่ไทย พร้อมพุทธศักราช เช่น "21 กรกฎาคม 2569"
export function formatThai(input, { buddhistEra = true, withTime = false } = {}) {
  const d = parseStrict(input);
  const year = d.getFullYear() + (buddhistEra ? 543 : 0);
  let out = `${d.getDate()} ${TH_MONTHS[d.getMonth()]} ${year}`;
  if (withTime) {
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    out += ` เวลา ${hh}:${mm} น.`;
  }
  return out;
}

export default {
  DateValidationError,
  now,
  parseStrict,
  assertNotPast,
  daysBetween,
  daysOverdue,
  addDays,
  toISODate,
  toISO,
  formatThai,
};
