import json
import sqlite3
from contextlib import contextmanager

from src.config import DB_PATH

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
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


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
        return cur.lastrowid


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
) -> int:
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO backtest_runs
               (strategy_id, ticker, start_date, end_date, initial_capital,
                metrics, equity_curve, trade_log, explanation)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                strategy_id,
                ticker,
                start_date,
                end_date,
                initial_capital,
                json.dumps(metrics),
                json.dumps(equity_curve),
                json.dumps(trade_log),
                explanation,
            ),
        )
        return cur.lastrowid


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
    for key in ("metrics", "equity_curve", "trade_log"):
        if d.get(key):
            d[key] = json.loads(d[key])
    return d


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
