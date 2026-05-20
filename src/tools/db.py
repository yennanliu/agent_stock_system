import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from src.config import DB_PATH

STRATEGIES_DIR = Path("strategies")
STRATEGIES_DIR.mkdir(exist_ok=True)

# Per-run code lives at strategies/{run_id}/{ticker}.py
def _run_code_dir(run_id: int) -> Path:
    d = STRATEGIES_DIR / str(run_id)
    d.mkdir(parents=True, exist_ok=True)
    return d

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    id          INTEGER PRIMARY KEY,
    ticker      TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT,
    source_code TEXT NOT NULL,
    parameters  TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS code_reviews (
    id            INTEGER PRIMARY KEY,
    strategy_id   INTEGER REFERENCES strategies(id),
    confidence    INTEGER,
    issues_found  TEXT,
    fixes_applied TEXT,
    iterations    INTEGER,
    approved      INTEGER,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id              INTEGER PRIMARY KEY,
    strategy_id     INTEGER REFERENCES strategies(id),
    ticker          TEXT NOT NULL,
    start_date      TEXT,
    end_date        TEXT,
    initial_capital REAL DEFAULT 10000,
    metrics         TEXT,
    equity_curve    TEXT,
    trade_log       TEXT,
    explanation     TEXT,
    source_code     TEXT,
    raw_data_path   TEXT,
    price_series    TEXT,
    signals         TEXT,
    walkforward     TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

_MIGRATE_SQL = """
ALTER TABLE backtest_runs ADD COLUMN source_code TEXT;
ALTER TABLE backtest_runs ADD COLUMN raw_data_path TEXT;
ALTER TABLE backtest_runs ADD COLUMN price_series TEXT;
ALTER TABLE backtest_runs ADD COLUMN signals TEXT;
ALTER TABLE backtest_runs ADD COLUMN walkforward TEXT;
"""

RAW_DATA_DIR = Path("data/raw")
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

RUN_CODE_DIR = Path("data/runs")
RUN_CODE_DIR.mkdir(parents=True, exist_ok=True)


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.executescript(SCHEMA)
    # Add new columns to existing databases (idempotent)
    for stmt in _MIGRATE_SQL.strip().splitlines():
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            with _conn() as con:
                con.execute(stmt)
        except Exception:
            pass  # column already exists


def _strategy_filename(strategy_id: int, ticker: str, name: str) -> Path:
    safe_name = re.sub(r"[^\w]", "_", name)
    return STRATEGIES_DIR / f"{ticker}_{safe_name}_{strategy_id}.py"


def save_strategy(
    ticker: str,
    name: str,
    description: str,
    source_code: str,
    parameters: dict,
) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO strategies (ticker, name, description, source_code, parameters) VALUES (?,?,?,?,?)",
            (ticker, name, description, source_code, json.dumps(parameters)),
        )
        sid = cur.lastrowid

    # Write .py file to disk
    param_lines = "\n".join(f"#   {k} = {v}" for k, v in parameters.items())
    header = (
        f'"""\n'
        f"Strategy: {name}\n"
        f"Ticker:   {ticker}\n"
        f"ID:       {sid}\n"
        f"Parameters:\n{param_lines}\n\n"
        f"{description}\n"
        f'"""\n\n'
        f"import numpy as np\n"
        f"import pandas as pd\n"
        f"from backtesting import Strategy\n"
        f"from backtesting.lib import crossover\n\n"
    )
    safe_name = re.sub(r"[^\w]", "_", name)
    path = _strategy_filename(sid, ticker, name)
    path.write_text(header + source_code, encoding="utf-8")

    # Write a standalone runner next to the strategy file
    runner_path = STRATEGIES_DIR / f"{ticker}_{safe_name}_{sid}_run.py"
    _write_runner(runner_path, path.name, ticker, name, sid)
    return sid


