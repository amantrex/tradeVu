import csv
import io
from datetime import datetime

import pytz

from config import TIMEZONE
from data.db import (
    get_analysis_runs_for_date, get_daily_trade_summary, get_recent_learnings,
    get_trades_for_date,
)

IST = pytz.timezone(TIMEZONE)


def build_eod_report(trade_date: str) -> dict:
    trades = [t for t in get_trades_for_date(trade_date) if t["action"] in ("BUY", "SELL")]
    analyses = get_analysis_runs_for_date(trade_date)
    summary = get_daily_trade_summary(trade_date)
    learnings = get_recent_learnings(limit=10)

    html = [
        "<html><body style='font-family:Arial,sans-serif;color:#111;'>",
        f"<h2>AI Vision Trader EOD Report — {trade_date}</h2>",
        f"<p>Generated at {datetime.now(IST).strftime('%H:%M IST')}</p>",
        "<h3>Summary</h3>",
        "<ul>",
        f"<li>Total analyses: {len(analyses)}</li>",
        f"<li>Mock trades tracked: {summary['total_trades']}</li>",
        f"<li>Wins: {summary['wins']}</li>",
        f"<li>Losses: {summary['losses']}</li>",
        f"<li>Total P&amp;L: ₹{summary['total_pnl']:.2f}</li>",
        "</ul>",
        "<h3>Trades</h3>",
        "<table border='1' cellspacing='0' cellpadding='6'>",
        "<tr><th>Symbol</th><th>Action</th><th>Entry</th><th>SL</th><th>Target</th><th>Exit</th><th>Outcome</th><th>P&L</th><th>Reason</th></tr>",
    ]
    for trade in trades:
        html.append(
            f"<tr><td>{trade['symbol']}</td><td>{trade['action']}</td>"
            f"<td>{trade['entry'] or '—'}</td><td>{trade['stoploss'] or '—'}</td>"
            f"<td>{trade['target'] or '—'}</td><td>{trade['exit_price'] or '—'}</td>"
            f"<td>{trade['outcome']}</td><td>{trade['pnl'] or 0:.2f}</td>"
            f"<td>{trade.get('exit_reason') or '—'}</td></tr>"
        )
    html.extend(["</table>", "<h3>Recent Learnings</h3>"])
    if learnings and learnings != "No learnings yet — first day of observation!":
        html.append("<ul>")
        for line in learnings.split("\n"):
            item = line[2:] if line.startswith("• ") else line
            html.append(f"<li>{item}</li>")
        html.append("</ul>")
    else:
        html.append("<p>No learnings captured yet.</p>")
    html.append("</body></html>")

    # Build CSV
    csv_output = io.StringIO()
    writer = csv.writer(csv_output)
    writer.writerow(["Symbol", "Action", "Entry", "SL", "Target", "Exit", "Outcome", "P&L", "Reason"])
    for trade in trades:
        writer.writerow([
            trade['symbol'], trade['action'], trade['entry'] or '', trade['stoploss'] or '',
            trade['target'] or '', trade['exit_price'] or '', trade['outcome'], trade['pnl'] or 0,
            trade.get('exit_reason', '')
        ])
    csv_string = csv_output.getvalue()

    return {
        "trade_date": trade_date,
        "summary": summary,
        "trades": trades,
        "analyses": analyses,
        "learnings": learnings,
        "html": "".join(html),
        "csv": csv_string,
    }
