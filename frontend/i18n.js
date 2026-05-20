'use strict';
/**
 * Lightweight i18n — supports 'en' and 'zh-TW'.
 * Usage:
 *   Add data-i18n="key" to any element.
 *   Call applyI18n() after DOM load or language switch.
 *   Call setLang('zh-TW') to switch.
 */

const TRANSLATIONS = {
  en: {
    // Nav
    'nav.analyzer':    'Analyzer',
    'nav.playground':  '🧪 Playground',
    'nav.guide':       '📖 Eval Guide',
    'nav.landing':     '🏠 Home',
    'nav.back_analyzer': '← Back to Analyzer',
    'nav.strategies':    '📚 Strategies',

    // Header tagline
    'tagline.main':       'AI-powered quantitative strategy generation & backtesting',
    'tagline.playground': 'Strategy Playground — upload & run any strategy against synthetic data',
    'tagline.guide':      'How to Evaluate Quantitative Trading Results',

    // Analyzer — search
    'search.placeholder':  'Enter ticker (e.g. NVDA, AAPL, TSLA)',
    'search.analyze_btn':  'Analyze',
    'search.strategy_type':'Strategy Type',
    'search.indicators':   'Indicators',
    'search.history':      'History',
    'opt.auto':            'Auto (AI decides)',
    'opt.trend':           'Trend Following',
    'opt.reversion':       'Mean Reversion',
    'opt.momentum':        'Momentum',
    'opt.breakout':        'Breakout',
    'opt.sma':             'SMA Crossover',
    'opt.ema':             'EMA Crossover',
    'opt.rsi':             'RSI',
    'opt.macd':            'MACD',
    'opt.bollinger':       'Bollinger Bands',
    'opt.atr':             'ATR-based',
    'opt.combined':        'Combined (multiple)',
    'opt.1y':              '1 Year',
    'opt.2y':              '2 Years',
    'opt.5y':              '5 Years',
    'opt.10y':             '10 Years',

    // Strategy panel
    'strategy.source_code':  'Strategy Source Code',
    'strategy.download':     '⬇ Strategy',
    'strategy.runner':       '⬇ Runner',
    'strategy.optimize':     '⚡ Optimize',
    'strategy.run_again':    '▶ Run Again',
    'strategy.param_header': 'Parameter',
    'strategy.param_value':  'Value',
    'strategy.rerun_params': '▶ Re-run with these params',
    'strategy.reset_params': '↺ Reset',

    // Backtest panel
    'backtest.title':        'Backtest Results',
    'backtest.wf_title':     'Walk-Forward Validation',
    'backtest.wf_badge':     'In-sample 70% / Out-of-sample 30%',
    'backtest.candle_title': 'Candlestick Chart & Trade Signals',
    'backtest.equity_title': 'Equity Curve vs Buy & Hold',
    'backtest.dd_title':     'Drawdown',
    'backtest.pnl_title':    'Trade P&L Distribution',
    'backtest.trade_log':    'Trade Log',
    'backtest.analysis':     'Analysis',
    'backtest.run_code':     '⬇ Run Code',
    'backtest.raw_data':     '⬇ Raw Data',
    'backtest.buy':          'Buy',
    'backtest.sell':         'Sell',
    'backtest.replay':       '⟳ Replay',

    // Trade log table headers
    'tl.num':    '#',
    'tl.entry':  'Entry',
    'tl.exit':   'Exit',
    'tl.ep':     'Entry $',
    'tl.xp':     'Exit $',
    'tl.size':   'Size',
    'tl.pnl':    'P&L',
    'tl.ret':    'Return %',
    'tl.days':   'Days',

    // Optimize
    'opt_card.title':  'Parameter Optimisation Results',
    'opt_card.apply':  '▶ Run with Optimised Params',
    'opt_card.original': 'Original',
    'opt_card.optimised':'Optimised',

    // Sidebar
    'sidebar.history':  'Run History',
    'sidebar.refresh':  '↻',
    'sidebar.empty':    'No runs yet. Analyze a ticker to get started.',

    // Walk-forward table
    'wf.metric':    'Metric',
    'wf.insample':  'In-sample',
    'wf.outsample': 'Out-of-sample',
    'wf.delta':     'Δ',

    // Playground
    'pg.data_source':   'Data Source',
    'pg.mode':          'Mode',
    'pg.mode_synth':    'Synthetic (no API key needed)',
    'pg.mode_real':     'Real market data (yfinance)',
    'pg.regime':        'Market Regime',
    'pg.volatility':    'Volatility',
    'pg.n_bars':        'Number of bars (trading days)',
    'pg.capital':       'Initial Capital ($)',
    'pg.run':           '▶ Run Backtest',
    'pg.drop_label':    'Drop your *_run.py or strategy .py here\nor click to browse',
    'pg.backtest_cfg':  'Backtest Config',
    'pg.empty':         'Upload a strategy file on the left to get started.',
    'pg.regime_bull':   'Bull Market (uptrend)',
    'pg.regime_bear':   'Bear Market (downtrend)',
    'pg.regime_side':   'Sideways / Ranging',
    'pg.regime_vol':    'High-Volatility / Stress',
    'pg.vol_low':       'Low (quiet market)',
    'pg.vol_med':       'Medium (normal)',
    'pg.vol_high':      'High (turbulent)',
    'pg.period':        'Period',
    'pg.ticker':        'Ticker',

    // Dynamic metric labels (used in JS renderMetrics)
    'metric.total_return':  'Total Return',
    'metric.cagr':          'CAGR',
    'metric.sharpe':        'Sharpe',
    'metric.max_drawdown':  'Max Drawdown',
    'metric.win_rate':      'Win Rate',
    'metric.profit_factor': 'Profit Factor',
    'metric.trades':        'Trades',
    'metric.bnh':           'B&H',
    'metric.exposure':      'Exposure',

    // Dynamic walk-forward labels
    'wf.in_sample_full':   'In-sample\nfirst 70%',
    'wf.out_sample_full':  'Out-of-sample\nlast 30%',

    // Sidebar erase
    'sidebar.clear_all':    '🗑 Clear All',
    'sidebar.confirm_clear':'Delete ALL run history? This cannot be undone.',
    'sidebar.confirm_del':  'Delete this run?',

    // Run ID badge
    'run.id_label':         'Run',
    'run.path_label':       'File',

    // Misc dynamic
    'no_trades':            'No trades executed',
    'code_review_label':    'Code Review',
  },

  'zh-TW': {
    // Nav
    'nav.analyzer':    '策略分析',
    'nav.playground':  '🧪 沙箱測試',
    'nav.guide':       '📖 評估指南',
    'nav.landing':     '🏠 首頁',
    'nav.back_analyzer': '← 返回分析器',
    'nav.strategies':    '📚 策略庫',

    // Header tagline
    'tagline.main':       'AI 驅動的量化策略生成與回測系統',
    'tagline.playground': '策略沙箱 — 上傳策略並以合成數據測試',
    'tagline.guide':      '如何評估量化交易結果',

    // Analyzer — search
    'search.placeholder':  '輸入股票代號（例：NVDA、AAPL、TSLA）',
    'search.analyze_btn':  '分析',
    'search.strategy_type':'策略類型',
    'search.indicators':   '指標',
    'search.history':      '歷史記錄',
    'opt.auto':            '自動（AI 決定）',
    'opt.trend':           '趨勢跟蹤',
    'opt.reversion':       '均值回歸',
    'opt.momentum':        '動量策略',
    'opt.breakout':        '突破策略',
    'opt.sma':             'SMA 交叉',
    'opt.ema':             'EMA 交叉',
    'opt.rsi':             'RSI',
    'opt.macd':            'MACD',
    'opt.bollinger':       '布林通道',
    'opt.atr':             'ATR 策略',
    'opt.combined':        '多指標組合',
    'opt.1y':              '1 年',
    'opt.2y':              '2 年',
    'opt.5y':              '5 年',
    'opt.10y':             '10 年',

    // Strategy panel
    'strategy.source_code':  '策略原始碼',
    'strategy.download':     '⬇ 策略程式碼',
    'strategy.runner':       '⬇ 執行腳本',
    'strategy.optimize':     '⚡ 參數優化',
    'strategy.run_again':    '▶ 重新執行',
    'strategy.param_header': '參數',
    'strategy.param_value':  '數值',
    'strategy.rerun_params': '▶ 以修改參數重新執行',
    'strategy.reset_params': '↺ 重置',

    // Backtest panel
    'backtest.title':        '回測結果',
    'backtest.wf_title':     '前向驗證',
    'backtest.wf_badge':     '樣本內 70% ／ 樣本外 30%',
    'backtest.candle_title': 'K 線圖與交易訊號',
    'backtest.equity_title': '權益曲線 vs 買入持有',
    'backtest.dd_title':     '最大回撤',
    'backtest.pnl_title':    '交易損益分佈',
    'backtest.trade_log':    '交易紀錄',
    'backtest.analysis':     '績效分析',
    'backtest.run_code':     '⬇ 策略程式碼',
    'backtest.raw_data':     '⬇ 原始數據',
    'backtest.buy':          '買入',
    'backtest.sell':         '賣出',
    'backtest.replay':       '⟳ 重播',

    // Trade log table headers
    'tl.num':    '#',
    'tl.entry':  '進場日',
    'tl.exit':   '出場日',
    'tl.ep':     '進場價',
    'tl.xp':     '出場價',
    'tl.size':   '數量',
    'tl.pnl':    '損益',
    'tl.ret':    '報酬率',
    'tl.days':   '持倉天數',

    // Optimize
    'opt_card.title':   '參數優化結果',
    'opt_card.apply':   '▶ 以最優參數執行',
    'opt_card.original':'原始值',
    'opt_card.optimised':'最優值',

    // Sidebar
    'sidebar.history':  '執行歷史',
    'sidebar.refresh':  '↻',
    'sidebar.empty':    '尚無執行記錄。輸入股票代號開始分析。',

    // Walk-forward table
    'wf.metric':    '指標',
    'wf.insample':  '樣本內',
    'wf.outsample': '樣本外',
    'wf.delta':     '差值',

    // Playground
    'pg.data_source':   '資料來源',
    'pg.mode':          '模式',
    'pg.mode_synth':    '合成數據（無需 API 金鑰）',
    'pg.mode_real':     '真實市場數據（yfinance）',
    'pg.regime':        '市場情境',
    'pg.volatility':    '波動率',
    'pg.n_bars':        '交易日數量（K 線數）',
    'pg.capital':       '初始資金（美元）',
    'pg.run':           '▶ 執行回測',
    'pg.drop_label':    '將 *_run.py 或策略 .py 拖曳至此\n或點擊瀏覽',
    'pg.backtest_cfg':  '回測設定',
    'pg.empty':         '請在左側上傳策略檔案以開始測試。',
    'pg.regime_bull':   '多頭市場（上升趨勢）',
    'pg.regime_bear':   '空頭市場（下跌趨勢）',
    'pg.regime_side':   '盤整市場',
    'pg.regime_vol':    '高波動 ／ 壓力測試',
    'pg.vol_low':       '低波動（平靜市場）',
    'pg.vol_med':       '中等波動（正常）',
    'pg.vol_high':      '高波動（動盪市場）',
    'pg.period':        '時間段',
    'pg.ticker':        '股票代號',

    // Dynamic metric labels
    'metric.total_return':  '總回報',
    'metric.cagr':          '年化複合增長率',
    'metric.sharpe':        '夏普比率',
    'metric.max_drawdown':  '最大回撤',
    'metric.win_rate':      '勝率',
    'metric.profit_factor': '獲利因子',
    'metric.trades':        '交易次數',
    'metric.bnh':           '買入持有',
    'metric.exposure':      '持倉暴露',

    // Dynamic walk-forward labels
    'wf.in_sample_full':   '樣本內\n前70%',
    'wf.out_sample_full':  '樣本外\n後30%',

    // Sidebar erase
    'sidebar.clear_all':    '🗑 清除全部',
    'sidebar.confirm_clear':'刪除所有執行歷史？此操作無法復原。',
    'sidebar.confirm_del':  '刪除此次執行記錄？',

    // Run ID badge
    'run.id_label':         '執行',
    'run.path_label':       '檔案',

    // Misc dynamic
    'no_trades':            '未執行任何交易',
    'code_review_label':    '代碼審查',
  },
};

