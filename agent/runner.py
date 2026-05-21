"""
agent/runner.py — periodic screenshot analysis and mock-trade worker

This module powers the separate background worker process. It captures
screenshots throughout the trading day, records every analysis pass, manages
mock trades, and prepares data for the dashboard and email reports.
"""

import json
import math
import logging
import os
import threading
import time
from datetime import datetime, time as dt_time

import pytz

from config import (
    PAPER_CAPITAL, TIMEZONE, STATE_FILE, MIN_CONFIDENCE, MAX_SL_PCT,
    MIN_RR_RATIO, RISK_PER_TRADE_PCT, MAX_TRADES_PER_DAY,
    MAX_OPEN_POSITIONS, MAX_POSITION_CAPITAL_PCT, DEMO_DAYS,
    CAPTURE_START_HOUR, CAPTURE_START_MINUTE, ENTRY_START_HOUR,
    ENTRY_START_MINUTE, ENTRY_END_HOUR, ENTRY_END_MINUTE,
    MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE,
)
from agent.screenshotter import run_screenshots
from agent.vision_analyst import analyze_chart, generate_trade_learning
from data.db import (
    init_db, save_trade, get_pending_trades, save_daily_log,
    get_daily_trade_summary, expire_stale_recommendations, save_analysis_run,
    get_trades_for_date, get_latest_analysis_for_symbol, update_trade_result,
    save_learning, save_worker_event,
)

IST = pytz.timezone(TIMEZONE)
logger = logging.getLogger(__name__)
MARKET_CYCLE_LOCK = threading.Lock()
EOD_CLOSEOUT_LOCK = threading.Lock()


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "phase": "OBSERVE",
        "day": 1,
        "paused": False,
        "capital": PAPER_CAPITAL,
        "total_pnl": 0.0,
        "awaiting_eod_approval": False,
        "last_morning_run_date": None,
        "last_eod_date": None,
        "day_start_capital": PAPER_CAPITAL,
        "risk_alert": "",
        "demo_days": DEMO_DAYS,
        "last_cycle_at": None,
        "last_cycle_batch": None,
        "last_cycle_summary": "",
        "last_report_at": None,
        "last_report_status": "NOT_SENT",
        "last_closeout_at": None,
    }


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def ist_now() -> datetime:
    return datetime.now(IST)


def ist_today_str() -> str:
    return ist_now().date().isoformat()


def sync_daily_log_for_date(state: dict, trade_date: str):
    summary = get_daily_trade_summary(trade_date)
    save_daily_log({
        "date": trade_date,
        "phase": state["phase"],
        "day_num": state["day"],
        "total_trades": summary["total_trades"],
        "wins": summary["wins"],
        "losses": summary["losses"],
        "total_pnl": summary["total_pnl"],
        "capital": state["capital"],
        "your_note": "",
    })


def _window_time(hour: int, minute: int) -> dt_time:
    return dt_time(hour=hour, minute=minute)


def within_capture_window(now: datetime | None = None) -> bool:
    now = now or ist_now()
    current = now.time()
    start = _window_time(CAPTURE_START_HOUR, CAPTURE_START_MINUTE)
    end = _window_time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)
    return start <= current <= end


def within_entry_window(now: datetime | None = None) -> bool:
    now = now or ist_now()
    current = now.time()
    start = _window_time(ENTRY_START_HOUR, ENTRY_START_MINUTE)
    end = _window_time(ENTRY_END_HOUR, ENTRY_END_MINUTE)
    return start <= current <= end


def validate_and_size(decision: dict, capital: float) -> dict | None:
    """Returns enriched decision or None if trade should be rejected."""
    action = decision.get("action")
    if action == "NO_ACTION":
        return None

    entry = decision.get("entry_price") or 0
    sl = decision.get("stoploss") or 0
    tgt = decision.get("target") or 0
    conf = decision.get("confidence", 0)

    if not entry or not sl or not tgt:
        return None
    if conf < MIN_CONFIDENCE:
        logger.info(f"    Rejected {decision['symbol']}: confidence {conf}% < {MIN_CONFIDENCE}%")
        return None

    if action == "BUY":
        sl_pct = (entry - sl) / entry * 100
        rr = (tgt - entry) / (entry - sl) if (entry - sl) > 0 else 0
    else:
        sl_pct = (sl - entry) / entry * 100
        rr = (entry - tgt) / (sl - entry) if (sl - entry) > 0 else 0

    if sl_pct > MAX_SL_PCT:
        logger.info(f"    Rejected {decision['symbol']}: SL {sl_pct:.2f}% > {MAX_SL_PCT}%")
        return None
    if rr < MIN_RR_RATIO:
        logger.info(f"    Rejected {decision['symbol']}: RR {rr:.2f} < {MIN_RR_RATIO}")
        return None

    risk_per_share = abs(entry - sl)
    max_loss_amt = capital * (RISK_PER_TRADE_PCT / 100)
    qty = max(1, math.floor(min(
        max_loss_amt / risk_per_share,
        (capital * (MAX_POSITION_CAPITAL_PCT / 100)) / entry
    )))

    decision["quantity"] = qty
    decision["rr_ratio"] = round(rr, 2)
    decision["risk_amount"] = round(risk_per_share * qty, 2)
    return decision


