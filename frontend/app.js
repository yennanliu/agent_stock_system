'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let currentStrategyId = null;
let currentBacktestId = null;
let activeHistoryId   = null;
let equityChart = null, drawdownChart = null, pnlChart = null;
let _candleChart = null;    // lightweight-charts instance
let _originalParams = {};   // original params for reset
let _optimizedParams = {};  // best params from optimize run

// ── DOM ───────────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const tickerInput        = $('tickerInput');
const analyzeBtn         = $('analyzeBtn');
const strategyTypeSelect = $('strategyTypeSelect');
const indicatorsSelect   = $('indicatorsSelect');
const periodSelect       = $('periodSelect');
const statusLog          = $('status-log');
const strategyPanel      = $('strategy-panel');
const backtestPanel      = $('backtest-panel');
const runBtn             = $('runBtn');
const downloadBtn        = $('downloadBtn');
const runIdBadge         = $('runIdBadge');
const runSourceBtn       = $('runSourceBtn');
const runDataBtn         = $('runDataBtn');
const historyList        = $('historyList');
const refreshHistBtn     = $('refreshHistoryBtn');
const runWithParamsBtn   = $('runWithParamsBtn');
const resetParamsBtn     = $('resetParamsBtn');
const paramActions       = $('paramActions');
const optimizeBtn        = $('optimizeBtn');
const applyOptimizedBtn  = $('applyOptimizedBtn');

// ── Boot ──────────────────────────────────────────────────────────────────────
refreshHistoryList();

// ── Event wiring ──────────────────────────────────────────────────────────────
analyzeBtn.addEventListener('click', () => {
  const ticker = tickerInput.value.trim().toUpperCase();
  if (ticker) startAnalysis(ticker);
});
tickerInput.addEventListener('keydown', e => { if (e.key === 'Enter') analyzeBtn.click(); });
runBtn.addEventListener('click', () => rerunStrategy());
refreshHistBtn.addEventListener('click', refreshHistoryList);
runWithParamsBtn.addEventListener('click', () => rerunWithParams());
resetParamsBtn.addEventListener('click', () => resetParams());
optimizeBtn.addEventListener('click', () => runOptimize());
applyOptimizedBtn.addEventListener('click', () => applyOptimized());

// ── Analysis pipeline ─────────────────────────────────────────────────────────
function startAnalysis(ticker) {
  analyzeBtn.disabled = true;
  clearStatusLog();
  strategyPanel.hidden = true;
  backtestPanel.hidden = true;

  const strategyType = strategyTypeSelect.value;
  const indicators   = indicatorsSelect.value;
  const period       = periodSelect.value;
  const es = new EventSource(
    `/api/analyze?ticker=${ticker}&strategy_type=${strategyType}&indicators=${indicators}&period=${period}`
  );
  es.onmessage = async e => {
    const data = JSON.parse(e.data);
    if (data.stage === 'ping') return;
    appendLog(data.stage, data.message, data.stage === 'error');

    if (data.stage === 'complete') {
      await loadStrategy(data.strategy_id);
      await loadBacktest(data.backtest_id);
      setActiveHistory(data.backtest_id);
      refreshHistoryList();
    }
    if (data.stage === 'critique' && data.critique) {
      renderCritiquePreview(data.critique, data.changes_summary);
    }
    if (data.stage === 'critique_complete') {
      es.close();
      analyzeBtn.disabled = false;
      await loadStrategy(data.strategy_id);
      await loadBacktest(data.backtest_id);
      setActiveHistory(data.backtest_id);
      refreshHistoryList();
      appendLog('critique_complete', `Revised strategy loaded. Compare with original run #${data.original_backtest_id}.`);
    }
    if (data.stage === 'error') { es.close(); analyzeBtn.disabled = false; }
  };
  es.onerror = () => {
    appendLog('error', 'Connection lost.', true);
    es.close(); analyzeBtn.disabled = false;
  };
}

