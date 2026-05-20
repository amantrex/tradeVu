"""
data/db.py — SQLite trade database
"""

import sqlite3
import json
import os
from datetime import datetime
from config import DB_FILE

REALIZED_OUTCOMES = ("WIN", "LOSS", "BREAKEVEN")
OPEN_OUTCOMES = ("AWAITING_APPROVAL", "PENDING")


def get_conn():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn, table: str, column: str, definition: str):
    cols = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT,
            phase       TEXT,
            symbol      TEXT,
            action      TEXT,
            entry       REAL,
            stoploss    REAL,
            target      REAL,
            quantity    INTEGER DEFAULT 1,
            confidence  INTEGER,
            pattern     TEXT,
            trend       TEXT,
            rr_ratio    REAL,
            reasoning   TEXT,
            risk_note   TEXT,
            image_path  TEXT,
            exit_price  REAL,
            pnl         REAL,
            outcome     TEXT DEFAULT 'PENDING',
            exit_reason TEXT,
            opened_at   TEXT,
            closed_at   TEXT,
            your_note   TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS learnings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            learning    TEXT,
            trade_id    INTEGER,
            date        TEXT DEFAULT (date('now')),
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS daily_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT UNIQUE,
            phase       TEXT,
            day_num     INTEGER,
            total_trades INTEGER DEFAULT 0,
            wins        INTEGER DEFAULT 0,
            losses      INTEGER DEFAULT 0,
            total_pnl   REAL DEFAULT 0,
            capital     REAL,
            your_note   TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS analysis_runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id    TEXT,
            date        TEXT,
            run_at      TEXT,
            symbol      TEXT,
            current_price REAL,
            action      TEXT,
            entry       REAL,
            stoploss    REAL,
            target      REAL,
            confidence  INTEGER,
            pattern     TEXT,
            trend       TEXT,
            rr_ratio    REAL,
            reasoning   TEXT,
            risk_note   TEXT,
            image_path  TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS worker_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type  TEXT,
            message     TEXT,
            event_at    TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    ensure_column(conn, "trades", "exit_reason", "TEXT")
    ensure_column(conn, "trades", "opened_at", "TEXT")
    ensure_column(conn, "trades", "closed_at", "TEXT")
    conn.commit()
    conn.close()


def save_trade(t: dict) -> int:
    conn = get_conn()
    trade_key = (t.get("date"), t.get("phase"), t.get("symbol"))
    existing = conn.execute("""
        SELECT id, outcome FROM trades
        WHERE date=? AND phase=? AND symbol=?
    """, trade_key).fetchone()

    default_outcome = "SKIPPED" if t.get("action") == "NO_ACTION" else "AWAITING_APPROVAL"
    explicit_outcome = t.get("outcome")

    if existing:
        if existing["outcome"] in REALIZED_OUTCOMES or existing["outcome"] in ("PENDING", "REJECTED"):
            conn.close()
            return existing["id"]

        if explicit_outcome is not None:
            outcome = explicit_outcome
        else:
            outcome = default_outcome

        conn.execute("""
            UPDATE trades
            SET action=?, entry=?, stoploss=?, target=?, quantity=?,
                confidence=?, pattern=?, trend=?, rr_ratio=?, reasoning=?,
                risk_note=?, image_path=?, outcome=?, opened_at=COALESCE(opened_at, ?)
            WHERE id=?
        """, (
            t.get("action"), t.get("entry_price"), t.get("stoploss"), t.get("target"),
            t.get("quantity", 1), t.get("confidence"), t.get("pattern"),
            t.get("trend"), t.get("rr_ratio"), json.dumps(t.get("reasoning", [])),
            t.get("risk_note"), t.get("image_path"), outcome,
            t.get("opened_at") or datetime.now().isoformat(timespec="seconds"),
            existing["id"],
        ))
        trade_id = existing["id"]
    else:
        cur = conn.execute("""
            INSERT INTO trades
              (date, phase, symbol, action, entry, stoploss, target, quantity,
               confidence, pattern, trend, rr_ratio, reasoning, risk_note, image_path, outcome, opened_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            t.get("date"), t.get("phase"), t.get("symbol"), t.get("action"),
            t.get("entry_price"), t.get("stoploss"), t.get("target"),
            t.get("quantity", 1), t.get("confidence"), t.get("pattern"),
            t.get("trend"), t.get("rr_ratio"),
            json.dumps(t.get("reasoning", [])),
            t.get("risk_note"), t.get("image_path"),
            explicit_outcome or default_outcome,
            t.get("opened_at") or datetime.now().isoformat(timespec="seconds"),
        ))
        trade_id = cur.lastrowid

    conn.commit()
    conn.close()
    return trade_id


def update_trade_result(trade_id: int, exit_price: float,
                        pnl: float, outcome: str, exit_reason: str = "MANUAL"):
    conn = get_conn()
    conn.execute("""
        UPDATE trades
        SET exit_price=?, pnl=?, outcome=?, exit_reason=?, closed_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (exit_price, pnl, outcome, exit_reason, trade_id))
    conn.commit()
    conn.close()


def update_trade_outcome(trade_id: int, outcome: str):
    conn = get_conn()
    conn.execute(
        "UPDATE trades SET outcome=?, exit_price=NULL, pnl=NULL, exit_reason=NULL, closed_at=NULL WHERE id=?",
        (outcome, trade_id)
    )
    conn.commit()
    conn.close()


