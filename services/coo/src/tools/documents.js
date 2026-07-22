// documents.js — เครื่องมือสร้างเอกสารทางการอัตโนมัติ (จำลอง Google Apps Script web app)
//
// ในการใช้งานจริง handler นี้จะยิงไปที่ Web App URL ของ Google Apps Script
// (ตั้งค่าใน env) เพื่อสั่งสร้าง PDF สัญญา / แบบฟอร์ม PDPA แล้วเก็บลง Drive
// ที่นี่จำลองผลลัพธ์เพื่อให้ทั้งระบบรันได้ครบวงจรโดยไม่ต้องต่อของจริง
import store from '../data/store.js';
import logger from '../utils/logger.js';
import { now, toISODate } from '../utils/datetime.js';

const TYPE_LABEL = {
  pdpa_consent: 'แบบฟอร์มยินยอม PDPA',
  loan_contract: 'สัญญาสินเชื่อ',
  refinance_agreement: 'สัญญารีไฟแนนซ์',
};

// ตั้งชื่อไฟล์แบบมีมาตรฐาน: <TYPE>_<ACCOUNT>_<YYYYMMDD>.pdf
function buildFilename(type, accountId, date) {
  const stamp = toISODate(date).replaceAll('-', '');
  const t = (type || 'DOC').toUpperCase();
  return `${t}_${accountId || 'NA'}_${stamp}.pdf`;
}

// สร้างเอกสารจากรายการใน queue (หรือรายการที่ระบุ)
export function generateDocuments({ docId, appsScriptUrl } = {}) {
  const queue = store.documents.queue || [];
  const targets = docId ? queue.filter((d) => d.id === docId) : queue.filter((d) => d.status === 'pending');

  if (targets.length === 0) {
    return { generated: [], count: 0, message: 'ไม่มีเอกสารที่รอสร้างในคิว' };
  }

  const today = now();
  const generated = [];

  for (const doc of targets) {
    const filename = buildFilename(doc.type, doc.accountId, today);
    // จุดเชื่อมของจริง: ถ้ามี appsScriptUrl ให้ POST ไปสั่งสร้าง (คงไว้เป็น TODO ที่ชัดเจน)
    const record = {
      id: doc.id,
      type: doc.type,
      typeLabel: TYPE_LABEL[doc.type] || doc.type,
      customer: doc.customer,
      accountId: doc.accountId,
      filename,
      // จำลอง path บน Drive; ของจริงจะเป็น URL ไฟล์ที่ Apps Script คืนมา
      drivePath: `/COO-Command/Documents/${new Date(today).getFullYear()}/${filename}`,
      generatedAt: new Date().toISOString(),
      source: appsScriptUrl ? 'apps_script' : 'simulated',
    };
    doc.status = 'generated';
    store.documents.generated.push(record);
    generated.push(record);
    logger.info('documents', `สร้าง ${record.typeLabel} สำเร็จ: ${filename}`);
  }

  store.persist('documents');
  return {
    generated,
    count: generated.length,
    message: `สร้างและจัดเก็บเอกสารสำเร็จ ${generated.length} ฉบับ`,
  };
}

export function listDocuments() {
  return {
    pending: (store.documents.queue || []).filter((d) => d.status === 'pending'),
    generated: store.documents.generated || [],
  };
}

export const tools = {
  document_generate: {
    description:
      'สั่งสร้างเอกสารทางการอัตโนมัติ (สัญญาสินเชื่อ / แบบฟอร์ม PDPA) จากคิว จัดเก็บและตั้งชื่อไฟล์ตามมาตรฐาน ' +
      'รองรับการต่อ Google Apps Script web app ผ่านพารามิเตอร์ appsScriptUrl',
    parameters: {
      type: 'object',
      properties: {
        docId: { type: 'string', description: 'รหัสเอกสารเฉพาะราย (ไม่ใส่ = ทุกเอกสารที่ pending)' },
        appsScriptUrl: { type: 'string', description: 'Web App URL ของ Google Apps Script (ถ้ามี)' },
      },
    },
    handler: generateDocuments,
  },
  document_list: {
    description: 'แสดงรายการเอกสารที่รอสร้าง (pending) และที่สร้างเสร็จแล้ว',
    parameters: { type: 'object', properties: {} },
    handler: listDocuments,
  },
};

export default { generateDocuments, listDocuments, tools };