async function rerunStrategy() {
  if (!currentStrategyId) return;
  runBtn.disabled = true;
  clearStatusLog();

  const es = new EventSource(`/api/run/${currentStrategyId}`);
  es.onmessage = async e => {
    const data = JSON.parse(e.data);
    appendLog(data.stage, data.message, data.stage === 'error');
    if (data.stage === 'complete') {
      es.close(); runBtn.disabled = false;
      await loadBacktest(data.backtest_id);
      setActiveHistory(data.backtest_id);
      refreshHistoryList();
    }
    if (data.stage === 'error') { es.close(); runBtn.disabled = false; }
  };
  es.onerror = () => { es.close(); runBtn.disabled = false; };
}

function rerunWithParams() {
  if (!currentStrategyId) return;
  const overrides = {};
  document.querySelectorAll('.param-input').forEach(input => {
    const name = input.dataset.param;
    const raw  = input.value.trim();
    if (raw !== '') overrides[name] = raw.includes('.') ? parseFloat(raw) : parseInt(raw, 10);
  });
  const period = periodSelect.value;
  runWithParamsBtn.disabled = true;
  clearStatusLog();

  const paramsJson = encodeURIComponent(JSON.stringify(overrides));
  const es = new EventSource(
    `/api/strategies/${currentStrategyId}/run-with-params?params=${paramsJson}&period=${period}`
  );
  es.onmessage = async e => {
    const data = JSON.parse(e.data);
    appendLog(data.stage, data.message, data.stage === 'error');
    if (data.stage === 'complete') {
      es.close(); runWithParamsBtn.disabled = false;
      await loadBacktest(data.backtest_id);
      setActiveHistory(data.backtest_id);
      refreshHistoryList();
    }
    if (data.stage === 'error') { es.close(); runWithParamsBtn.disabled = false; }
  };
  es.onerror = () => { es.close(); runWithParamsBtn.disabled = false; };
}

function resetParams() {
  document.querySelectorAll('.param-input').forEach(input => {
    const orig = _originalParams[input.dataset.param];
    if (orig !== undefined) input.value = orig;
  });
}

// ── History sidebar ───────────────────────────────────────────────────────────
async function refreshHistoryList() {
  const runs = await fetch('/api/runs').then(r => r.json()).catch(() => []);
  renderHistoryList(runs);
}

function renderHistoryList(runs) {
  if (!runs.length) {
    historyList.innerHTML = '<div class="history-empty">No runs yet. Analyze a ticker to get started.</div>';
    return;
  }
  historyList.innerHTML = runs.map(r => {
    const m = r.metrics || {};
    const ret = m.total_return_pct;
    const retStr = ret !== undefined ? `${ret >= 0 ? '+' : ''}${fmt(ret)}%` : '—';
    const retCls = ret !== undefined ? (ret >= 0 ? 'pos' : 'neg') : '';
    const date = (r.created_at || '').slice(0, 10);
    return `<div class="history-item${r.id === activeHistoryId ? ' active' : ''}"
                 data-run-id="${r.id}" data-strat-id="${r.strategy_id}"
                 onclick="onHistoryClick(${r.id}, ${r.strategy_id})">
      <div class="hi-ticker">${escHtml(r.ticker)}</div>
      <div class="hi-name">${escHtml(r.strategy_name || '')}</div>
      <div class="hi-meta">
        <span class="hi-ret ${retCls}">${retStr}</span>
        <span>${date}</span>
      </div>
    </div>`;
  }).join('');
}

async function onHistoryClick(runId, stratId) {
  setActiveHistory(runId);
  clearStatusLog();
  await loadStrategy(stratId);
  await loadBacktest(runId);
}

function setActiveHistory(runId) {
  activeHistoryId = runId;
  document.querySelectorAll('.history-item').forEach(el => {
    el.classList.toggle('active', parseInt(el.dataset.runId) === runId);
  });
}

