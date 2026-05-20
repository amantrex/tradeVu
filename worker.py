"""
worker.py — separate intraday worker process

Captures TradingView screenshots every 10 minutes during the business day,
analyzes them with Gemini 3.1, manages mock trades, runs EOD closeout, and sends
an end-of-day email report when email credentials are configured.
"""

import logging
import os
import time
from datetime import datetime

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from agent.runner import load_state, run_eod_closeout, run_market_cycle, save_state
from config import (
    TIMEZONE, WORKER_LOG_FILE, REPORT_HOUR, REPORT_MINUTE,
)
from data.db import init_db, save_worker_event
from reporting.emailer import send_eod_report_email

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(WORKER_LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)
IST = pytz.timezone(TIMEZONE)


def _run_cycle_job():
    state = load_state()
    if state.get("paused"):
        logger.info("⏸  Worker paused — skipping scheduled cycle.")
        return
    run_market_cycle(manual=False)


def _run_closeout_job():
    result = run_eod_closeout()
    logger.info(f"🌆 Closeout result: {result}")


def _run_report_job():
    result = send_eod_report_email()
    state = load_state()
    state["last_report_at"] = datetime.now(IST).isoformat(timespec="seconds")
    state["last_report_status"] = result["status"]
    save_state(state)
    save_worker_event("EMAIL_REPORT", result["message"])
    logger.info(f"📧 Report job: {result['message']}")


def run_worker():
    scheduler = BackgroundScheduler(timezone=IST)
    scheduler.add_job(
        _run_cycle_job,
        trigger="cron",
        day_of_week="mon-fri",
        hour="9-15",
        minute="5,15,25,35,45,55",
        id="market-cycle",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_closeout_job,
        trigger="cron",
        day_of_week="mon-fri",
        hour=15,
        minute=35,
        id="eod-closeout",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_report_job,
        trigger="cron",
        day_of_week="mon-fri",
        hour=REPORT_HOUR,
        minute=REPORT_MINUTE,
        id="eod-email-report",
        replace_existing=True,
    )
    scheduler.start()

    logger.info("=" * 55)
    logger.info("🤖 AI VISION TRADING AGENT WORKER")
    logger.info("   Separate worker process for screenshot, analysis, closeout, and reporting.")
    logger.info("=" * 55)
    logger.info("   Market cycle: weekdays every 10 minutes during market hours")
    logger.info("   EOD closeout: weekdays at 15:35 IST")
    logger.info(f"   EOD email report: weekdays at {REPORT_HOUR:02d}:{REPORT_MINUTE:02d} IST")
    logger.info("   Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("\n👋 Shutting down worker...")
        scheduler.shutdown()


if __name__ == "__main__":
    init_db()
    run_worker()
