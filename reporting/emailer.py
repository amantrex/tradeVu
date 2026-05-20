import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

import pytz

from config import (
    EMAIL_ENABLED, REPORT_EMAIL_FROM, REPORT_EMAIL_TO, SMTP_HOST, SMTP_PASSWORD,
    SMTP_PORT, SMTP_USERNAME, SMTP_USE_TLS, TIMEZONE,
)
from reporting.report_builder import build_eod_report

IST = pytz.timezone(TIMEZONE)


def send_eod_report_email(trade_date: str | None = None) -> dict:
    trade_date = trade_date or datetime.now(IST).date().isoformat()
    report = build_eod_report(trade_date)

    if not EMAIL_ENABLED:
        return {
            "status": "DISABLED",
            "message": "Email delivery skipped because EMAIL_ENABLED is false.",
            "report": report,
        }

    required = [SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, REPORT_EMAIL_FROM, REPORT_EMAIL_TO]
    if not all(required):
        return {
            "status": "MISSING_CONFIG",
            "message": "Email delivery skipped because SMTP settings are incomplete.",
            "report": report,
        }

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"AI Vision Trader EOD Report — {trade_date}"
    msg["From"] = REPORT_EMAIL_FROM
    msg["To"] = REPORT_EMAIL_TO

    body = MIMEMultipart("alternative")
    body.attach(MIMEText(report["html"], "html"))
    msg.attach(body)

    if report.get("csv"):
        part = MIMEApplication(report["csv"].encode('utf-8'), Name=f"trades_{trade_date}.csv")
        part['Content-Disposition'] = f'attachment; filename="trades_{trade_date}.csv"'
        msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            if SMTP_USE_TLS:
                smtp.starttls()
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.sendmail(REPORT_EMAIL_FROM, [REPORT_EMAIL_TO], msg.as_string())
        return {
            "status": "SENT",
            "message": f"EOD report sent to {REPORT_EMAIL_TO}.",
            "report": report,
        }
    except Exception as exc:
        return {
            "status": "FAILED",
            "message": f"EOD report failed to send: {exc}",
            "report": report,
        }