// ── Load strategy ─────────────────────────────────────────────────────────────
async function loadStrategy(id) {
  currentStrategyId = id;
  const data = await fetch(`/api/strategies/${id}`).then(r => r.json());

  $('strategyTicker').textContent = data.ticker || '';
  $('strategyDate').textContent   = (data.created_at || '').slice(0, 10);
  $('strategyName').textContent   = data.name || 'Generated Strategy';
  $('strategyExplanation').textContent = data.description || '';

  // Download link
  downloadBtn.href = `/api/strategies/${id}/download`;
  downloadBtn.download = `${data.ticker}_${data.name}_${id}.py`;

  // Review badge
  const badge = $('reviewBadge');
  if (data.approved !== undefined) {
    const ok = !!data.approved;
    badge.innerHTML = `
      <div class="review-badge ${ok ? 'approved' : 'rejected'}">
        ${ok ? '✓' : '✗'} Code Review
        <span class="score">${data.confidence ?? '—'}/100</span>
        · ${(data.issues_found || []).length} issues · ${data.iterations ?? 0} iter
      </div>`;
  } else {
    badge.innerHTML = '';
  }

  // Parameters (editable)
  const params = data.parameters || {};
  _originalParams = { ...params };
  const paramTable = $('paramTable');
  if (Object.keys(params).length) {
    paramTable.innerHTML =
      '<thead><tr><th>Parameter</th><th>Value</th></tr></thead><tbody>' +
      Object.entries(params).map(([k, v]) =>
        `<tr><td>${escHtml(k)}</td><td>` +
        `<input class="param-input" data-param="${escHtml(k)}" type="number" value="${escHtml(String(v))}" step="any" /></td></tr>`
      ).join('') + '</tbody>';
    paramActions.hidden = false;
  } else {
    paramTable.innerHTML = '';
    paramActions.hidden = true;
  }

  // Source code
  const codeEl = $('sourceCode');
  codeEl.textContent = data.source_code || '';
  hljs.highlightElement(codeEl);

  strategyPanel.hidden = false;
}

// ── Load backtest ─────────────────────────────────────────────────────────────
async function loadBacktest(id) {
  currentBacktestId = id;
  const data = await fetch(`/api/backtest/${id}`).then(r => r.json());
  renderMetrics(data.metrics);
  renderWalkforward(data.walkforward);
  renderEquityCurve(data.equity_curve, data.metrics.buy_hold_return_pct);
  renderDrawdown(data.equity_curve);
  renderPnlChart(data.trade_log);
  renderTradeLog(data.trade_log);
  $('narrative').innerHTML = marked.parse(data.explanation || '');

  // Run ID badge + download buttons
  const ticker = data.ticker || '';
  runIdBadge.textContent = `Run #${id}  ·  strategies/${id}/${ticker}.py`;
  runIdBadge.title = `Code saved at strategies/${id}/${ticker}.py`;

  runSourceBtn.href = `/api/backtest/${id}/source`;
  runSourceBtn.download = `run_${id}_${ticker}.py`;
  runSourceBtn.hidden = !data.source_code;

  runDataBtn.href = `/api/backtest/${id}/rawdata`;
  runDataBtn.download = `run_${id}_${ticker}_raw.csv`;
  runDataBtn.hidden = !data.raw_data_path;

  // Candlestick chart (uses saved raw OHLCV CSV via /api/backtest/{id}/ohlcv)
  if (data.raw_data_path) {
    await renderCandleChart(id, data.signals || []);
  } else {
    $('signalChartCard').hidden = true;
  }

  backtestPanel.hidden = false;
}

