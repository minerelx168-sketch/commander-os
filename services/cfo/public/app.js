// CFO Command dashboard — vanilla JS front-end.
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const fmt = (n) => new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(n ?? 0);

const AGENTS = [
  { key: 'cfo', name: 'CFO', role: 'Command Layer', icon: '₿' },
  { key: 'cash', name: 'Cash Sentinel', role: 'Liquidity Radar', icon: '≈' },
  { key: 'pnl', name: 'P&L Analyst', role: 'Profit Engine', icon: '▤' },
  { key: 'risk', name: 'Risk Auditor', role: 'Exposure Watch', icon: '⚑' },
  { key: 'collect', name: 'Collections', role: 'Receivables', icon: '◔' },
  { key: 'data', name: 'Data Feed', role: 'Signal Layer', icon: '◇' },
];

const state = { analysis: null, status: null, chat: [], view: 'command' };

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.statusText);
  return res.json();
}

// ---------- tiny markdown ----------
function md(text) {
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const inline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Italic only at word boundaries so snake_case identifiers (collection_legal,
    // ANTHROPIC_API_KEY) are left untouched.
    .replace(/(^|[^\w])_([^_]+?)_(?=[^\w]|$)/g, '$1<em>$2</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>');
  const out = [];
  let inList = false;
  for (const raw of text.split('\n')) {
    const line = raw.replace(/\s+$/, '');
    if (/^#\s/.test(line)) { if (inList) { out.push('</ul>'); inList = false; } out.push(`<h1>${inline(line.slice(2))}</h1>`); }
    else if (/^##\s/.test(line)) { if (inList) { out.push('</ul>'); inList = false; } out.push(`<h2>${inline(line.slice(3))}</h2>`); }
    else if (/^\s*[-*]\s/.test(line)) { if (!inList) { out.push('<ul>'); inList = true; } out.push(`<li>${inline(line.replace(/^\s*[-*]\s/, ''))}</li>`); }
    else if (line.trim() === '') { if (inList) { out.push('</ul>'); inList = false; } }
    else { if (inList) { out.push('</ul>'); inList = false; } out.push(`<p>${inline(line)}</p>`); }
  }
  if (inList) out.push('</ul>');
  return out.join('');
}

// ---------- render pieces ----------
function renderAgents() {
  $('#agentList').innerHTML = AGENTS.map((a) => `
    <div class="agent-row">
      <span class="dot"></span>
      <div><div class="a-name">${a.name}</div><div class="a-role">${a.role}</div></div>
      <span class="a-status">working</span>
    </div>`).join('');

  $('#agentTiles').innerHTML = AGENTS.map((a, i) => `
    <div class="tile ${i === 0 ? 'active' : ''}" data-agent="${a.key}">
      <div class="tile-top">
        <div class="tile-ic">${a.icon}</div>
        <div class="tile-badge"><span class="dot"></span>working</div>
      </div>
      <div class="tile-name">${a.name}</div>
      <div class="tile-role">${a.role}</div>
    </div>`).join('');

  $$('.tile').forEach((t) => t.addEventListener('click', () => {
    $$('.tile').forEach((x) => x.classList.remove('active'));
    t.classList.add('active');
    $('#chatInput').focus();
  }));
}

function renderKpis(a) {
  const p = a.portfolio;
  const minGood = p.projectedMinCash >= (state.status?.thresholds?.minCashBuffer ?? 0);
  $('#kpis').innerHTML = `
    <div class="kpi good"><div class="kpi-label">Total Cash</div><div class="kpi-val mono">฿${fmt(p.totalCash)}</div><div class="kpi-sub">ทุกโปรเจครวมกัน</div></div>
    <div class="kpi ${p.totalNetMTD >= 0 ? 'good' : 'bad'}"><div class="kpi-label">Net P&amp;L (MTD)</div><div class="kpi-val mono">฿${fmt(p.totalNetMTD)}</div><div class="kpi-sub">รายรับ ฿${fmt(p.totalRevenueMTD)}</div></div>
    <div class="kpi ${minGood ? 'good' : 'bad'}"><div class="kpi-label">Projected Min Cash</div><div class="kpi-val mono">฿${fmt(p.projectedMinCash)}</div><div class="kpi-sub">อีก ${state.status?.thresholds?.projectionDays ?? 30} วันข้างหน้า</div></div>
    <div class="kpi ${p.criticalAlerts ? 'bad' : (p.totalAlerts ? 'warn' : 'good')}"><div class="kpi-label">Active Alerts</div><div class="kpi-val mono">${p.totalAlerts}</div><div class="kpi-sub">${p.criticalAlerts} วิกฤต</div></div>`;
}

function alertHtml(al, recurringCodes) {
  const sev = al.severity;
  const icon = sev === 'critical' ? '🔴' : sev === 'warning' ? '🟠' : '🔵';
  const recur = recurringCodes.has(al.code) ? '<span class="recur">เกิดซ้ำ</span>' : '';
  return `<div class="alert ${sev}">
    <div class="sev">${icon}</div>
    <div><div class="a-msg">${al.message}${recur}</div><div class="a-rec">↳ ${al.recommendation}</div></div>
  </div>`;
}

function renderProjects(a) {
  const recurring = new Set((state.status?.memory?.recurringAlerts || []).map((r) => r.split(':')[0]));
  $('#projectCards').innerHTML = a.projects.map((p) => {
    const c = p.pnl.current;
    const rw = p.runway.status === 'burning'
      ? `${p.runway.runwayMonths} เดือน`
      : 'เป็นบวก';
    return `<div class="card proj">
      <div class="proj-head">
        <div class="proj-name">${p.name}</div>
        <div class="proj-type">${p.type}</div>
        <div class="muted" style="margin-left:auto;font-size:11px">${p.description}</div>
      </div>
      <div class="proj-grid">
        <div class="metric"><div class="m-l">Cash on hand</div><div class="m-v mono">฿${fmt(p.currentCash)}</div></div>
        <div class="metric"><div class="m-l">Net P&amp;L (MTD)</div><div class="m-v mono ${c.netProfit >= 0 ? 'pos' : 'neg'}">฿${fmt(c.netProfit)}</div></div>
        <div class="metric"><div class="m-l">Runway</div><div class="m-v mono">${rw}</div></div>
        <div class="metric"><div class="m-l">Min cash (${p.projection.horizonDays}d)</div><div class="m-v mono ${p.projection.minBalance >= (state.status?.thresholds?.minCashBuffer ?? 0) ? 'pos' : 'neg'}">฿${fmt(p.projection.minBalance)}</div></div>
      </div>
      ${p.alerts.length ? `<div class="proj-alerts">${p.alerts.map((al) => alertHtml(al, recurring)).join('')}</div>` : '<div class="proj-alerts"><div class="muted" style="font-size:12px">ไม่มีสัญญาณเตือน ✅</div></div>'}
    </div>`;
  }).join('');
}

async function loadBrief() {
  $('#briefBody').innerHTML = '<span class="muted">CFO is typing ●●●</span>';
  try {
    const data = await api('/api/brief');
    $('#briefBody').innerHTML = md(data.brief.text);
    const src = $('#briefSource');
    src.textContent = data.brief.source === 'claude' ? 'Claude' : 'deterministic';
    src.className = 'chip ' + (data.brief.source === 'claude' ? 'claude' : 'fallback');
  } catch (e) {
    $('#briefBody').innerHTML = `<p class="muted">โหลด brief ไม่สำเร็จ: ${e.message}</p>`;
  }
}

async function loadAll() {
  state.status = await api('/api/status');
  state.analysis = await api('/api/analysis');
  const conn = $('#connState');
  conn.textContent = state.status.claudeConnected ? '● Claude connected' : '● offline (fallback)';
  conn.className = 'conn-pill ' + (state.status.claudeConnected ? 'on' : 'off');
  $('#modelLine').textContent = `model: ${state.status.model} · cron: ${state.status.monitorCron}`;
  $('#chatStatus').textContent = state.status.claudeConnected ? '● online' : '● offline';
  renderKpis(state.analysis);
  renderProjects(state.analysis);
  loadBrief();
}

// ---------- chat ----------
function pushMsg(role, text, cls = '') {
  const log = $('#chatLog');
  const div = document.createElement('div');
  div.className = `msg ${role === 'user' ? 'user' : 'bot'} ${cls}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

async function sendChat() {
  const input = $('#chatInput');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  input.style.height = 'auto';
  pushMsg('user', text);
  state.chat.push({ role: 'user', content: text });
  const typing = pushMsg('bot', 'CFO is typing ●●●', 'typing');
  $('#chatSend').disabled = true;
  try {
    const reply = await api('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, history: state.chat.slice(0, -1) }),
    });
    typing.remove();
    pushMsg('bot', reply.text);
    state.chat.push({ role: 'assistant', content: reply.text });
  } catch (e) {
    typing.remove();
    pushMsg('bot', `ผิดพลาด: ${e.message}`);
  } finally {
    $('#chatSend').disabled = false;
  }
}

// ---------- init ----------
function init() {
  renderAgents();
  loadAll();

  $('#refreshBrief').addEventListener('click', () => { loadAll(); });
  $('#chatSend').addEventListener('click', sendChat);
  const input = $('#chatInput');
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });

  $$('.nav-item').forEach((n) => n.addEventListener('click', () => {
    $$('.nav-item').forEach((x) => x.classList.remove('active'));
    n.classList.add('active');
    const v = n.dataset.view;
    // Lightweight: focus relevant area; all data already on the command view.
    if (v === 'command') window.scrollTo({ top: 0, behavior: 'smooth' });
    else document.querySelector('#projectCards')?.scrollIntoView({ behavior: 'smooth' });
    if (v === 'cashflow') $('#chatInput').value = 'สรุปกระแสเงินสดและ runway ของทุกโปรเจค';
    if (v === 'pnl') $('#chatInput').value = 'สรุป P&L รายโปรเจคเดือนนี้';
    if (v === 'alerts') $('#chatInput').value = 'มี red flag อะไรบ้างที่ต้องตัดสินใจวันนี้';
    if (v === 'receivables') $('#chatInput').value = 'วิเคราะห์ความเสี่ยงลูกหนี้พอร์ตสินเชื่อ';
  }));

  // Seed greeting
  pushMsg('bot', 'CFO Command พร้อมทำงาน — เฝ้าระวังสภาพคล่องและ P&L ของทุกโปรเจคแบบเรียลไทม์ พิมพ์คำสั่งหรือคำถามได้เลย');
}

init();
