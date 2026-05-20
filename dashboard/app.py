"""
dashboard/app.py — Interactive Web Dashboard

A clean Flask web app that serves as your entire control panel.
No CLI needed. Open http://localhost:8080 in your browser.

Features:
  • See all 20 chart screenshots from today
  • Review Gemini 3.1 trade recommendations with reasoning
  • Approve or reject each trade before it's "paper executed"
  • Enter exit prices manually at EOD
  • View P&L history, win rate, learnings
  • Proceed/Pause/Go-Live controls
  • Live agent status
"""

import json
import os
from datetime import datetime
from pathlib import Path
import pytz
from flask import (
    Flask, render_template, request, jsonify, send_from_directory
)
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    STATE_FILE, PAPER_CAPITAL, LIVE_CAPITAL, TIMEZONE,
    DASHBOARD_HOST, DASHBOARD_PORT, STOCK_BASKET,
    FLASK_SECRET_KEY, MAX_DAILY_LOSS_PCT, DEMO_DAYS, MAX_TRADES_PER_DAY,
    MAX_OPEN_POSITIONS, RISK_PER_TRADE_PCT, MAX_SL_PCT, MIN_RR_RATIO,
    ENTRY_START_HOUR, ENTRY_START_MINUTE, ENTRY_END_HOUR, ENTRY_END_MINUTE
)
from data.db import (
    init_db, get_trades_for_date, get_all_trades, get_trade_by_id,
    get_pending_trades, get_trades_awaiting_approval, update_trade_result,
    update_trade_outcome, add_user_note, save_learning, save_daily_log,
    get_stats, get_daily_logs, get_recent_learnings, get_daily_trade_summary,
    expire_stale_recommendations, get_recent_worker_events
)
from agent.vision_analyst import generate_trade_learning

IST = pytz.timezone(TIMEZONE)
app = Flask(__name__, template_folder="../templates")
app.secret_key = FLASK_SECRET_KEY


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "phase": "OBSERVE", "day": 1, "paused": False,
        "capital": PAPER_CAPITAL, "total_pnl": 0.0,
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


