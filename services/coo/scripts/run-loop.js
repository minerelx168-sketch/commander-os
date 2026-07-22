#!/usr/bin/env node
// run-loop.js — รัน agent loop เป็นรอบ ๆ ตามช่วงเวลา (autonomous scheduler อย่างง่าย)
//
// ใช้: node scripts/run-loop.js [intervalMinutes]
// ตัวอย่าง: node scripts/run-loop.js 60   → รันทุก 60 นาที
import { runAgent } from '../src/agent/agentLoop.js';
import logger from '../src/utils/logger.js';

const intervalMin = Number(process.argv[2]) || 60;
const intervalMs = intervalMin * 60 * 1000;

async function tick() {
  try {
    const result = await runAgent();
    logger.info('scheduler', `รอบเสร็จ: ${result.actions.length} action, ${result.brief.blockers.length} blocker`);
    console.log('\n' + result.brief.text + '\n');
  } catch (err) {
    logger.error('scheduler', `รอบล้มเหลว: ${err.message}`);
  }
}

logger.info('scheduler', `เริ่ม autonomous loop ทุก ${intervalMin} นาที (กด Ctrl+C เพื่อหยุด)`);
await tick();
setInterval(tick, intervalMs);