def _close_trade_from_price(trade: dict, current_price: float, exit_reason: str, state: dict):
    if not current_price:
        return None

    entry = trade["entry"] or 0
    qty = trade["quantity"] or 1
    action = trade["action"]

    if action == "BUY":
        pnl = (current_price - entry) * qty
    else:
        pnl = (entry - current_price) * qty

    outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"
    update_trade_result(trade["id"], current_price, round(pnl, 2), outcome, exit_reason=exit_reason)

    reasoning = json.loads(trade.get("reasoning", "[]"))
    learning = generate_trade_learning(
        trade["symbol"], action, trade.get("pattern", ""), pnl, reasoning, outcome
    )
    save_learning(learning, trade["id"])

    if state["phase"] == "LIVE":
        state["capital"] = round(state["capital"] + pnl, 2)
        state["total_pnl"] = round(state.get("total_pnl", 0) + pnl, 2)

    logger.info(f"  ✅ Closed {trade['symbol']} via {exit_reason} at ₹{current_price:.2f} ({outcome}, ₹{pnl:.2f})")
    return {
        "symbol": trade["symbol"],
        "exit_price": round(current_price, 2),
        "pnl": round(pnl, 2),
        "outcome": outcome,
        "exit_reason": exit_reason,
    }


def _review_open_trade(trade: dict, decision: dict, state: dict):
    current_price = decision.get("current_price")
    if not current_price:
        return None

    if trade["action"] == "BUY":
        if current_price <= trade["stoploss"]:
            return _close_trade_from_price(trade, current_price, "AUTO_STOPLOSS", state)
        if current_price >= trade["target"]:
            return _close_trade_from_price(trade, current_price, "AUTO_TARGET", state)
    else:
        if current_price >= trade["stoploss"]:
            return _close_trade_from_price(trade, current_price, "AUTO_STOPLOSS", state)
        if current_price <= trade["target"]:
            return _close_trade_from_price(trade, current_price, "AUTO_TARGET", state)
    return None


