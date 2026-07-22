// CFO Command — HTTP server. Serves the dashboard and a small JSON API, and
// arms the autonomous monitoring scheduler on boot.

import express from 'express';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { config, hasClaude } from './src/config.js';
import { runAnalysis, runBrief, runChat, addFeedback, memoryContext } from './src/service.js';
import { startScheduler } from './src/scheduler.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();
app.use(express.json({ limit: '1mb' }));
app.use(express.static(join(__dirname, 'public')));

const wrap = (fn) => (req, res) => Promise.resolve(fn(req, res)).catch((e) => {
  console.error(e);
  res.status(500).json({ error: String(e.message || e) });
});

// System status (used by the UI header / agent tiles)
app.get('/api/status', (req, res) => {
  res.json({
    name: 'CFO Command',
    tagline: 'Autonomous AI Chief Financial Officer',
    model: config.model,
    claudeConnected: hasClaude(),
    currency: config.currency,
    monitorCron: config.monitorCron,
    thresholds: {
      minCashBuffer: config.minCashBuffer,
      projectionDays: config.projectionDays,
      costSpikePct: config.costSpikePct,
      nplDays: config.nplDays,
    },
    memory: memoryContext(),
  });
});

// Full deterministic analysis (numbers)
app.get('/api/analysis', wrap((req, res) => {
  res.json(runAnalysis(req.query.asOf));
}));

// Executive brief (AI or fallback)
app.get('/api/brief', wrap(async (req, res) => {
  const { analysis, brief } = await runBrief(req.query.asOf);
  res.json({ asOf: analysis.asOf, portfolio: analysis.portfolio, brief });
}));

// Chat with the CFO agent
app.post('/api/chat', wrap(async (req, res) => {
  const { message, history } = req.body || {};
  if (!message || typeof message !== 'string') {
    return res.status(400).json({ error: 'message is required' });
  }
  const reply = await runChat(history, message, req.query.asOf);
  res.json(reply);
}));

// Operator feedback → fed back into the self-learning loop
app.post('/api/feedback', wrap((req, res) => {
  const { text } = req.body || {};
  if (!text) return res.status(400).json({ error: 'text is required' });
  addFeedback(text, new Date().toISOString());
  res.json({ ok: true });
}));

// Trigger an on-demand monitoring run
app.post('/api/monitor/run', wrap(async (req, res) => {
  const { analysis } = await runBrief(req.query.asOf);
  res.json({ ok: true, asOf: analysis.asOf, portfolio: analysis.portfolio });
}));

app.listen(config.port, () => {
  console.log('');
  console.log('  CFO Command System Initialized. Monitoring financial pipelines.');
  console.log(`  Dashboard : http://localhost:${config.port}`);
  console.log(`  Model     : ${config.model}`);
  console.log(`  Claude    : ${hasClaude() ? 'connected' : 'offline (deterministic fallback)'}`);
  console.log('');
  startScheduler();
});
