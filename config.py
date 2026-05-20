"""
config.py — AI Vision Trading Agent v2
No broker API. No KYC. Just chart screenshots + Gemini 3.1 vision + your decisions.
"""

import os
from dotenv import load_dotenv
load_dotenv()

# ── Gemini ─────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_KEY_HERE")
# Default to a lower-latency model for repeated chart analysis runs.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash")

# ── Your 20-stock basket (diverse sectors) ─────────────────────────────────────
# Format: (display_name, TradingView_symbol)
STOCK_BASKET = [
    # 🏦 Banking & Finance
    ("HDFCBANK",   "NSE:HDFCBANK"),
    ("ICICIBANK",  "NSE:ICICIBANK"),
    ("SBIN",       "NSE:SBIN"),
    ("KOTAKBANK",  "NSE:KOTAKBANK"),
    ("RECLTD",     "NSE:RECLTD"),

    # 💻 IT & Tech
    ("TCS",        "NSE:TCS"),
    ("INFY",       "NSE:INFY"),
    ("WIPRO",      "NSE:WIPRO"),
    ("HCLTECH",    "NSE:HCLTECH"),

    # ⚡ Energy & Power
    ("RELIANCE",   "NSE:RELIANCE"),
    ("NTPC",       "NSE:NTPC"),
    ("POWERGRID",  "NSE:POWERGRID"),
    ("ADANIGREEN", "NSE:ADANIGREEN"),

    # 🏭 Manufacturing & Auto
    ("MARUTI",     "NSE:MARUTI"),
    ("TATAMOTORS", "NSE:TATAMOTORS"),
    ("BAJAJ_AUTO", "NSE:BAJAJ_AUTO"),

    # 🏥 Pharma & FMCG
    ("SUNPHARMA",  "NSE:SUNPHARMA"),
    ("DRREDDY",    "NSE:DRREDDY"),
    ("HINDUNILVR", "NSE:HINDUNILVR"),

    # 📦 Infra & Conglomerate
    ("LT",         "NSE:LT"),
]

# ── Screenshot settings ─────────────────────────────────────────────────────────
CHART_TIMEFRAME   = "15"         # 15-minute candles for intraday
CHART_WIDTH       = 1400
CHART_HEIGHT      = 700
CHART_THEME       = "dark"       # "dark" or "light"
SCREENSHOT_DIR    = "screenshots"

# How long to wait for chart to render (ms) — increase if charts load slow
CHART_LOAD_WAIT_MS = 4000

# ── Trading / Risk rules ────────────────────────────────────────────────────────
PAPER_CAPITAL         = 10_000   # ₹ for observation phase
LIVE_CAPITAL          = 1_000    # ₹ when you go live manually
DEMO_DAYS             = 5        # Paper-trading demo period before going live
RISK_PER_TRADE_PCT    = 1.0      # Risk budget per trade (% of capital)
MAX_SL_PCT            = 1.25     # Stoploss max distance from entry (%)
MIN_RR_RATIO          = 2.0      # Minimum risk:reward ratio
MAX_DAILY_LOSS_PCT    = 15.0     # Agent flags a warning above this
MIN_CONFIDENCE        = 60       # Skip if model confidence < this
MAX_TRADES_PER_DAY    = 2        # Only keep the best 2 setups per day
MAX_OPEN_POSITIONS    = 1        # Only one approved open position at a time
MAX_POSITION_CAPITAL_PCT = 30.0  # Cap single-position exposure

# ── Intraday execution window ───────────────────────────────────────────────────
CAPTURE_START_HOUR    = 9
CAPTURE_START_MINUTE  = 25
ENTRY_START_HOUR      = 9
ENTRY_START_MINUTE    = 45
ENTRY_END_HOUR        = 13
ENTRY_END_MINUTE      = 30
MARKET_CLOSE_HOUR     = 15
MARKET_CLOSE_MINUTE   = 25
REPORT_HOUR           = 17
REPORT_MINUTE         = 0
WORKER_INTERVAL_MINUTES = 10

# ── Scheduler ───────────────────────────────────────────────────────────────────
TIMEZONE              = "Asia/Kolkata"
MORNING_HOUR          = 9
MORNING_MINUTE        = 45       # Screenshot + analysis run at 9:45 AM IST
EOD_HOUR              = 15
EOD_MINUTE            = 25       # EOD report at 3:25 PM IST

# ── Web dashboard ───────────────────────────────────────────────────────────────
DASHBOARD_HOST        = "127.0.0.1"
DASHBOARD_PORT        = 8080
FLASK_SECRET_KEY      = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")

# ── Email reporting ─────────────────────────────────────────────────────────────
EMAIL_ENABLED         = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
SMTP_HOST             = os.getenv("SMTP_HOST", "")
SMTP_PORT             = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME         = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD         = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS          = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
REPORT_EMAIL_FROM     = os.getenv("REPORT_EMAIL_FROM", SMTP_USERNAME)
REPORT_EMAIL_TO       = os.getenv("REPORT_EMAIL_TO", "")

# ── Google Sheets (optional) ────────────────────────────────────────────────────
GOOGLE_CREDENTIALS_FILE = "credentials.json"
GOOGLE_SHEET_NAME       = "AI Vision Trader Log"
ENABLE_GOOGLE_SHEETS    = False   # Set True once you have credentials.json

# ── Files ────────────────────────────────────────────────────────────────────────
STATE_FILE  = "agent_state.json"
DB_FILE     = "data/trades.db"
LOG_FILE    = "logs/agent.log"
WORKER_LOG_FILE = "logs/worker.log"
