// logger.js — บันทึก log แบบมีโครงสร้าง เก็บใน memory เพื่อให้ dashboard/brief ดึงได้
import config from '../config.js';

const RING_SIZE = 500;
const ring = [];

function push(level, scope, message, meta) {
  const entry = {
    ts: new Date().toISOString(),
    level,
    scope,
    message,
    ...(meta ? { meta } : {}),
  };
  ring.push(entry);
  if (ring.length > RING_SIZE) ring.shift();

  const line = `[${entry.ts}] ${level.toUpperCase()} (${scope}) ${message}`;
  if (level === 'error') console.error(line, meta ?? '');
  else if (level === 'warn') console.warn(line, meta ?? '');
  else if (level === 'debug') {
    if (config.debug) console.debug(line, meta ?? '');
  } else console.log(line, meta ?? '');
  return entry;
}

export const logger = {
  info: (scope, message, meta) => push('info', scope, message, meta),
  warn: (scope, message, meta) => push('warn', scope, message, meta),
  error: (scope, message, meta) => push('error', scope, message, meta),
  debug: (scope, message, meta) => push('debug', scope, message, meta),
  recent: (n = 50) => ring.slice(-n),
  clear: () => {
    ring.length = 0;
  },
};

export default logger;
