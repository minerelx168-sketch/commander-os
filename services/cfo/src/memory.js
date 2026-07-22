// Lightweight persistent memory that gives the CFO agent continuity between runs
// — the basis of its "self-learning" loop. Past briefs, resolved/standing flags,
// and operator feedback are stored and fed back into future prompts so the agent
// stops repeating noise and tracks whether prior recommendations worked.

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const MEM_DIR = join(__dirname, '..', 'memory');
const MEM_FILE = join(MEM_DIR, 'cfo-memory.json');

const EMPTY = {
  version: 1,
  briefs: [], // { at, portfolioSnapshot, headline }
  insights: [], // learned patterns/notes { at, note, source }
  feedback: [], // operator responses { at, text }
  seenAlerts: {}, // code:project -> { firstSeen, lastSeen, count }
};

function ensureDir() { if (!existsSync(MEM_DIR)) mkdirSync(MEM_DIR, { recursive: true }); }

export function load() {
  try {
    if (!existsSync(MEM_FILE)) return structuredClone(EMPTY);
    return { ...structuredClone(EMPTY), ...JSON.parse(readFileSync(MEM_FILE, 'utf8')) };
  } catch {
    return structuredClone(EMPTY);
  }
}

export function save(mem) {
  ensureDir();
  writeFileSync(MEM_FILE, JSON.stringify(mem, null, 2));
}

// Record a brief and reconcile alerts against what we've seen before, so the
// agent can distinguish "new today" from "still unresolved / recurring".
export function recordBrief(analysis, headline, isoNow) {
  const mem = load();
  mem.briefs.unshift({
    at: isoNow,
    headline,
    totalCash: analysis.portfolio.totalCash,
    totalNetMTD: analysis.portfolio.totalNetMTD,
    criticalAlerts: analysis.portfolio.criticalAlerts,
  });
  mem.briefs = mem.briefs.slice(0, 60);

  for (const p of analysis.projects) {
    for (const a of p.alerts) {
      const key = `${a.code}:${p.id}`;
      const prev = mem.seenAlerts[key];
      if (prev) { prev.lastSeen = isoNow; prev.count += 1; }
      else mem.seenAlerts[key] = { firstSeen: isoNow, lastSeen: isoNow, count: 1 };
    }
  }
  save(mem);
  return mem;
}

export function addFeedback(text, isoNow) {
  const mem = load();
  mem.feedback.unshift({ at: isoNow, text });
  mem.feedback = mem.feedback.slice(0, 100);
  save(mem);
  return mem;
}

export function addInsight(note, source, isoNow) {
  const mem = load();
  mem.insights.unshift({ at: isoNow, note, source: source || 'agent' });
  mem.insights = mem.insights.slice(0, 100);
  save(mem);
  return mem;
}

// Compact memory context injected into Claude prompts.
export function memoryContext() {
  const mem = load();
  const recurring = Object.entries(mem.seenAlerts)
    .filter(([, v]) => v.count >= 2)
    .map(([k, v]) => `${k} (seen ${v.count}x, since ${v.firstSeen.slice(0, 10)})`);
  return {
    lastBrief: mem.briefs[0] || null,
    recurringAlerts: recurring,
    recentFeedback: mem.feedback.slice(0, 5),
    insights: mem.insights.slice(0, 8),
  };
}