_RUNNER_TEMPLATE = '''\
#!/usr/bin/env python
"""
Standalone runner for: {name}  (ticker: {ticker}, id: {sid})

HOW TO RUN
----------
1. Install dependencies (one-time):
       pip install backtesting yfinance pandas numpy

2. Run:
       python {runner_filename}

   Or with a custom date range:
       python {runner_filename} --start 2022-01-01 --end 2024-01-01

3. The script opens an interactive backtest chart in your browser.
   Close it to exit.
"""
import argparse
import sys
from pathlib import Path

# ── resolve strategy file relative to this runner ─────────────────────────────
_HERE = Path(__file__).parent
_STRATEGY_FILE = _HERE / "{strategy_filename}"

try:
    import numpy as np
    import pandas as pd
    import yfinance as yf
    from backtesting import Backtest, Strategy
    from backtesting.lib import crossover, cross, barssince
except ImportError as e:
    print(f"Missing dependency: {{e}}")
    print("Run:  pip install backtesting yfinance pandas numpy")
    sys.exit(1)

# ── TA helper functions (same as the live system) ─────────────────────────────
def SMA(values, n):
    return pd.Series(values).rolling(n).mean().values
def EMA(values, n):
    return pd.Series(values).ewm(span=n, adjust=False).mean().values
def RSI(values, n=14):
    s = pd.Series(values)
    delta = s.diff()
    gain  = delta.clip(lower=0).ewm(com=n - 1, adjust=True).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=n - 1, adjust=True).mean()
    rs    = gain / loss.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).values
def MACD(values, fast=12, slow=26):
    s = pd.Series(values)
    return (s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()).values
def MACD_SIGNAL(values, fast=12, slow=26, signal=9):
    return pd.Series(MACD(values, fast, slow)).ewm(span=signal, adjust=False).mean().values
def BBANDS_UPPER(values, n=20, k=2.0):
    s = pd.Series(values); m = s.rolling(n).mean(); return (m + k * s.rolling(n).std()).values
def BBANDS_MID(values, n=20):
    return pd.Series(values).rolling(n).mean().values
def BBANDS_LOWER(values, n=20, k=2.0):
    s = pd.Series(values); m = s.rolling(n).mean(); return (m - k * s.rolling(n).std()).values
def ATR(high, low, close, n=14):
    h, l, c = pd.Series(high), pd.Series(low), pd.Series(close)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(com=n - 1, adjust=True).mean().values
def STDEV(values, n=20):
    return pd.Series(values).rolling(n).std().values
def HIGHEST(values, n):
    return pd.Series(values).rolling(n).max().values
def LOWEST(values, n):
    return pd.Series(values).rolling(n).min().values

# ── load strategy class from the .py file ────────────────────────────────────
_scope = dict(
    Strategy=Strategy, np=np, pd=pd,
    crossover=crossover, cross=cross, barssince=barssince,
    SMA=SMA, EMA=EMA, RSI=RSI, MACD=MACD, MACD_SIGNAL=MACD_SIGNAL,
    BBANDS_UPPER=BBANDS_UPPER, BBANDS_MID=BBANDS_MID, BBANDS_LOWER=BBANDS_LOWER,
    ATR=ATR, STDEV=STDEV, HIGHEST=HIGHEST, LOWEST=LOWEST,
)
exec(compile(_STRATEGY_FILE.read_text(), str(_STRATEGY_FILE), "exec"), _scope)
StrategyClass = next(
    v for v in _scope.values()
    if isinstance(v, type) and issubclass(v, Strategy) and v is not Strategy
)

# ── CLI args ──────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--ticker", default="{ticker}")
parser.add_argument("--period", default="2y")
parser.add_argument("--start",  default=None, help="e.g. 2022-01-01")
parser.add_argument("--end",    default=None, help="e.g. 2024-01-01")
parser.add_argument("--cash",   type=float, default=10000)
parser.add_argument("--no-plot", action="store_true")
args = parser.parse_args()

# ── fetch data ────────────────────────────────────────────────────────────────
print(f"Fetching {{args.ticker}} data…")
if args.start:
    df = yf.download(args.ticker, start=args.start, end=args.end, auto_adjust=True, progress=False)
else:
    df = yf.download(args.ticker, period=args.period, auto_adjust=True, progress=False)

if df.empty:
    print(f"No data returned for {{args.ticker}}. Check the ticker symbol.")
    sys.exit(1)

df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
print(f"  {{len(df)}} trading days loaded ({{}}{{}})".format(
    df.index[0].date(), " → " + str(df.index[-1].date())))

# ── run backtest ──────────────────────────────────────────────────────────────
bt = Backtest(df, StrategyClass, cash=args.cash, commission=0.002,
              exclusive_orders=True, finalize_trades=True)
stats = bt.run()

print("\\n── Results ──────────────────────────────────────────────────")
for key in ["Return [%]", "Return (Ann.) [%]", "Sharpe Ratio",
            "Max. Drawdown [%]", "Win Rate [%]", "# Trades"]:
    val = stats.get(key)
    if val is not None:
        print(f"  {{key:<25}} {{val:.2f}}")
print()

if not args.no_plot:
    bt.plot()
'''


def _write_runner(runner_path: Path, strategy_filename: str, ticker: str, name: str, sid: int) -> None:
    runner_path.write_text(
        _RUNNER_TEMPLATE.format(
            runner_filename=runner_path.name,
            strategy_filename=strategy_filename,
            ticker=ticker,
            name=name,
            sid=sid,
        ),
        encoding="utf-8",
    )


