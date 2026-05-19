'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let currentStrategyId = null;
let currentTicker = null;
let equityChart = null;
let drawdownChart = null;
let pnlChart = null;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const tickerInput   = $('tickerInput');
const analyzeBtn    = $('analyzeBtn');
const statusLog     = $('status-log');
const strategyPanel = $('strategy-panel');
const backtestPanel = $('backtest-panel');
const historySection= $('history-section');
const runBtn        = $('runBtn');

// ── Init ──────────────────────────────────────────────────────────────────────
analyzeBtn.addEventListener('click', () => {
  const ticker = tickerInput.value.trim().toUpperCase();
  if (!ticker) return;
  startAnalysis(ticker);
});

tickerInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') analyzeBtn.click();
});

runBtn.addEventListener('click', async () => {
  if (!currentStrategyId) return;
  runBtn.disabled = true;
  clearStatusLog();
  appendLog('backtest', 'Re-running strategy with fresh data…');
  await streamRun(`/api/run/${currentStrategyId}`);
  runBtn.disabled = false;
});

// ── Pipeline entry ─────────────────────────────────────────────────────────────
function startAnalysis(ticker) {
  currentTicker = ticker;
  analyzeBtn.disabled = true;
  clearStatusLog();
  strategyPanel.hidden = true;
  backtestPanel.hidden = true;

  const es = new EventSource(`/api/analyze?ticker=${ticker}`);

  es.onmessage = async e => {
    const data = JSON.parse(e.data);
    appendLog(data.stage, data.message, data.stage === 'error');

    if (data.stage === 'complete') {
      es.close();
      analyzeBtn.disabled = false;
      await loadStrategy(data.strategy_id);
      await loadBacktest(data.backtest_id);
      await loadHistory(ticker);
    }
    if (data.stage === 'error') {
      es.close();
      analyzeBtn.disabled = false;
    }
  };

  es.onerror = () => {
    appendLog('error', 'Connection lost.', true);
    es.close();
    analyzeBtn.disabled = false;
  };
}

async function streamRun(url) {
  return new Promise(resolve => {
    const es = new EventSource(url);
    es.onmessage = async e => {
      const data = JSON.parse(e.data);
      appendLog(data.stage, data.message, data.stage === 'error');
      if (data.stage === 'complete') {
        es.close();
        await loadBacktest(data.backtest_id);
        resolve();
      }
      if (data.stage === 'error') { es.close(); resolve(); }
    };
    es.onerror = () => { es.close(); resolve(); };
  });
}

