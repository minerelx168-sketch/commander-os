// Thin orchestration layer shared by the HTTP server, CLI, and scheduler.

import { loadAll } from './dataLoader.js';
import { analyze } from './financeEngine.js';
import { generateBrief, chat } from './cfoAgent.js';
import { recordBrief, addFeedback, memoryContext, load as loadMemory } from './memory.js';

export function runAnalysis(asOf) {
  const data = loadAll();
  return analyze(data, asOf);
}

export async function runBrief(asOf, isoNow) {
  const analysis = runAnalysis(asOf);
  const brief = await generateBrief(analysis);
  const headline = analysis.portfolio.criticalAlerts > 0
    ? `${analysis.portfolio.criticalAlerts} critical alert(s)`
    : `${analysis.portfolio.totalAlerts} alert(s)`;
  recordBrief(analysis, headline, isoNow || new Date().toISOString());
  return { analysis, brief };
}

export async function runChat(history, message, asOf) {
  const analysis = runAnalysis(asOf);
  return chat(history || [], message, analysis);
}

export { addFeedback, memoryContext, loadMemory };