def run_market_cycle(manual: bool = False):
    """Run one 10-minute screenshot + analysis pass across the stock basket."""
    if not MARKET_CYCLE_LOCK.acquire(blocking=False):
        logger.info("⏳ Market cycle already running — skipping duplicate trigger.")
        return {"ok": False, "message": "Cycle already running"}

    state = load_state()
    now = ist_now()
    today = now.date().isoformat()
    run_at = now.isoformat(timespec="seconds")
    batch_id = now.strftime("%Y%m%d-%H%M")

    try:
        if state["paused"] and not manual:
            logger.info("⏸  Worker paused — skipping market cycle.")
            return {"ok": False, "message": "Paused"}

        if not manual and not within_capture_window(now):
            logger.info("🕒 Outside capture window — skipping market cycle.")
            return {"ok": False, "message": "Outside capture window"}

        expired = expire_stale_recommendations(today)
        if expired:
            logger.info(f"🧹 Expired {expired} stale recommendation(s) from prior days.")

        logger.info(f"\n{'=' * 55}")
        logger.info(f"📡 MARKET CYCLE | {now.strftime('%H:%M IST')} | Day {state['day']} | {state['phase']}")
        logger.info(f"{'=' * 55}")

        screenshots = run_screenshots()
        if not screenshots:
            logger.error("No screenshots captured — aborting market cycle.")
            return {"ok": False, "message": "No screenshots captured"}

        open_trades = {t["symbol"]: t for t in get_pending_trades(today)}
        todays_trades = [
            t for t in get_trades_for_date(today)
            if t["action"] in ("BUY", "SELL") and t["outcome"] not in ("SKIPPED", "EXPIRED")
        ]
        available_slots = max(0, MAX_TRADES_PER_DAY - len(todays_trades))
        candidates = []
        closed_trades = []

        for symbol, paths in screenshots.items():
            decision = analyze_chart(symbol, paths["archive_path"], state["capital"], state["phase"])
            decision["date"] = today
            decision["phase"] = state["phase"]
            decision["run_at"] = run_at
            decision["batch_id"] = batch_id
            decision["image_path"] = paths["archive_path"]

            save_analysis_run(decision)

            # Sleep to avoid hitting Gemini free tier rate limits (5 RPM for 3.5-flash)
            time.sleep(15)

            open_trade = open_trades.get(symbol)
            if open_trade:
                result = _review_open_trade(open_trade, decision, state)
                if result:
                    closed_trades.append(result)
                continue

            if not within_entry_window(now):
                continue

            sized = validate_and_size(decision, state["capital"])
            if sized:
                sized["outcome"] = "PENDING"
                sized["opened_at"] = run_at
                candidates.append(sized)

        candidates.sort(key=lambda d: (d.get("confidence", 0), d.get("rr_ratio", 0)), reverse=True)
        selected = candidates[:available_slots]

        for sized in selected:
            db_id = save_trade(sized)
            emoji = "🟢 BUY" if sized["action"] == "BUY" else "🔴 SELL"
            logger.info(
                f"  {emoji}  {sized['symbol']} @ ₹{sized['entry_price']} | "
                f"SL: ₹{sized['stoploss']} | T: ₹{sized['target']} | "
                f"Qty: {sized['quantity']} | RR: {sized['rr_ratio']} | "
                f"Risk: ₹{sized['risk_amount']:.2f} | Conf: {sized['confidence']}%"
            )
            sized["db_id"] = db_id

        skipped_for_cap = max(0, len(candidates) - len(selected))
        if skipped_for_cap:
            logger.info(f"  ℹ️  Skipped {skipped_for_cap} lower-ranked setup(s) due to max {MAX_TRADES_PER_DAY} trades/day.")

        state["awaiting_eod_approval"] = False
        state["last_cycle_at"] = run_at
        state["last_cycle_batch"] = batch_id
        state["last_cycle_summary"] = (
            f"{len(screenshots)} screenshots, {len(selected)} new setups, "
            f"{len(closed_trades)} auto-closed trade(s)"
        )
        state["last_morning_run_date"] = today
        sync_daily_log_for_date(state, today)
        save_state(state)

        save_worker_event("MARKET_CYCLE", state["last_cycle_summary"])
        logger.info(f"  ✅ Market cycle complete — {state['last_cycle_summary']}")
        return {
            "ok": True,
            "screenshots": len(screenshots),
            "new_setups": len(selected),
            "closed_trades": len(closed_trades),
        }
    finally:
        MARKET_CYCLE_LOCK.release()


def run_eod_closeout():
    """Force-close any open mock trades at the end of the intraday session."""
    if not EOD_CLOSEOUT_LOCK.acquire(blocking=False):
        logger.info("⏳ EOD closeout already running — skipping duplicate trigger.")
        return {"ok": False, "message": "Closeout already running"}

    state = load_state()
    today = ist_today_str()

    try:
        pending = get_pending_trades(today)
        if not pending:
            closed = 0
        else:
            closed = []
            for trade in pending:
                latest = get_latest_analysis_for_symbol(trade["symbol"], today)
                exit_price = (latest or {}).get("current_price") or trade["entry"]
                result = _close_trade_from_price(trade, exit_price, "EOD_MARK_TO_MARKET", state)
                if result:
                    closed.append(result)

        state["awaiting_eod_approval"] = False
        state["last_eod_date"] = today
        state["last_closeout_at"] = ist_now().isoformat(timespec="seconds")
        if state["phase"] == "OBSERVE" and state["day"] < state.get("demo_days", DEMO_DAYS):
            state["day"] += 1
        elif state["phase"] == "OBSERVE" and state["day"] >= state.get("demo_days", DEMO_DAYS):
            state["phase"] = "AWAITING_APPROVAL"

        sync_daily_log_for_date(state, today)
        save_state(state)
        closed_count = closed if isinstance(closed, int) else len(closed)
        save_worker_event("EOD_CLOSEOUT", f"Closed {closed_count} trade(s) at end of day.")
        return {"ok": True, "closed": closed_count}
    finally:
        EOD_CLOSEOUT_LOCK.release()


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    init_db()

    if "--cycle-now" in sys.argv:
        run_market_cycle(manual=True)
    elif "--closeout" in sys.argv:
        run_eod_closeout()
    else:
        print("Usage: python agent/runner.py --cycle-now | --closeout")
