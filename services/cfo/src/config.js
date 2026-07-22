// Central configuration. Reads from environment with safe defaults.
// No financial values are hard-coded here beyond operator-set safety thresholds.

import 'node:process';

function num(name, fallback) {
  const v = process.env[name];
  if (v === undefined || v === '') return fallback;
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export const config = {
  model: process.env.CFO_MODEL || 'claude-opus-4-8',
  apiKey: process.env.ANTHROPIC_API_KEY || '',
  port: num('PORT', 3000),
  monitorCron: process.env.CFO_MONITOR_CRON || '0 8 * * *',

  // Safety thresholds (operator-configurable)
  minCashBuffer: num('CFO_MIN_CASH_BUFFER', 100000),
  projectionDays: num('CFO_PROJECTION_DAYS', 30),
  costSpikePct: num('CFO_COST_SPIKE_PCT', 20),
  nplDays: num('CFO_NPL_DAYS', 30),

  currency: 'THB',
};

export function hasClaude() {
  return Boolean(config.apiKey);
}
