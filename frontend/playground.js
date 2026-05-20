'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let _file        = null;
let _equityChart = null, _drawdownChart = null, _pnlChart = null;
let _candleChart = null;

// ── DOM ───────────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const dropZone         = $('dropZone');
const fileInput        = $('fileInput');
const dzFilename       = $('dzFilename');
const codePreview      = $('codePreview');
const codePreviewEl    = $('codePreviewEl');
const codePreviewName  = $('codePreviewName');
const codeLineCount    = $('codeLineCount');
const dataModeSelect   = $('dataModeSelect');
const syntheticCtrls   = $('syntheticControls');
const trendSelect      = $('trendSelect');
const volatilitySelect = $('volatilitySelect');
const nBarsInput       = $('nBarsInput');
const tickerInput      = $('tickerInput');
const periodSelect     = $('periodSelect');
const capitalInput     = $('capitalInput');
const runBtn           = $('runBtn');
const pgStatus         = $('pgStatus');
const pgEmpty          = $('pgEmpty');
const pgResults        = $('pgResults');

// ── File drop / pick ──────────────────────────────────────────────────────────
dropZone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) setFile(fileInput.files[0]);
});
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const f = e.dataTransfer.files[0];
  if (f && f.name.endsWith('.py')) setFile(f);
  else showStatus('Only .py files are accepted.', 'err');
});

function setFile(f) {
  _file = f;
  dzFilename.textContent = f.name;
  runBtn.disabled = false;

  const reader = new FileReader();
  reader.onload = e => {
    const src = e.target.result;
    codePreviewEl.textContent = src;
    hljs.highlightElement(codePreviewEl);
    codePreviewName.textContent = f.name;
    codeLineCount.textContent   = `${src.split('\n').length} lines`;
    codePreview.style.display   = 'block';
  };
  reader.readAsText(f);
}

// ── Data mode toggle ──────────────────────────────────────────────────────────
dataModeSelect.addEventListener('change', () => {
  const real = dataModeSelect.value === 'real';
  document.querySelectorAll('.real-only').forEach(el => {
    el.style.display = real ? 'flex' : 'none';
  });
  syntheticCtrls.style.display = real ? 'none' : 'block';
});

// ── Run ───────────────────────────────────────────────────────────────────────
runBtn.addEventListener('click', runBacktest);

async function runBacktest() {
  if (!_file) return;
  runBtn.disabled = true;
  showStatus('Running backtest…', 'running');
  pgEmpty.style.display   = 'none';
  pgResults.style.display = 'none';

  const fd = new FormData();
  fd.append('file',       _file);
  fd.append('data_mode',  dataModeSelect.value);
  fd.append('ticker',     tickerInput.value.trim().toUpperCase() || 'NVDA');
  fd.append('period',     periodSelect.value);
  fd.append('capital',    capitalInput.value);
  fd.append('trend',      trendSelect.value);
  fd.append('volatility', volatilitySelect.value);
  fd.append('n_bars',     nBarsInput.value);

  try {
    const resp = await fetch('/api/playground/run', { method: 'POST', body: fd });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || resp.statusText);
    }
    const data = await resp.json();
    renderResults(data);
    showStatus(
      `✓ Backtest complete — ${data.n_bars} bars · ${data.ticker} · ` +
      `Return: ${fmtPct(data.metrics.total_return_pct)} · ` +
      `Sharpe: ${fmt(data.metrics.sharpe)}`,
      'ok'
    );
  } catch (e) {
    showStatus(`Error: ${e.message}`, 'err');
    pgEmpty.style.display = 'block';
  } finally {
    runBtn.disabled = false;
  }
}

// ── Render results ────────────────────────────────────────────────────────────
function renderResults(data) {
  pgResults.style.display = 'flex';
  pgResults.style.flexDirection = 'column';

  // Summary label
  const label = dataModeSelect.value === 'real'
    ? `${data.ticker} · ${data.start_date} → ${data.end_date}`
    : `Synthetic · ${trendSelect.options[trendSelect.selectedIndex].text}`;
  $('runSummaryLabel').textContent = label;

  // Regime badges
  const badges = [];
  if (dataModeSelect.value === 'synthetic') {
    badges.push(trendSelect.options[trendSelect.selectedIndex].text);
    badges.push(`${volatilitySelect.value} volatility`);
    badges.push(`${data.n_bars} bars`);
  } else {
    badges.push(data.ticker);
    badges.push(`${data.start_date} → ${data.end_date}`);
    badges.push(`${data.n_bars} bars`);
  }
  $('regimeBadges').innerHTML = badges.map(b =>
    `<span class="regime-badge">${escHtml(b)}</span>`).join('');

  renderMetrics(data.metrics);
  renderWalkforward(data.walkforward);
  renderCandleChart(data.ohlcv, data.signals);
  renderEquityCurve(data.equity_curve, data.metrics.buy_hold_return_pct);
  renderDrawdown(data.equity_curve);
  renderPnlChart(data.trade_log);
  renderTradeLog(data.trade_log);
}