// ── Candlestick chart (lightweight-charts) ────────────────────────────────────
async function renderCandleChart(runId, signals) {
  const container = $('candleChart');
  if (_candleChart) { _candleChart.remove(); _candleChart = null; }

  let ohlcv = [];
  try {
    ohlcv = await fetch(`/api/backtest/${runId}/ohlcv`).then(r => r.json());
  } catch (_) { $('signalChartCard').hidden = true; return; }
  if (!ohlcv.length) { $('signalChartCard').hidden = true; return; }

  $('signalChartCard').hidden = false;
  container.innerHTML = '';

  const chart = LightweightCharts.createChart(container, {
    width:  container.clientWidth,
    height: 320,
    layout: { background: { color: '#13161f' }, textColor: '#8892a4' },
    grid:   { vertLines: { color: '#1e2235' }, horzLines: { color: '#1e2235' } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: '#2a2f4a' },
    timeScale: { borderColor: '#2a2f4a', timeVisible: true },
  });
  _candleChart = chart;

  const candleSeries = chart.addCandlestickSeries({
    upColor:   '#3de8a0', downColor: '#ff6b6b',
    borderUpColor: '#3de8a0', borderDownColor: '#ff6b6b',
    wickUpColor:   '#3de8a0', wickDownColor:   '#ff6b6b',
  });
  candleSeries.setData(ohlcv);

  // Buy/sell markers
  if (signals && signals.length) {
    const markers = signals.map(s => ({
      time:     s.date,
      position: s.type === 'buy' ? 'belowBar' : 'aboveBar',
      color:    s.type === 'buy' ? '#3de8a0'  : '#ff6b6b',
      shape:    s.type === 'buy' ? 'arrowUp'  : 'arrowDown',
      text:     s.type === 'buy' ? 'B'        : 'S',
    })).sort((a, b) => a.time < b.time ? -1 : 1);
    candleSeries.setMarkers(markers);
  }

  chart.timeScale().fitContent();

  // Resize on window resize
  window.addEventListener('resize', () => {
    if (_candleChart) chart.resize(container.clientWidth, 320);
  }, { once: true });
}

// ── Optimize ──────────────────────────────────────────────────────────────────
function runOptimize() {
  if (!currentStrategyId) return;
  optimizeBtn.disabled = true;
  const period = periodSelect.value;

  const es = new EventSource(`/api/strategies/${currentStrategyId}/optimize?period=${period}`);
  es.onmessage = e => {
    const data = JSON.parse(e.data);
    appendLog(data.stage || 'optimize', data.message, data.stage === 'error');
    if (data.stage === 'optimize_done') {
      es.close(); optimizeBtn.disabled = false;
      renderOptimizeResults(data.best_params, data.metrics);
    }
    if (data.stage === 'error') { es.close(); optimizeBtn.disabled = false; }
  };
  es.onerror = () => { es.close(); optimizeBtn.disabled = false; };
}

