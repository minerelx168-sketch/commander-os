// Loads financial source data (CSV/JSON) from disk. No external dependencies.
// Kept intentionally strict: malformed numeric cells throw rather than silently
// coercing to 0, because the CFO must never work off guessed numbers.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
export const DATA_DIR = join(__dirname, '..', 'data');

// Minimal RFC-4180-ish CSV parser (supports quoted fields).
export function parseCSV(text) {
  const rows = [];
  let field = '';
  let row = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += c;
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ',') {
      row.push(field); field = '';
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(field); field = '';
      if (row.length > 1 || row[0] !== '') rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row); }
  if (!rows.length) return [];
  const header = rows[0].map((h) => h.trim());
  return rows.slice(1).map((r) => {
    const obj = {};
    header.forEach((h, idx) => { obj[h] = (r[idx] ?? '').trim(); });
    return obj;
  });
}

function toNumber(value, context) {
  const n = Number(String(value).replace(/,/g, ''));
  if (!Number.isFinite(n)) {
    throw new Error(`Non-numeric financial value "${value}" in ${context}`);
  }
  return n;
}

export function loadProjects() {
  const raw = JSON.parse(readFileSync(join(DATA_DIR, 'projects.json'), 'utf8'));
  return raw;
}

export function loadTransactions() {
  const rows = parseCSV(readFileSync(join(DATA_DIR, 'transactions.csv'), 'utf8'));
  return rows.map((r, i) => ({
    date: r.date,
    project: r.project,
    type: r.type, // income | expense
    category: r.category,
    cost_type: r.cost_type, // fixed | variable | na
    pnl: r.pnl === 'yes', // whether it hits the P&L (vs. balance-sheet cash flow)
    amount: toNumber(r.amount, `transactions.csv row ${i + 2}`),
    description: r.description || '',
  }));
}

export function loadObligations() {
  const rows = parseCSV(readFileSync(join(DATA_DIR, 'obligations.csv'), 'utf8'));
  return rows.map((r, i) => ({
    date: r.date,
    project: r.project,
    direction: r.direction, // in | out
    category: r.category,
    amount: toNumber(r.amount, `obligations.csv row ${i + 2}`),
    status: r.status,
    description: r.description || '',
  }));
}

export function loadReceivables() {
  const rows = parseCSV(readFileSync(join(DATA_DIR, 'receivables.csv'), 'utf8'));
  return rows.map((r, i) => ({
    customer_id: r.customer_id,
    project: r.project,
    principal: toNumber(r.principal, `receivables.csv row ${i + 2}`),
    outstanding: toNumber(r.outstanding, `receivables.csv row ${i + 2}`),
    due_date: r.due_date,
    days_overdue: toNumber(r.days_overdue, `receivables.csv row ${i + 2}`),
    status: r.status,
  }));
}

export function loadAll() {
  return {
    projectsMeta: loadProjects(),
    transactions: loadTransactions(),
    obligations: loadObligations(),
    receivables: loadReceivables(),
  };
}
