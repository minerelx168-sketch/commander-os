// Autonomous monitoring loop. On the configured cron cadence it re-runs the full
// analysis, generates a fresh brief (persisting it to memory), and logs any
// critical/ warning alerts. This is what makes the CFO "always on" without anyone
// asking. In production, wire notify() to email / LINE / Slack / webhook.

import cron from 'node-cron';
import { config } from './config.js';
import { runBrief } from './service.js';

function notify(analysis) {
  const crit = analysis.projects.flatMap((p) =>
    p.alerts.filter((a) => a.severity !== 'info').map((a) => ({ project: p.name, ...a })));
  if (!crit.length) {
    console.log(`[CFO monitor] ${analysis.asOf} — ไม่มีสัญญาณเตือนเร่งด่วน ✅`);
    return;
  }
  console.log(`[CFO monitor] ${analysis.asOf} — พบ ${crit.length} สัญญาณเตือน:`);
  for (const a of crit) {
    const tag = a.severity === 'critical' ? '🔴' : '🟠';
    console.log(`  ${tag} [${a.project}] ${a.message}`);
  }
}

export async function runOnce(reason = 'manual') {
  const started = new Date().toISOString();
  const { analysis } = await runBrief(undefined, started);
  console.log(`[CFO monitor] run (${reason}) @ ${started}`);
  notify(analysis);
  return analysis;
}

export function startScheduler() {
  if (!config.monitorCron || config.monitorCron.toLowerCase() === 'off') {
    console.log('[CFO monitor] scheduler disabled (CFO_MONITOR_CRON=off)');
    return null;
  }
  if (!cron.validate(config.monitorCron)) {
    console.warn(`[CFO monitor] invalid cron "${config.monitorCron}" — scheduler not started`);
    return null;
  }
  const task = cron.schedule(config.monitorCron, () => {
    runOnce('scheduled').catch((e) => console.error('[CFO monitor] error:', e));
  });
  console.log(`[CFO monitor] scheduler armed: "${config.monitorCron}"`);
  return task;
}
