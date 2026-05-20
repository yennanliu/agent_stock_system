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
    path = _strategy_filename(sid, ticker, name)
    path.write_text(header + source_code, encoding="utf-8")
    return sid


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