// ── Metrics ───────────────────────────────────────────────────────────────────
function renderMetrics(m) {
  const cards = [
    { label:'Total Return', value:fmtPct(m.total_return_pct), pos:m.total_return_pct>0, sub:`B&H: ${fmtPct(m.buy_hold_return_pct)}` },
    { label:'CAGR',         value:fmtPct(m.cagr_pct),         pos:m.cagr_pct>0 },
    { label:'Sharpe',       value:fmt(m.sharpe),               pos:m.sharpe>1,    neg:m.sharpe<0 },
    { label:'Max Drawdown', value:fmtPct(m.max_drawdown_pct),  neg:true },
    { label:'Win Rate',     value:fmtPct(m.win_rate_pct),      pos:m.win_rate_pct>50 },
    { label:'Profit Factor',value:m.profit_factor?fmt(m.profit_factor):'—', pos:(m.profit_factor||0)>1 },
    { label:'Trades',       value:m.num_trades, sub:`Exposure: ${fmtPct(m.exposure_pct)}` },
  ];
  $('pgMetrics').innerHTML = cards.map(c => `
    <div class="metric-card">
      <div class="label">${c.label}</div>
      <div class="value ${c.neg?'neg':c.pos?'pos':'neutral'}">${c.value}</div>
      ${c.sub?`<div class="sub">${c.sub}</div>`:''}
    </div>`).join('');
}

// ── Walk-forward ──────────────────────────────────────────────────────────────
function renderWalkforward(wf) {
  const card = $('pgWalkforward');
  if (!wf || !wf.in_sample) { card.hidden = true; return; }
  card.hidden = false;
  const ins = wf.in_sample, outs = wf.out_sample;
  const rows = [
    ['Total Return %', ins.total_return_pct,  outs.total_return_pct,  true],
    ['CAGR %',        ins.cagr_pct,           outs.cagr_pct,           true],
    ['Sharpe',        ins.sharpe,              outs.sharpe,              true],
    ['Max DD %',      ins.max_drawdown_pct,    outs.max_drawdown_pct,    false],
    ['Win Rate %',    ins.win_rate_pct,        outs.win_rate_pct,        true],
    ['# Trades',      ins.num_trades,          outs.num_trades,          null],
  ];
  $('pgWfTable').innerHTML = `
    <table class="wf-table">
      <thead><tr><th>Metric</th><th>In-sample (70%)</th><th>Out-of-sample (30%)</th><th>Δ</th></tr></thead>
      <tbody>${rows.map(([label, iv, ov, hg]) => {
        const d = (iv!=null&&ov!=null)?(ov-iv):null;
        const ds = d!=null?`${d>=0?'+':''}${fmt(d)}`:'—';
        const dc = d==null||hg==null?'':(d>=0===hg?'td-pos':'td-neg');
        return `<tr><td>${label}</td><td>${fmt(iv)}</td><td>${fmt(ov)}</td><td class="${dc}">${ds}</td></tr>`;
      }).join('')}</tbody>
    </table>
    <div class="wf-split-note">Split date: ${wf.split_date||'—'}</div>`;
}

// ── Candlestick chart ─────────────────────────────────────────────────────────
function renderCandleChart(ohlcv, signals) {
  const container = $('pgCandleChart');
  if (_candleChart) { _candleChart.remove(); _candleChart = null; }
  if (!ohlcv || !ohlcv.length) return;

  const chart = LightweightCharts.createChart(container, {
    width:  container.clientWidth,
    height: 320,
    layout: { background:{ color:'#13161f' }, textColor:'#8892a4' },
    grid:   { vertLines:{ color:'#1e2235' }, horzLines:{ color:'#1e2235' } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor:'#2a2f4a' },
    timeScale:        { borderColor:'#2a2f4a', timeVisible:true },
  });
  _candleChart = chart;

  const cs = chart.addCandlestickSeries({
    upColor:'#3de8a0', downColor:'#ff6b6b',
    borderUpColor:'#3de8a0', borderDownColor:'#ff6b6b',
    wickUpColor:'#3de8a0',   wickDownColor:'#ff6b6b',
  });
  cs.setData(ohlcv);

  if (signals && signals.length) {
    const markers = signals.map(s => ({
      time:     s.date,
      position: s.type==='buy'?'belowBar':'aboveBar',
      color:    s.type==='buy'?'#3de8a0':'#ff6b6b',
      shape:    s.type==='buy'?'arrowUp':'arrowDown',
      text:     s.type==='buy'?'B':'S',
    })).sort((a,b)=>a.time<b.time?-1:1);
    cs.setMarkers(markers);
  }

  chart.timeScale().fitContent();
  window.addEventListener('resize', () => {
    if (_candleChart) chart.resize(container.clientWidth, 320);
  }, { once: true });
}

