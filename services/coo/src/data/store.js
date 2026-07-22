// store.js — ที่เก็บสถานะอย่างง่าย (JSON) สำหรับ pipeline / documents / announcements
//
// โหลด seed จาก data/*.json ครั้งแรก แล้ว persist สถานะ runtime ลง
// data/runtime/*.json (ถูก gitignore) เพื่อไม่ทับ seed ต้นฉบับ
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import logger from '../utils/logger.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..', '..');
const SEED_DIR = join(ROOT, 'data');
const RUNTIME_DIR = join(ROOT, 'data', 'runtime');

const FILES = ['pipeline', 'documents', 'announcements'];

function ensureRuntimeDir() {
  if (!existsSync(RUNTIME_DIR)) mkdirSync(RUNTIME_DIR, { recursive: true });
}

function loadFile(name) {
  const runtimePath = join(RUNTIME_DIR, `${name}.json`);
  const seedPath = join(SEED_DIR, `${name}.json`);
  const path = existsSync(runtimePath) ? runtimePath : seedPath;
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch (err) {
    logger.error('store', `โหลดไฟล์ ${name} ไม่ได้: ${err.message}`);
    return {};
  }
}

class Store {
  constructor() {
    this.state = {};
    this.reload();
  }

  reload() {
    for (const f of FILES) this.state[f] = loadFile(f);
    return this.state;
  }

  // โหลด seed ต้นฉบับเข้า memory โดยไม่แตะ runtime (ใช้ให้ test เป็น deterministic)
  loadSeedOnly() {
    for (const f of FILES) {
      this.state[f] = JSON.parse(readFileSync(join(SEED_DIR, `${f}.json`), 'utf8'));
    }
    return this.state;
  }

  persist(name) {
    ensureRuntimeDir();
    const path = join(RUNTIME_DIR, `${name}.json`);
    writeFileSync(path, JSON.stringify(this.state[name], null, 2), 'utf8');
  }

  get pipeline() {
    return this.state.pipeline;
  }
  get documents() {
    return this.state.documents;
  }
  get announcements() {
    return this.state.announcements;
  }

  // รีเซ็ตกลับไปใช้ seed (ลบ runtime) — มีประโยชน์ตอนทดสอบ/เดโม
  resetToSeed() {
    for (const f of FILES) {
      const seed = JSON.parse(readFileSync(join(SEED_DIR, `${f}.json`), 'utf8'));
      this.state[f] = seed;
      this.persist(f);
    }
    return this.state;
  }
}

export const store = new Store();
export default store;