// ── Status log ─────────────────────────────────────────────────────────────────
function appendLog(stage, message, isError = false) {
  const entry = document.createElement('div');
  entry.className = `log-entry${isError ? ' error' : stage === 'complete' ? ' complete' : ''}`;
  entry.innerHTML = `<span class="log-stage">${stage}</span><span>${escHtml(message)}</span>`;
  statusLog.appendChild(entry);
  entry.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function clearStatusLog() {
  statusLog.innerHTML = '';
}

// ── Load strategy ──────────────────────────────────────────────────────────────
async function loadStrategy(id) {
  currentStrategyId = id;
  const data = await fetch(`/api/strategies/${id}`).then(r => r.json());

  $('strategyName').textContent = data.name || 'Generated Strategy';
  $('strategyExplanation').textContent = data.description || '';

  // Review badge
  const badge = $('reviewBadge');
  if (data.approved !== undefined) {
    const ok = !!data.approved;
    badge.innerHTML = `
      <div class="review-badge ${ok ? 'approved' : 'rejected'}">
        ${ok ? '✓' : '✗'} Code Review
        <span class="score">${data.confidence ?? '—'}/100</span>
        · ${(data.issues_found || []).length} issues
        · ${data.iterations ?? 0} iteration(s)
      </div>`;
  } else {
    badge.innerHTML = '';
  }

  // Parameters table
  const params = data.parameters || {};
  const paramTable = $('paramTable');
  if (Object.keys(params).length) {
    paramTable.innerHTML =
      '<thead><tr><th>Parameter</th><th>Default</th></tr></thead><tbody>' +
      Object.entries(params).map(([k, v]) =>
        `<tr><td>${escHtml(k)}</td><td>${escHtml(String(v))}</td></tr>`
      ).join('') +
      '</tbody>';
  } else {
    paramTable.innerHTML = '';
  }

  // Source code
  const codeEl = $('sourceCode');
  codeEl.textContent = data.source_code || '';
  hljs.highlightElement(codeEl);

  strategyPanel.hidden = false;
}

// ── Load backtest ──────────────────────────────────────────────────────────────
async function loadBacktest(id) {
  const data = await fetch(`/api/backtest/${id}`).then(r => r.json());
  renderMetrics(data.metrics);
  renderEquityCurve(data.equity_curve, data.metrics.buy_hold_return_pct);
  renderDrawdown(data.equity_curve);
  renderPnlChart(data.trade_log);
  renderTradeLog(data.trade_log);
  $('narrative').innerHTML = marked.parse(data.explanation || '');
  backtestPanel.hidden = false;
}

// ── Metrics cards ──────────────────────────────────────────────────────────────
function renderMetrics(m) {
  const cards = [
    { label: 'Total Return', value: fmt(m.total_return_pct, '%'), pos: m.total_return_pct > 0, sub: `B&H: ${fmt(m.buy_hold_return_pct, '%')}` },
    { label: 'CAGR', value: fmt(m.cagr_pct, '%'), pos: m.cagr_pct > 0 },
    { label: 'Sharpe Ratio', value: fmt(m.sharpe), pos: m.sharpe > 1, neg: m.sharpe < 0 },
    { label: 'Max Drawdown', value: fmt(m.max_drawdown_pct, '%'), neg: true },
    { label: 'Win Rate', value: fmt(m.win_rate_pct, '%'), pos: m.win_rate_pct > 50 },
    { label: 'Profit Factor', value: m.profit_factor ? fmt(m.profit_factor) : '—', pos: m.profit_factor > 1 },
    { label: 'Trades', value: m.num_trades, pos: false, sub: `Exposure: ${fmt(m.exposure_pct, '%')}` },
  ];
  $('metricsRow').innerHTML = cards.map(c => `
    <div class="metric-card">
      <div class="label">${c.label}</div>
      <div class="value ${c.neg ? 'neg' : c.pos ? 'pos' : 'neutral'}">${c.value}</div>
      ${c.sub ? `<div class="sub">${c.sub}</div>` : ''}
    </div>`).join('');
}

function fmt(val, suffix = '') {
  if (val === null || val === undefined) return '—';
  return `${Number(val).toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`;
}

// ── Equity curve chart ─────────────────────────────────────────────────────────
function renderEquityCurve(equityCurve, bhReturnPct) {
  if (equityChart) equityChart.destroy();
  const dates = equityCurve.map(p => p.date);
  const equities = equityCurve.map(p => p.equity);
  const initial = equities[0] || 10000;

  // Buy & hold baseline: linear from 0% to bhReturnPct
  const bhValues = equities.map((_, i) =>
    initial * (1 + (bhReturnPct / 100) * (i / (equities.length - 1)))
  );

  equityChart = new Chart($('equityChart'), {
    type: 'line',
    data: {
      labels: dates,
      datasets: [
        {
          label: 'Strategy', data: equities,
          borderColor: '#6c8eff', borderWidth: 2,
          pointRadius: 0, fill: false, tension: 0.3,
        },
        {
          label: 'Buy & Hold', data: bhValues,
          borderColor: '#8892a4', borderWidth: 1.5,
          borderDash: [5, 5], pointRadius: 0, fill: false, tension: 0,
        },
      ],
    },
    options: chartOptions('$'),
  });
}

// ── Drawdown chart ─────────────────────────────────────────────────────────────
function renderDrawdown(equityCurve) {
  if (drawdownChart) drawdownChart.destroy();
  const equities = equityCurve.map(p => p.equity);
  const dates = equityCurve.map(p => p.date);

  let peak = equities[0];
  const dd = equities.map(v => {
    peak = Math.max(peak, v);
    return peak > 0 ? ((v - peak) / peak) * 100 : 0;
  });

  drawdownChart = new Chart($('drawdownChart'), {
    type: 'line',
    data: {
      labels: dates,
      datasets: [{
        label: 'Drawdown %', data: dd,
        borderColor: '#f87171', backgroundColor: 'rgba(248,113,113,0.15)',
        borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.2,
      }],
    },
    options: chartOptions('%'),
  });
}

// ── P&L distribution chart ─────────────────────────────────────────────────────
function renderPnlChart(trades) {
  if (pnlChart) pnlChart.destroy();
  if (!trades || !trades.length) return;

  const pnls = trades.map(t => t.pnl);
  const colors = pnls.map(v => v >= 0 ? 'rgba(52,211,153,0.8)' : 'rgba(248,113,113,0.8)');

  pnlChart = new Chart($('pnlChart'), {
    type: 'bar',
    data: {
      labels: trades.map((_, i) => `T${i + 1}`),
      datasets: [{
        label: 'P&L $',
        data: pnls,
        backgroundColor: colors,
        borderRadius: 3,
      }],
    },
    options: {
      ...chartOptions('$'),
      plugins: { legend: { display: false } },
    },
  });
}

// ── Trade log table ────────────────────────────────────────────────────────────
function renderTradeLog(trades) {
  const tbody = $('tradeLog').querySelector('tbody');
  if (!trades || !trades.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted)">No trades executed</td></tr>';
    return;
  }
  tbody.innerHTML = trades.map((t, i) => `
    <tr>
      <td>${i + 1}</td>
      <td>${t.entry_date}</td>
      <td>${t.exit_date}</td>
      <td>$${fmt(t.entry_price)}</td>
      <td>$${fmt(t.exit_price)}</td>
      <td>${t.size}</td>
      <td class="${t.pnl >= 0 ? 'td-pos' : 'td-neg'}">$${fmt(t.pnl)}</td>
      <td class="${t.return_pct >= 0 ? 'td-pos' : 'td-neg'}">${fmt(t.return_pct)}%</td>
      <td>${t.bars_held}d</td>
    </tr>`).join('');
}

