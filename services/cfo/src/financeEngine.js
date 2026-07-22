// Deterministic financial engine. Every number the CFO reports originates here —
// Claude only narrates these figures, it never invents them.

import { config } from './config.js';

const DAY_MS = 86400000;

function parseDate(s) { return new Date(`${s}T00:00:00Z`); }
function monthKey(dateStr) { return dateStr.slice(0, 7); }
function prevMonthKey(key) {
  const [y, m] = key.split('-').map(Number);
  const d = new Date(Date.UTC(y, m - 2, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}
function daysInMonth(key) {
  const [y, m] = key.split('-').map(Number);
  return new Date(Date.UTC(y, m, 0)).getUTCDate();
}
function round(n) { return Math.round(n * 100) / 100; }

// ---------- P&L ----------
function pnlForPeriod(txns, projectId, monthKeyStr) {
  const rows = txns.filter(
    (t) => t.project === projectId && t.pnl && monthKey(t.date) === monthKeyStr,
  );
  const revenue = sum(rows.filter((t) => t.type === 'income'));
  const variableCost = sum(rows.filter((t) => t.type === 'expense' && t.cost_type === 'variable'));
  const fixedCost = sum(rows.filter((t) => t.type === 'expense' && t.cost_type === 'fixed'));
  const grossProfit = revenue - variableCost;
  const netProfit = grossProfit - fixedCost;
  return {
    period: monthKeyStr,
    revenue: round(revenue),
    variableCost: round(variableCost),
    fixedCost: round(fixedCost),
    grossProfit: round(grossProfit),
    netProfit: round(netProfit),
    netMarginPct: revenue > 0 ? round((netProfit / revenue) * 100) : null,
  };
}

function sum(rows) { return rows.reduce((a, t) => a + t.amount, 0); }

// ---------- Cost structure & spike detection ----------
function costStructure(txns, projectId, currentMonth, priorMonth, asOf) {
  const dayOfMonth = asOf.getUTCDate();
  const dim = daysInMonth(currentMonth);
  const costTypeByCat = {};
  const catTotals = (mk) => {
    const map = {};
    txns
      .filter((t) => t.project === projectId && t.type === 'expense' && t.pnl && monthKey(t.date) === mk)
      .forEach((t) => {
        map[t.category] = (map[t.category] || 0) + t.amount;
        costTypeByCat[t.category] = t.cost_type;
      });
    return map;
  };
  const cur = catTotals(currentMonth);
  const prior = catTotals(priorMonth);
  const categories = new Set([...Object.keys(cur), ...Object.keys(prior)]);
  const breakdown = [];
  const spikes = [];
  for (const cat of categories) {
    const mtd = cur[cat] || 0;
    // Variable costs accrue daily → prorate MTD to a full-month run-rate.
    // Fixed costs post as recurring lump sums → compare actuals directly to
    // avoid false spikes from day-of-month proration.
    const isVariable = costTypeByCat[cat] === 'variable';
    const runRate = (isVariable && dayOfMonth > 0) ? (mtd * dim) / dayOfMonth : mtd;
    const priorVal = prior[cat] || 0;
    const changePct = priorVal > 0 ? ((runRate - priorVal) / priorVal) * 100 : (runRate > 0 ? Infinity : 0);
    const entry = {
      category: cat,
      mtd: round(mtd),
      projectedFullMonth: round(runRate),
      priorMonth: round(priorVal),
      changePct: Number.isFinite(changePct) ? round(changePct) : null,
    };
    breakdown.push(entry);
    // Flag material spikes only (ignore tiny absolute swings).
    if (changePct > config.costSpikePct && runRate - priorVal >= 5000) {
      spikes.push({ ...entry });
    }
  }
  breakdown.sort((a, b) => b.projectedFullMonth - a.projectedFullMonth);
  spikes.sort((a, b) => (b.changePct ?? 0) - (a.changePct ?? 0));
  return { breakdown, spikes };
}

// ---------- Current cash position ----------
function cashPosition(txns, project, asOf) {
  const opening = project.opening_cash;
  const openDate = parseDate(project.opening_cash_date);
  let cash = opening;
  txns
    .filter((t) => t.project === project.id)
    .filter((t) => {
      const d = parseDate(t.date);
      return d >= openDate && d <= asOf;
    })
    .forEach((t) => { cash += t.type === 'income' ? t.amount : -t.amount; });
  return round(cash);
}

// ---------- Forward cash-flow projection ----------
function projectCashFlow(obligations, projectId, startCash, asOf, horizonDays) {
  const horizonEnd = new Date(asOf.getTime() + horizonDays * DAY_MS);
  const items = obligations
    .filter((o) => o.project === projectId)
    .filter((o) => { const d = parseDate(o.date); return d > asOf && d <= horizonEnd; })
    .sort((a, b) => parseDate(a.date) - parseDate(b.date));

  let balance = startCash;
  let minBalance = startCash;
  let minDate = asOf.toISOString().slice(0, 10);
  let breachDate = null; // first day below safety buffer
  let negativeDate = null; // first day below zero
  const timeline = [];
  for (const it of items) {
    balance += it.direction === 'in' ? it.amount : -it.amount;
    balance = round(balance);
    timeline.push({
      date: it.date,
      direction: it.direction,
      category: it.category,
      amount: it.amount,
      status: it.status,
      description: it.description,
      balanceAfter: balance,
    });
    if (balance < minBalance) { minBalance = balance; minDate = it.date; }
    if (breachDate === null && balance < config.minCashBuffer) breachDate = it.date;
    if (negativeDate === null && balance < 0) negativeDate = it.date;
  }
  const totalIn = round(sum2(items.filter((i) => i.direction === 'in')));
  const totalOut = round(sum2(items.filter((i) => i.direction === 'out')));
  return {
    horizonDays,
    startCash: round(startCash),
    endCash: round(balance),
    minBalance: round(minBalance),
    minDate,
    breachDate,
    negativeDate,
    totalExpectedIn: totalIn,
    totalScheduledOut: totalOut,
    timeline,
  };
}
function sum2(rows) { return rows.reduce((a, r) => a + r.amount, 0); }

// ---------- Receivables / portfolio risk (lending) ----------
function receivablesRisk(receivables, projectId) {
  const rows = receivables.filter((r) => r.project === projectId);
  if (!rows.length) return null;
  const totalOutstanding = round(sum2(rows.map((r) => ({ amount: r.outstanding }))));
  const buckets = {
    current: 0, '1-30': 0, '31-60': 0, '61-90': 0, '90+': 0,
  };
  let atRisk = 0;
  const watchlist = [];
  for (const r of rows) {
    const o = r.outstanding;
    if (r.days_overdue <= 0) buckets.current += o;
    else if (r.days_overdue <= 30) buckets['1-30'] += o;
    else if (r.days_overdue <= 60) buckets['31-60'] += o;
    else if (r.days_overdue <= 90) buckets['61-90'] += o;
    else buckets['90+'] += o;
    if (r.days_overdue >= config.nplDays) {
      atRisk += o;
      watchlist.push({ customer_id: r.customer_id, outstanding: o, days_overdue: r.days_overdue, due_date: r.due_date });
    }
  }
  Object.keys(buckets).forEach((k) => { buckets[k] = round(buckets[k]); });
  watchlist.sort((a, b) => b.days_overdue - a.days_overdue);
  return {
    accounts: rows.length,
    totalOutstanding,
    buckets,
    atRiskAmount: round(atRisk),
    nplRatioPct: totalOutstanding > 0 ? round((atRisk / totalOutstanding) * 100) : 0,
    watchlist,
  };
}

// ---------- Runway ----------
function runway(currentCash, currentPnl, asOf, currentMonth) {
  const dayOfMonth = asOf.getUTCDate();
  const dim = daysInMonth(currentMonth);
  // Prorate MTD net profit to a full-month operating result.
  const monthlyNet = dayOfMonth > 0 ? (currentPnl.netProfit * dim) / dayOfMonth : currentPnl.netProfit;
  if (monthlyNet >= 0) {
    return { monthlyNet: round(monthlyNet), status: 'cash-generative', runwayMonths: null, runwayDays: null };
  }
  const burn = Math.abs(monthlyNet);
  const months = currentCash / burn;
  return {
    monthlyNet: round(monthlyNet),
    status: 'burning',
    runwayMonths: round(months),
    runwayDays: Math.round(months * 30),
  };
}

// ---------- Alert synthesis ----------
function buildAlerts(p) {
  const alerts = [];
  const push = (severity, code, message, recommendation) =>
    alerts.push({ severity, code, message, recommendation });

  if (p.projection.negativeDate) {
    push('critical', 'CASH_NEGATIVE',
      `กระแสเงินสดจะติดลบวันที่ ${p.projection.negativeDate} (ต่ำสุด ${fmt(p.projection.minBalance)} ${config.currency})`,
      'เร่งเก็บยอดค้างรับ / เลื่อนรายจ่ายที่ไม่จำเป็น / เตรียมวงเงินสำรองทันที');
  } else if (p.projection.breachDate) {
    push('warning', 'CASH_BUFFER_BREACH',
      `เงินสดจะต่ำกว่าเกณฑ์ปลอดภัย (${fmt(config.minCashBuffer)}) วันที่ ${p.projection.breachDate} — ต่ำสุด ${fmt(p.projection.minBalance)} ${config.currency}`,
      'ทบทวนตารางจ่ายเงินก้อนใหญ่ และเร่งกระแสเงินสดรับในช่วง 14 วันข้างหน้า');
  }

  for (const s of p.costStructure.spikes) {
    const pct = s.changePct === null ? 'ใหม่ทั้งหมด' : `+${s.changePct}%`;
    push(s.changePct !== null && s.changePct >= 100 ? 'critical' : 'warning', 'COST_SPIKE',
      `ต้นทุน "${s.category}" พุ่งขึ้น ${pct} เทียบเดือนก่อน (คาดเต็มเดือน ${fmt(s.projectedFullMonth)} vs ${fmt(s.priorMonth)})`,
      `ตรวจสอบสาเหตุหมวด ${s.category} ทันที และพิจารณาระงับ/ตัดงบส่วนเกิน`);
  }

  if (p.receivables && p.receivables.nplRatioPct >= 15) {
    push('warning', 'NPL_HIGH',
      `สัดส่วนหนี้เสี่ยง (NPL) = ${p.receivables.nplRatioPct}% ของยอดคงค้าง (${fmt(p.receivables.atRiskAmount)} ${config.currency})`,
      'เร่งติดตามลูกหนี้ค้างชำระเกินเกณฑ์ และตั้งสำรองหนี้สงสัยจะสูญ');
  }

  const bigOut = p.projection.timeline.filter((t) => t.direction === 'out' && t.amount >= 500000);
  for (const b of bigOut) {
    push('info', 'LARGE_PAYMENT',
      `มีกำหนดจ่ายเงินก้อนใหญ่ ${fmt(b.amount)} ${config.currency} วันที่ ${b.date} (${b.description})`,
      'ยืนยันสภาพคล่องคงเหลือหลังชำระ และจัดลำดับความสำคัญ');
  }

  if (p.pnl.current.netProfit < 0) {
    push('warning', 'PNL_LOSS',
      `เดือนนี้ (MTD) ขาดทุน ${fmt(p.pnl.current.netProfit)} ${config.currency}`,
      'ทบทวนต้นทุนผันแปรและเป้ารายรับให้กลับมาเป็นบวก');
  }
  return alerts;
}

function fmt(n) {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(n);
}

// ---------- Top-level analysis ----------
export function analyze(data, asOfStr) {
  const asOf = parseDate(asOfStr || data.projectsMeta.as_of);
  const currentMonth = monthKey(asOf.toISOString().slice(0, 10));
  const priorMonth = prevMonthKey(currentMonth);

  const projects = data.projectsMeta.projects.map((project) => {
    const pnlCurrent = pnlForPeriod(data.transactions, project.id, currentMonth);
    const pnlPrior = pnlForPeriod(data.transactions, project.id, priorMonth);
    const cash = cashPosition(data.transactions, project, asOf);
    const projection = projectCashFlow(data.obligations, project.id, cash, asOf, config.projectionDays);
    const cost = costStructure(data.transactions, project.id, currentMonth, priorMonth, asOf);
    const receivables = receivablesRisk(data.receivables, project.id);
    const rw = runway(cash, pnlCurrent, asOf, currentMonth);

    const analysis = {
      id: project.id,
      name: project.name,
      type: project.type,
      description: project.description,
      currency: config.currency,
      currentCash: cash,
      runway: rw,
      pnl: { current: pnlCurrent, prior: pnlPrior },
      costStructure: cost,
      projection,
      receivables,
    };
    analysis.alerts = buildAlerts(analysis);
    return analysis;
  });

  // Portfolio rollup
  const portfolio = {
    asOf: asOfStr || data.projectsMeta.as_of,
    currentMonth,
    priorMonth,
    totalCash: round(sum2(projects.map((p) => ({ amount: p.currentCash })))),
    totalRevenueMTD: round(sum2(projects.map((p) => ({ amount: p.pnl.current.revenue })))),
    totalNetMTD: round(sum2(projects.map((p) => ({ amount: p.pnl.current.netProfit })))),
    projectedMinCash: round(Math.min(...projects.map((p) => p.projection.minBalance))),
    criticalAlerts: projects.reduce((a, p) => a + p.alerts.filter((x) => x.severity === 'critical').length, 0),
    totalAlerts: projects.reduce((a, p) => a + p.alerts.length, 0),
  };

  return { asOf: asOfStr || data.projectsMeta.as_of, portfolio, projects };
}

export const _internals = { pnlForPeriod, costStructure, projectCashFlow, receivablesRisk, runway };