def save_analysis_run(run: dict) -> int:
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO analysis_runs
          (batch_id, date, run_at, symbol, current_price, action, entry, stoploss,
           target, confidence, pattern, trend, rr_ratio, reasoning, risk_note, image_path)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        run.get("batch_id"), run.get("date"), run.get("run_at"), run.get("symbol"),
        run.get("current_price"), run.get("action"), run.get("entry_price"),
        run.get("stoploss"), run.get("target"), run.get("confidence"),
        run.get("pattern"), run.get("trend"), run.get("rr_ratio"),
        json.dumps(run.get("reasoning", [])), run.get("risk_note"), run.get("image_path"),
    ))
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def save_worker_event(event_type: str, message: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO worker_events (event_type, message) VALUES (?, ?)",
        (event_type, message),
    )
    conn.commit()
    conn.close()


def add_user_note(trade_id: int, note: str):
    conn = get_conn()
    conn.execute("UPDATE trades SET your_note=? WHERE id=?", (note, trade_id))
    conn.commit()
    conn.close()


def save_learning(learning: str, trade_id: int = None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO learnings (learning, trade_id) VALUES (?, ?)",
        (learning, trade_id)
    )
    conn.commit()
    conn.close()


def get_recent_learnings(limit: int = 10) -> str:
    conn = get_conn()
    rows = conn.execute(
        "SELECT learning FROM learnings ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    if not rows:
        return "No learnings yet — first day of observation!"
    return "\n".join(f"• {r['learning']}" for r in rows)


def get_trades_for_date(date: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades WHERE date=? ORDER BY created_at", (date,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_trades(limit: int = 200) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trade_by_id(trade_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_analysis_for_symbol(symbol: str, trade_date: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("""
        SELECT * FROM analysis_runs
        WHERE symbol=? AND date=?
        ORDER BY run_at DESC, id DESC
        LIMIT 1
    """, (symbol, trade_date)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_analysis_runs_for_date(trade_date: str, limit: int = 400) -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM analysis_runs
        WHERE date=?
        ORDER BY run_at DESC, symbol ASC
        LIMIT ?
    """, (trade_date, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_worker_events(limit: int = 20) -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM worker_events
        ORDER BY event_at DESC, id DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_trades(trade_date: str | None = None) -> list:
    conn = get_conn()
    if trade_date:
        rows = conn.execute("""
            SELECT * FROM trades
            WHERE outcome='PENDING' AND action IN ('BUY', 'SELL') AND date=?
            ORDER BY date, created_at
        """, (trade_date,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM trades
            WHERE outcome='PENDING' AND action IN ('BUY', 'SELL')
            ORDER BY date, created_at
        """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trades_awaiting_approval(trade_date: str | None = None) -> list:
    conn = get_conn()
    if trade_date:
        rows = conn.execute("""
            SELECT * FROM trades
            WHERE outcome='AWAITING_APPROVAL' AND action IN ('BUY', 'SELL') AND date=?
            ORDER BY created_at
        """, (trade_date,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM trades
            WHERE outcome='AWAITING_APPROVAL' AND action IN ('BUY', 'SELL')
            ORDER BY date, created_at
        """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def expire_stale_recommendations(current_date: str) -> int:
    conn = get_conn()
    cur = conn.execute("""
        UPDATE trades
        SET outcome='EXPIRED'
        WHERE outcome='AWAITING_APPROVAL' AND date < ?
    """, (current_date,))
    conn.commit()
    expired = cur.rowcount
    conn.close()
    return expired


def save_daily_log(log: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO daily_log
          (date, phase, day_num, total_trades, wins, losses, total_pnl, capital, your_note)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
          phase=excluded.phase, day_num=excluded.day_num,
          total_trades=excluded.total_trades,
          wins=excluded.wins, losses=excluded.losses,
          total_pnl=excluded.total_pnl, capital=excluded.capital,
          your_note=excluded.your_note
    """, (
        log["date"], log["phase"], log["day_num"],
        log["total_trades"], log["wins"], log["losses"],
        log["total_pnl"], log["capital"], log.get("your_note", "")
    ))
    conn.commit()
    conn.close()


def get_daily_logs(limit: int = 30) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM daily_log ORDER BY date DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    conn = get_conn()
    row = conn.execute("""
        SELECT
          COUNT(*) as total,
          SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins,
          SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) as losses,
          SUM(COALESCE(pnl, 0)) as total_pnl,
          AVG(confidence) as avg_confidence
        FROM trades WHERE outcome IN ('WIN', 'LOSS', 'BREAKEVEN')
    """).fetchone()
    conn.close()
    d = dict(row)
    d["win_rate"] = round(d["wins"] / d["total"] * 100, 1) if d["total"] else 0
    return d


def get_daily_trade_summary(trade_date: str) -> dict:
    conn = get_conn()
    row = conn.execute("""
        SELECT
          SUM(CASE WHEN action IN ('BUY', 'SELL')
                    AND outcome IN ('PENDING', 'WIN', 'LOSS', 'BREAKEVEN')
                   THEN 1 ELSE 0 END) as total_trades,
          SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins,
          SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) as losses,
          SUM(COALESCE(pnl, 0)) as total_pnl
        FROM trades
        WHERE date=?
    """, (trade_date,)).fetchone()
    conn.close()
    summary = dict(row)
    return {
        "total_trades": summary["total_trades"] or 0,
        "wins": summary["wins"] or 0,
        "losses": summary["losses"] or 0,
        "total_pnl": round(summary["total_pnl"] or 0, 2),
    }
