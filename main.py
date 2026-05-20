"""
main.py — AI Vision Trading Agent dashboard

Runs only the Flask dashboard. The market worker should be started separately
via `python worker.py`.
"""

import logging
import os

from config import DASHBOARD_HOST, DASHBOARD_PORT, LOG_FILE
from data.db import init_db

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def run_dashboard():
    from dashboard.app import app
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    init_db()

    logger.info("=" * 55)
    logger.info("🤖 AI VISION TRADING AGENT v2")
    logger.info("   Dashboard process only.")
    logger.info("=" * 55)
    logger.info(f"   Dashboard: http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    logger.info("   Start the worker separately with: python worker.py")
    logger.info("   Press Ctrl+C to stop.\n")

    try:
        run_dashboard()
    except KeyboardInterrupt:
        logger.info("\n👋 Shutting down dashboard...")