def get_strategy_filepath(strategy_id: int) -> Path | None:
    row = get_strategy(strategy_id)
    if row is None:
        return None
    path = _strategy_filename(strategy_id, row["ticker"], row["name"])
    return path if path.exists() else None


def save_code_review(
    strategy_id: int,
    confidence: int,
    issues_found: list,
    fixes_applied: list,
    iterations: int,
    approved: bool,
) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO code_reviews (strategy_id, confidence, issues_found, fixes_applied, iterations, approved) VALUES (?,?,?,?,?,?)",
            (
                strategy_id,
                confidence,
                json.dumps(issues_found),
                json.dumps(fixes_applied),
                iterations,
                int(approved),
            ),
        )
        return cur.lastrowid


def save_backtest_run(
    strategy_id: int,
    ticker: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    metrics: dict,
    equity_curve: list,
    trade_log: list,
    explanation: str,
    source_code: str = "",
    raw_df=None,           # optional pd.DataFrame of OHLCV + indicators
    price_series: list | None = None,
    signals: list | None = None,
    walkforward: dict | None = None,
) -> int:
    # Reserve a row ID first (needed for file paths)
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO backtest_runs
               (strategy_id, ticker, start_date, end_date, initial_capital,
                metrics, equity_curve, trade_log, explanation,
                source_code, raw_data_path, price_series, signals, walkforward)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                strategy_id, ticker, start_date, end_date, initial_capital,
                json.dumps(metrics), json.dumps(equity_curve),
                json.dumps(trade_log), explanation,
                source_code, None,
                json.dumps(price_series or []),
                json.dumps(signals or []),
                json.dumps(walkforward or {}),
            ),
        )
        run_id = cur.lastrowid

    # Save code at strategies/{run_id}/{ticker}.py
    _save_run_code(run_id, ticker, source_code)

    # Save raw OHLCV+indicators CSV
    if raw_df is not None:
        csv_path = RAW_DATA_DIR / f"{run_id}_{ticker}.csv"
        raw_df.to_csv(csv_path)
        with _conn() as con:
            con.execute(
                "UPDATE backtest_runs SET raw_data_path=? WHERE id=?",
                (str(csv_path), run_id),
            )

    return run_id


def _save_run_code(run_id: int, ticker: str, source_code: str) -> None:
    if not source_code:
        return
    path = _run_code_dir(run_id) / f"{ticker}.py"
    path.write_text(source_code, encoding="utf-8")


def get_strategy(strategy_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute(
            """SELECT s.*, cr.confidence, cr.issues_found, cr.fixes_applied,
                      cr.iterations, cr.approved
               FROM strategies s
               LEFT JOIN code_reviews cr ON cr.strategy_id = s.id
               WHERE s.id = ?
               ORDER BY cr.created_at DESC LIMIT 1""",
            (strategy_id,),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    for key in ("parameters", "issues_found", "fixes_applied"):
        if d.get(key):
            d[key] = json.loads(d[key])
    return d


def get_backtest(run_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM backtest_runs WHERE id = ?", (run_id,)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    for key in ("metrics", "equity_curve", "trade_log", "price_series", "signals", "walkforward"):
        if d.get(key):
            d[key] = json.loads(d[key])
    return d


def get_run_source_path(run_id: int) -> Path | None:
    # Primary: strategies/{run_id}/{ticker}.py
    run_dir = STRATEGIES_DIR / str(run_id)
    if run_dir.exists():
        candidates = list(run_dir.glob("*.py"))
        if candidates:
            return candidates[0]
    # Legacy fallback: data/runs/{run_id}_{ticker}.py
    import glob
    matches = glob.glob(str(RUN_CODE_DIR / f"{run_id}_*.py"))
    if matches:
        return Path(matches[0])
    return None


def get_run_raw_data_path(run_id: int) -> Path | None:
    with _conn() as con:
        row = con.execute(
            "SELECT raw_data_path FROM backtest_runs WHERE id = ?", (run_id,)
        ).fetchone()
    if row and row["raw_data_path"]:
        p = Path(row["raw_data_path"])
        return p if p.exists() else None
    return None


def list_strategies() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT id, ticker, name, description, created_at FROM strategies ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_runs_for_ticker(ticker: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """SELECT br.id, br.strategy_id, br.ticker, br.start_date, br.end_date,
                      br.metrics, br.created_at, s.name as strategy_name
               FROM backtest_runs br
               JOIN strategies s ON s.id = br.strategy_id
               WHERE br.ticker = ?
               ORDER BY br.created_at DESC""",
            (ticker.upper(),),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("metrics"):
            d["metrics"] = json.loads(d["metrics"])
        result.append(d)
    return result