// ── Equity curve ──────────────────────────────────────────────────────────────
function renderEquityCurve(eq, bhPct) {
  if (_equityChart) _equityChart.destroy();
  const dates    = eq.map(p=>p.date);
  const equities = eq.map(p=>p.equity);
  const init     = equities[0]||10000;
  const bh       = equities.map((_,i)=>init*(1+(bhPct/100)*(i/(equities.length-1||1))));
  _equityChart = new Chart($('pgEquityChart'), {
    type:'line',
    data:{ labels:dates, datasets:[
      { label:'Strategy',   data:equities, borderColor:'#6c8eff', borderWidth:2, pointRadius:0, fill:false, tension:0.3 },
      { label:'Buy & Hold', data:bh,       borderColor:'#8892a4', borderWidth:1.5, borderDash:[5,5], pointRadius:0, fill:false },
    ]},
    options: chartOpts('$'),
  });
}

function renderDrawdown(eq) {
  if (_drawdownChart) _drawdownChart.destroy();
  const equities = eq.map(p=>p.equity);
  const dates    = eq.map(p=>p.date);
  let peak = equities[0];
  const dd = equities.map(v=>{ peak=Math.max(peak,v); return peak>0?((v-peak)/peak)*100:0; });
  _drawdownChart = new Chart($('pgDrawdownChart'), {
    type:'line',
    data:{ labels:dates, datasets:[
      { label:'Drawdown %', data:dd, borderColor:'#f87171', backgroundColor:'rgba(248,113,113,0.15)',
        borderWidth:1.5, pointRadius:0, fill:true, tension:0.2 },
    ]},
    options: chartOpts('%'),
  });
}

function renderPnlChart(trades) {
  if (_pnlChart) _pnlChart.destroy();
  if (!trades||!trades.length) return;
  const pnls   = trades.map(t=>t.pnl);
  const colors = pnls.map(v=>v>=0?'rgba(52,211,153,0.8)':'rgba(248,113,113,0.8)');
  _pnlChart = new Chart($('pgPnlChart'), {
    type:'bar',
    data:{ labels:trades.map((_,i)=>`T${i+1}`),
           datasets:[{ label:'P&L $', data:pnls, backgroundColor:colors, borderRadius:3 }] },
    options:{ ...chartOpts('$'), plugins:{ legend:{ display:false } } },
  });
}

// ── Trade log ─────────────────────────────────────────────────────────────────
function renderTradeLog(trades) {
  const tbody = $('pgTradeLog').querySelector('tbody');
  if (!trades||!trades.length) {
    tbody.innerHTML='<tr><td colspan="9" style="text-align:center;color:var(--text-muted)">No trades executed</td></tr>';
    return;
  }
  tbody.innerHTML = trades.map((t,i)=>`
    <tr>
      <td>${i+1}</td><td>${t.entry_date}</td><td>${t.exit_date}</td>
      <td>$${fmt(t.entry_price)}</td><td>$${fmt(t.exit_price)}</td>
      <td>${t.size}</td>
      <td class="${t.pnl>=0?'td-pos':'td-neg'}">$${fmt(t.pnl)}</td>
      <td class="${t.return_pct>=0?'td-pos':'td-neg'}">${fmt(t.return_pct)}%</td>
      <td>${t.bars_held}d</td>
    </tr>`).join('');
}

// ── Status bar ────────────────────────────────────────────────────────────────
function showStatus(msg, type) {
  pgStatus.textContent = msg;
  pgStatus.className   = type;
  pgStatus.style.display = 'block';
}

// ── Chart defaults ────────────────────────────────────────────────────────────
function chartOpts(unit) {
  return {
    responsive:true, maintainAspectRatio:true,
    interaction:{ mode:'index', intersect:false },
    plugins:{
      legend:{ labels:{ color:'#8892a4', font:{ size:11 } } },
      tooltip:{
        backgroundColor:'#1a1d27', borderColor:'#2d3148', borderWidth:1,
        titleColor:'#e2e8f0', bodyColor:'#8892a4',
        callbacks:{ label: ctx=>`${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)}${unit}` },
      },
    },
    scales:{
      x:{ ticks:{ color:'#8892a4', maxTicksLimit:8, font:{ size:10 } }, grid:{ color:'#1e2235' } },
      y:{ ticks:{ color:'#8892a4', font:{ size:10 } }, grid:{ color:'#1e2235' } },
    },
  };
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(val, dp=2) {
  if (val===null||val===undefined) return '—';
  return Number(val).toLocaleString(undefined,{ maximumFractionDigits:dp });
}
function fmtPct(val) {
  if (val===null||val===undefined) return '—';
  return `${Number(val)>=0?'':'-'}${Math.abs(Number(val)).toFixed(2)}%`;
}
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