def save_state(s: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


def today_str():
    return datetime.now(IST).date().isoformat()


def sync_daily_log_for_date(trade_date: str, state: dict):
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


def maybe_pause_for_daily_loss(state: dict, trade_date: str):
    if state["phase"] != "LIVE":
        return

    day_start_capital = state.get("day_start_capital") or state["capital"]
    max_day_loss = round(day_start_capital * (MAX_DAILY_LOSS_PCT / 100), 2)
    summary = get_daily_trade_summary(trade_date)

    if summary["total_pnl"] <= -max_day_loss:
        state["paused"] = True
        state["risk_alert"] = (
            f"Daily loss limit reached for {trade_date}: "
            f"₹{abs(summary['total_pnl']):,.2f} loss vs max ₹{max_day_loss:,.2f}. "
            "Review trades before resuming."
        )


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    expire_stale_recommendations(today_str())
    state  = load_state()
    trades = get_trades_for_date(today_str())
    stats  = get_stats()
    logs   = get_daily_logs(limit=14)
    pending = get_pending_trades()
    awaiting = get_trades_awaiting_approval(today_str())
    learnings = get_recent_learnings(limit=5)
    actionable_trades = [t for t in trades if t["action"] != "NO_ACTION"]
    worker_events = get_recent_worker_events(limit=5)
    today_summary = {
        "recommended": len(awaiting) + len(pending),
        "approved": len([t for t in actionable_trades if t["outcome"] in ("PENDING", "WIN", "LOSS", "BREAKEVEN")]),
        "wins": len([t for t in actionable_trades if t["outcome"] == "WIN"]),
        "losses": len([t for t in actionable_trades if t["outcome"] == "LOSS"]),
    }
    strategy = {
        "demo_days": state.get("demo_days", DEMO_DAYS),
        "max_trades_per_day": MAX_TRADES_PER_DAY,
        "max_open_positions": MAX_OPEN_POSITIONS,
        "risk_per_trade_pct": RISK_PER_TRADE_PCT,
        "max_sl_pct": MAX_SL_PCT,
        "min_rr_ratio": MIN_RR_RATIO,
        "entry_window": f"{ENTRY_START_HOUR:02d}:{ENTRY_START_MINUTE:02d}–{ENTRY_END_HOUR:02d}:{ENTRY_END_MINUTE:02d} IST",
    }

    return render_template("index.html",
        state=state,
        trades=actionable_trades,
        pending_count=len(pending),
        awaiting_count=len(awaiting),
        today_summary=today_summary,
        strategy=strategy,
        worker_events=worker_events,
        stats=stats,
        logs=logs,
        today=today_str(),
        learnings=learnings,
        now=datetime.now(IST).strftime("%H:%M IST"),
    )


@app.route("/charts")
def charts():
    """Show today's chart screenshots + Gemini 3.1 analysis side by side."""
    expire_stale_recommendations(today_str())
    state  = load_state()
    trades = get_trades_for_date(today_str())
    today  = today_str()

    # Build a map of symbol → trade
    trade_map = {t["symbol"]: t for t in trades}

    # Get screenshot paths
    screenshot_dir = Path("screenshots") / today
    chart_data = []
    for name, _ in STOCK_BASKET:
        img_path = screenshot_dir / f"{name}.png"
        trade    = trade_map.get(name, {})
        chart_data.append({
            "symbol":     name,
            "has_image":  img_path.exists(),
            "img_url":    f"/screenshot/{today}/{name}.png" if img_path.exists() else None,
            "trade":      trade,
            "action":     trade.get("action", "NO_ACTION"),
            "confidence": trade.get("confidence", 0),
            "entry":      trade.get("entry"),
            "stoploss":   trade.get("stoploss"),
            "target":     trade.get("target"),
            "pattern":    trade.get("pattern", "—"),
            "reasoning":  json.loads(trade.get("reasoning", "[]")) if trade.get("reasoning") else [],
            "outcome":    trade.get("outcome", "—"),
        })

    return render_template("charts.html",
        state=state, chart_data=chart_data, today=today,
        now=datetime.now(IST).strftime("%H:%M IST"),
    )


@app.route("/screenshot/<date_str>/<filename>")
def serve_screenshot(date_str, filename):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    directory = os.path.join(base_dir, "screenshots", date_str)
    return send_from_directory(directory, filename)


@app.route("/eod", methods=["GET", "POST"])
def eod():
    """EOD trade evaluation — user enters exit prices."""
    state   = load_state()
    pending = get_pending_trades()

    if request.method == "POST":
        data = request.get_json()
        trade_id   = int(data.get("trade_id"))
        exit_price = float(data.get("exit_price", 0))
        user_note  = data.get("note", "")

        trade = get_trade_by_id(trade_id)
        if not trade:
            return jsonify({"error": "Trade not found"}), 404
        if trade["outcome"] != "PENDING":
            return jsonify({"error": "Trade is not awaiting an exit price"}), 400

        # Calculate PnL
        entry  = trade["entry"] or 0
        qty    = trade["quantity"] or 1
        action = trade["action"]

        if action == "BUY":
            pnl = (exit_price - entry) * qty
        else:
            pnl = (entry - exit_price) * qty

        outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"
        update_trade_result(trade_id, exit_price, round(pnl, 2), outcome)

        if user_note:
            add_user_note(trade_id, user_note)

        reasoning = json.loads(trade.get("reasoning", "[]"))
        learning = generate_trade_learning(
            trade["symbol"], action, trade.get("pattern", ""),
            pnl, reasoning, outcome
        )
        save_learning(learning, trade_id)

        # Update capital for live phase
        if state["phase"] == "LIVE":
            state["capital"] = round(state["capital"] + pnl, 2)
            state["total_pnl"] = round(state.get("total_pnl", 0) + pnl, 2)

        state["awaiting_eod_approval"] = bool(get_pending_trades())
        sync_daily_log_for_date(trade["date"], state)
        maybe_pause_for_daily_loss(state, trade["date"])
        save_state(state)

        return jsonify({
            "success": True,
            "pnl":     round(pnl, 2),
            "outcome": outcome,
        })

    return render_template("eod.html",
        state=state, pending=pending,
        now=datetime.now(IST).strftime("%H:%M IST"),
    )


@app.route("/history")
def history():
    """Full trade history with filters."""
    trades = get_all_trades(limit=200)
    logs   = get_daily_logs(limit=30)
    stats  = get_stats()
    learnings_raw = get_recent_learnings(limit=20)
    return render_template("history.html",
        trades=trades, logs=logs, stats=stats,
        learnings=learnings_raw,
    )


@app.route("/api/state")
def api_state():
    return jsonify(load_state())


@app.route("/api/proceed", methods=["POST"])
def api_proceed():
    state = load_state()
    state["paused"] = False
    state["awaiting_eod_approval"] = bool(get_pending_trades())
    state["risk_alert"] = ""
    save_state(state)
    return jsonify({"ok": True, "message": "Agent will run tomorrow."})


@app.route("/api/pause", methods=["POST"])
def api_pause():
    state = load_state()
    state["paused"] = True
    save_state(state)
    return jsonify({"ok": True, "message": "Agent paused."})


@app.route("/api/go_live", methods=["POST"])
def api_go_live():
    state = load_state()
    data  = request.get_json() or {}
    amt   = float(data.get("amount", LIVE_CAPITAL))

    state["phase"]   = "LIVE"
    state["capital"] = amt
    state["day_start_capital"] = amt
    state["paused"]  = False
    state["risk_alert"] = ""
    save_state(state)
    return jsonify({"ok": True, "message": f"Agent going LIVE with ₹{amt:,.0f}!"})


@app.route("/api/trades/<int:trade_id>/approve", methods=["POST"])
def api_approve_trade(trade_id: int):
    trade = get_trade_by_id(trade_id)
    if not trade:
        return jsonify({"error": "Trade not found"}), 404
    if trade["outcome"] not in ("AWAITING_APPROVAL", "PENDING"):
        return jsonify({"error": "Trade can no longer be approved"}), 400
    if trade["outcome"] == "AWAITING_APPROVAL" and len(get_pending_trades()) >= MAX_OPEN_POSITIONS:
        return jsonify({"error": f"Max open positions reached ({MAX_OPEN_POSITIONS}). Close the current trade first."}), 400

    update_trade_outcome(trade_id, "PENDING")
    state = load_state()
    sync_daily_log_for_date(trade["date"], state)
    return jsonify({"ok": True, "message": f"{trade['symbol']} approved for tracking."})


@app.route("/api/trades/<int:trade_id>/reject", methods=["POST"])
def api_reject_trade(trade_id: int):
    trade = get_trade_by_id(trade_id)
    if not trade:
        return jsonify({"error": "Trade not found"}), 404
    if trade["outcome"] != "AWAITING_APPROVAL":
        return jsonify({"error": "Only pending recommendations can be rejected"}), 400

    update_trade_outcome(trade_id, "REJECTED")
    state = load_state()
    sync_daily_log_for_date(trade["date"], state)
    return jsonify({"ok": True, "message": f"{trade['symbol']} rejected."})


@app.route("/api/run_now", methods=["POST"])
def api_run_now():
    """Trigger one manual worker cycle."""
    import threading
    from agent.runner import run_market_cycle

    def bg():
        run_market_cycle(manual=True)

    t = threading.Thread(target=bg, daemon=True)
    t.start()
    return jsonify({"ok": True, "message": "Worker cycle started in background."})


@app.route("/api/stats")
def api_stats():
    return jsonify({
        "stats":  get_stats(),
        "state":  load_state(),
        "logs":   get_daily_logs(5),
    })


# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print(f"\n🌐 Dashboard running at http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    print("   Open this in your browser.\n")
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False)