// ── Core API ──────────────────────────────────────────────────────────────────

let _currentLang = localStorage.getItem('lang') || 'en';

function t(key) {
  return (TRANSLATIONS[_currentLang] || TRANSLATIONS['en'])[key]
      || TRANSLATIONS['en'][key]
      || key;
}

function setLang(lang) {
  _currentLang = lang;
  localStorage.setItem('lang', lang);
  applyI18n();
  document.documentElement.lang = lang;
}

function getLang() { return _currentLang; }

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key  = el.getAttribute('data-i18n');
    const attr = el.getAttribute('data-i18n-attr'); // optional: translate an attribute
    const val  = t(key);
    if (attr) {
      el.setAttribute(attr, val);
    } else if (el.tagName === 'INPUT' && el.placeholder !== undefined) {
      el.placeholder = val;
    } else {
      el.textContent = val;
    }
  });
  // Update language switcher state
  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.lang === _currentLang);
  });
}

// ── Language switcher widget HTML ─────────────────────────────────────────────
function langSwitcherHTML() {
  return `<div class="lang-switcher">
    <button class="lang-btn${_currentLang==='en'?' active':''}" data-lang="en" onclick="setLang('en')">EN</button>
    <button class="lang-btn${_currentLang==='zh-TW'?' active':''}" data-lang="zh-TW" onclick="setLang('zh-TW')">中文</button>
  </div>`;
}

// Auto-apply on load
document.addEventListener('DOMContentLoaded', applyI18n);
