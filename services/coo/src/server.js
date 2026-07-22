// server.js — HTTP server ของ COO Command (zero-dependency: ใช้ node:http)
//
// เปิด REST API ให้ Manus/LLM เรียก tools ได้ + dashboard + สั่งรัน agent loop
import http from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, extname } from 'node:path';

import config from './config.js';
import logger from './utils/logger.js';
import store from './data/store.js';
import { listTools, toolSchemas, callTool } from './tools/index.js';
import { runAgent } from './agent/agentLoop.js';
import { checkPipeline } from './tools/pipeline.js';
import { listDocuments } from './tools/documents.js';
import { listAnnouncements } from './tools/announcements.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');

let latestBrief = null;

// ── helpers ──
function send(res, status, body, headers = {}) {
  const payload = typeof body === 'string' ? body : JSON.stringify(body, null, 2);
  res.writeHead(status, {
    'content-type': typeof body === 'string' ? 'text/plain; charset=utf-8' : 'application/json; charset=utf-8',
    'access-control-allow-origin': '*',
    'access-control-allow-headers': 'content-type, x-coo-key',
    'access-control-allow-methods': 'GET, POST, OPTIONS',
    ...headers,
  });
  res.end(payload);
}

function readBody(req) {
  return new Promise((resolve) => {
    let data = '';
    req.on('data', (c) => (data += c));
    req.on('end', () => {
      if (!data) return resolve({});
      try {
        resolve(JSON.parse(data));
      } catch {
        resolve({ __parseError: true });
      }
    });
  });
}

// ตรวจ auth เฉพาะเมื่อมีการตั้ง COO_API_KEY
function authorized(req) {
  if (!config.security.authEnabled) return true;
  return req.headers['x-coo-key'] === config.security.apiKey;
}

async function postReportWebhook(brief) {
  if (!config.reportWebhookUrl) return;
  try {
    await fetch(config.reportWebhookUrl, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(brief),
    });
    logger.info('webhook', `ส่ง COO Brief ไปยัง webhook สำเร็จ`);
  } catch (err) {
    logger.warn('webhook', `ส่ง webhook ไม่สำเร็จ: ${err.message}`);
  }
}

const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.yaml': 'text/yaml' };

function serveFile(res, absPath) {
  if (!existsSync(absPath)) return send(res, 404, { error: 'not found' });
  const body = readFileSync(absPath);
  res.writeHead(200, { 'content-type': `${MIME[extname(absPath)] || 'text/plain'}; charset=utf-8` });
  res.end(body);
}

// ── router ──
async function handle(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname;
  const method = req.method;

  if (method === 'OPTIONS') return send(res, 204, '');

  // static + dashboard
  if (method === 'GET' && (path === '/' || path === '/index.html')) {
    return serveFile(res, join(ROOT, 'public', 'index.html'));
  }
  if (method === 'GET' && path === '/openapi.yaml') {
    return serveFile(res, join(ROOT, 'manus', 'openapi.yaml'));
  }
  if (method === 'GET' && path === '/health') {
    return send(res, 200, { ok: true, service: 'coo-command', provider: config.llm.provider, time: new Date().toISOString() });
  }

  // ── Manus discovery: รายการ tools + schema ──
  if (method === 'GET' && path === '/api/tools') {
    return send(res, 200, { tools: listTools(), schemas: toolSchemas() });
  }

  // ── dashboard state ──
  if (method === 'GET' && path === '/api/state') {
    let pipeline = null;
    try {
      pipeline = checkPipeline();
    } catch (err) {
      pipeline = { error: err.message };
    }
    return send(res, 200, {
      provider: config.llm.provider,
      pipeline,
      documents: listDocuments(),
      announcements: listAnnouncements(),
      latestBrief,
      logs: logger.recent(30),
    });
  }

  if (method === 'GET' && path === '/api/brief/latest') {
    return send(res, 200, latestBrief || { message: 'ยังไม่มี brief — เรียก POST /api/agent/run ก่อน' });
  }

  // ── ต่อจากนี้ต้องผ่าน auth ──
  if (path.startsWith('/api/') && !authorized(req)) {
    return send(res, 401, { error: 'unauthorized — ตรวจ header x-coo-key' });
  }

  // เรียกเครื่องมือเดี่ยว (สำหรับ Manus tool-calling ผ่าน HTTP)
  if (method === 'POST' && path.startsWith('/api/tools/')) {
    const name = decodeURIComponent(path.slice('/api/tools/'.length));
    const body = await readBody(req);
    if (body.__parseError) return send(res, 400, { error: 'JSON ไม่ถูกต้อง' });
    const outcome = await callTool(name, body);
    return send(res, outcome.ok ? 200 : 400, outcome);
  }

  // รัน agent loop หนึ่งรอบ → คืน COO Operational Brief
  if (method === 'POST' && path === '/api/agent/run') {
    const body = await readBody(req);
    const result = await runAgent({ directive: body.directive, provider: body.provider });
    latestBrief = result.brief;
    await postReportWebhook(result.brief);
    return send(res, 200, result);
  }

  // reset ข้อมูลกลับ seed (สำหรับเดโม/ทดสอบ)
  if (method === 'POST' && path === '/api/reset') {
    store.resetToSeed();
    latestBrief = null;
    return send(res, 200, { ok: true, message: 'รีเซ็ตข้อมูลกลับ seed แล้ว' });
  }

  return send(res, 404, { error: `ไม่พบเส้นทาง ${method} ${path}` });
}

export function createServer() {
  return http.createServer((req, res) => {
    handle(req, res).catch((err) => {
      logger.error('server', `unhandled: ${err.stack || err.message}`);
      send(res, 500, { error: err.message });
    });
  });
}

// รันเมื่อเรียกไฟล์นี้โดยตรง
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const server = createServer();
  server.listen(config.port, config.host, () => {
    logger.info('server', `COO Command พร้อมใช้งานที่ http://${config.host}:${config.port} [LLM=${config.llm.provider}]`);
  });
}

export default createServer;