// ── History table ──────────────────────────────────────────────────────────────
async function loadHistory(ticker) {
  const runs = await fetch(`/api/history/${ticker}`).then(r => r.json());
  if (!runs.length) return;

  $('historyTicker').textContent = ticker;
  const tbody = $('history-table').querySelector('tbody');
  tbody.innerHTML = runs.map(r => {
    const m = r.metrics || {};
    const ret = m.total_return_pct ?? '—';
    return `<tr style="cursor:pointer" onclick="loadBacktest(${r.id})">
      <td>${(r.created_at || '').slice(0, 10)}</td>
      <td>${escHtml(r.strategy_name || '')}</td>
      <td class="${ret >= 0 ? 'td-pos' : 'td-neg'}">${fmt(ret)}%</td>
      <td>${fmt(m.sharpe)}</td>
      <td class="td-neg">${fmt(m.max_drawdown_pct)}%</td>
    </tr>`;
  }).join('');
  historySection.hidden = false;
}

// ── Chart defaults ─────────────────────────────────────────────────────────────
function chartOptions(unit) {
  return {
    responsive: true,
    maintainAspectRatio: true,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        labels: { color: '#8892a4', font: { size: 11 } },
      },
      tooltip: {
        backgroundColor: '#1a1d27',
        borderColor: '#2d3148',
        borderWidth: 1,
        titleColor: '#e2e8f0',
        bodyColor: '#8892a4',
        callbacks: {
          label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)}${unit}`,
        },
      },
    },
    scales: {
      x: {
        ticks: { color: '#8892a4', maxTicksLimit: 8, font: { size: 10 } },
        grid: { color: '#1e2235' },
      },
      y: {
        ticks: { color: '#8892a4', font: { size: 10 } },
        grid: { color: '#1e2235' },
      },
    },
  };
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