function renderOptimizeResults(bestParams, metrics) {
  const card = $('optimizeCard');
  if (!bestParams || !Object.keys(bestParams).length) {
    card.hidden = true; return;
  }
  _optimizedParams = bestParams;
  card.hidden = false;
  $('optimizeBadge').textContent = `Maximize: Sharpe Ratio`;

  $('optimizeTable').innerHTML = `
    <table class="wf-table">
      <thead><tr><th>Parameter</th><th>Original</th><th>Optimised</th></tr></thead>
      <tbody>
        ${Object.entries(bestParams).map(([k, v]) => {
          const orig = _originalParams[k];
          const changed = orig !== undefined && orig !== v;
          return `<tr>
            <td>${escHtml(k)}</td>
            <td>${orig !== undefined ? orig : '—'}</td>
            <td class="${changed ? 'td-pos' : ''}">${v}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
    ${metrics ? `<div class="wf-split-note">Optimised Sharpe: ${fmt(metrics.sharpe)} · Return: ${fmt(metrics.total_return_pct)}%</div>` : ''}`;

  applyOptimizedBtn.hidden = false;
}

function applyOptimized() {
  // Fill optimized values into the editable param inputs, then trigger re-run
  Object.entries(_optimizedParams).forEach(([k, v]) => {
    const input = document.querySelector(`.param-input[data-param="${k}"]`);
    if (input) input.value = v;
  });
  rerunWithParams();
}

// ── Critique preview ──────────────────────────────────────────────────────────
function renderCritiquePreview(critique, changesSummary) {
  let el = $('critiquePreview');
  if (!el) {
    el = document.createElement('div');
    el.id = 'critiquePreview';
    el.className = 'walkforward-card';
    $('backtest-panel').appendChild(el);
  }
  el.hidden = false;
  el.innerHTML = `<h4>Self-Critique <span class="wf-badge">${escHtml(changesSummary || '')}</span></h4>
    <div class="narrative" style="font-size:13px">${marked.parse(critique)}</div>`;
}

// ── Metrics ───────────────────────────────────────────────────────────────────
function renderMetrics(m) {
  const cards = [
    { label: 'Total Return', value: fmt(m.total_return_pct, '%'), pos: m.total_return_pct > 0, sub: `B&H: ${fmt(m.buy_hold_return_pct, '%')}` },
    { label: 'CAGR',         value: fmt(m.cagr_pct, '%'),         pos: m.cagr_pct > 0 },
    { label: 'Sharpe',       value: fmt(m.sharpe),                 pos: m.sharpe > 1, neg: m.sharpe < 0 },
    { label: 'Max Drawdown', value: fmt(m.max_drawdown_pct, '%'),  neg: true },
    { label: 'Win Rate',     value: fmt(m.win_rate_pct, '%'),      pos: m.win_rate_pct > 50 },
    { label: 'Profit Factor',value: m.profit_factor ? fmt(m.profit_factor) : '—', pos: (m.profit_factor || 0) > 1 },
    { label: 'Trades',       value: m.num_trades,                  sub: `Exposure: ${fmt(m.exposure_pct, '%')}` },
  ];
  $('metricsRow').innerHTML = cards.map(c => `
    <div class="metric-card">
      <div class="label">${c.label}</div>
      <div class="value ${c.neg ? 'neg' : c.pos ? 'pos' : 'neutral'}">${c.value}</div>
      ${c.sub ? `<div class="sub">${c.sub}</div>` : ''}
    </div>`).join('');
}

// ── Walk-forward table ────────────────────────────────────────────────────────
function renderWalkforward(wf) {
  const card = $('walkforwardCard');
  if (!wf || !wf.in_sample) { card.hidden = true; return; }
  card.hidden = false;

  const ins  = wf.in_sample;
  const outs = wf.out_sample;

  const rows = [
    ['Total Return %',    ins.total_return_pct,   outs.total_return_pct,   true],
    ['CAGR %',           ins.cagr_pct,            outs.cagr_pct,            true],
    ['Sharpe',           ins.sharpe,               outs.sharpe,               true],
    ['Max Drawdown %',   ins.max_drawdown_pct,     outs.max_drawdown_pct,     false],
    ['Win Rate %',       ins.win_rate_pct,          outs.win_rate_pct,          true],
    ['# Trades',         ins.num_trades,            outs.num_trades,            null],
  ];

  $('walkforwardTable').innerHTML = `
    <table class="wf-table">
      <thead><tr>
        <th>Metric</th>
        <th>In-sample<br><small>first 70%</small></th>
        <th>Out-of-sample<br><small>last 30%</small></th>
        <th>Δ</th>
      </tr></thead>
      <tbody>
        ${rows.map(([label, iv, ov, higherGood]) => {
          const delta = (iv !== undefined && ov !== undefined) ? (ov - iv) : null;
          const deltaStr = delta !== null ? `${delta >= 0 ? '+' : ''}${fmt(delta)}` : '—';
          const deltaCls = delta === null || higherGood === null ? '' : (delta >= 0 === higherGood ? 'td-pos' : 'td-neg');
          return `<tr>
            <td>${label}</td>
            <td>${fmt(iv)}</td>
            <td>${fmt(ov)}</td>
            <td class="${deltaCls}">${deltaStr}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
    <div class="wf-split-note">Split date: ${wf.split_date || '—'}</div>`;
}

// ── Charts ────────────────────────────────────────────────────────────────────
function renderEquityCurve(equityCurve, bhReturnPct) {
  if (equityChart) equityChart.destroy();
  const dates    = equityCurve.map(p => p.date);
  const equities = equityCurve.map(p => p.equity);
  const initial  = equities[0] || 10000;
  const bhValues = equities.map((_, i) =>
    initial * (1 + (bhReturnPct / 100) * (i / (equities.length - 1 || 1)))
  );
  equityChart = new Chart($('equityChart'), {
    type: 'line',
    data: {
      labels: dates,
      datasets: [
        { label: 'Strategy',    data: equities, borderColor: '#6c8eff', borderWidth: 2, pointRadius: 0, fill: false, tension: 0.3 },
        { label: 'Buy & Hold', data: bhValues,  borderColor: '#8892a4', borderWidth: 1.5, borderDash: [5,5], pointRadius: 0, fill: false },
      ],
    },
    options: chartOptions('$'),
  });
}

function renderDrawdown(equityCurve) {
  if (drawdownChart) drawdownChart.destroy();
  const equities = equityCurve.map(p => p.equity);
  const dates    = equityCurve.map(p => p.date);
  let peak = equities[0];
  const dd = equities.map(v => { peak = Math.max(peak, v); return peak > 0 ? ((v - peak) / peak) * 100 : 0; });
  drawdownChart = new Chart($('drawdownChart'), {
    type: 'line',
    data: {
      labels: dates,
      datasets: [{ label: 'Drawdown %', data: dd, borderColor: '#f87171', backgroundColor: 'rgba(248,113,113,0.15)', borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.2 }],
    },
    options: chartOptions('%'),
  });
}

function renderPnlChart(trades) {
  if (pnlChart) pnlChart.destroy();
  if (!trades || !trades.length) return;
  const pnls   = trades.map(t => t.pnl);
  const colors = pnls.map(v => v >= 0 ? 'rgba(52,211,153,0.8)' : 'rgba(248,113,113,0.8)');
  pnlChart = new Chart($('pnlChart'), {
    type: 'bar',
    data: {
      labels: trades.map((_, i) => `T${i + 1}`),
      datasets: [{ label: 'P&L $', data: pnls, backgroundColor: colors, borderRadius: 3 }],
    },
    options: { ...chartOptions('$'), plugins: { legend: { display: false } } },
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

// ── Status log ─────────────────────────────────────────────────────────────────
function appendLog(stage, message, isError = false) {
  const entry = document.createElement('div');
  entry.className = `log-entry${isError ? ' error' : stage === 'complete' ? ' complete' : ''}`;
  entry.innerHTML = `<span class="log-stage">${stage}</span><span>${escHtml(message)}</span>`;
  statusLog.appendChild(entry);
  entry.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
function clearStatusLog() { statusLog.innerHTML = ''; }

// ── Chart defaults ─────────────────────────────────────────────────────────────
function chartOptions(unit) {
  return {
    responsive: true, maintainAspectRatio: true,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { labels: { color: '#8892a4', font: { size: 11 } } },
      tooltip: {
        backgroundColor: '#1a1d27', borderColor: '#2d3148', borderWidth: 1,
        titleColor: '#e2e8f0', bodyColor: '#8892a4',
        callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)}${unit}` },
      },
    },
    scales: {
      x: { ticks: { color: '#8892a4', maxTicksLimit: 8, font: { size: 10 } }, grid: { color: '#1e2235' } },
      y: { ticks: { color: '#8892a4', font: { size: 10 } }, grid: { color: '#1e2235' } },
    },
  };
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function fmt(val, suffix = '') {
  if (val === null || val === undefined) return '—';
  return `${Number(val).toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`;
}
function escHtml(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
