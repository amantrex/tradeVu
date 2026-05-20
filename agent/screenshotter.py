"""
agent/screenshotter.py — TradingView chart screenshotter using Playwright

Takes a headless screenshot of each stock's 15-min chart on TradingView.
No login required for basic charts.

Install once:
    pip install playwright
    python -m playwright install chromium
"""

import asyncio
import shutil
from datetime import datetime
from pathlib import Path
import pytz

from config import (
    STOCK_BASKET, CHART_TIMEFRAME, CHART_WIDTH, CHART_HEIGHT,
    CHART_THEME, SCREENSHOT_DIR, CHART_LOAD_WAIT_MS, TIMEZONE
)

IST = pytz.timezone(TIMEZONE)


def tradingview_url(tv_symbol: str, timeframe: str, theme: str) -> str:
    """Build a TradingView chart URL that loads cleanly without sidebars."""
    # This URL format opens the chart in a clean widget-style view
    return (
        f"https://www.tradingview.com/chart/"
        f"?symbol={tv_symbol}"
        f"&interval={timeframe}"
        f"&theme={theme}"
        f"&style=1"          # Candlestick
        f"&toolbar_bg=%23f1f3f6"
        f"&hide_side_toolbar=1"
        f"&allow_symbol_change=0"
        f"&save_image=0"
        f"&studies=RSI%40tv-basicstudies%1FMACD%40tv-basicstudies"
    )


async def screenshot_single(page, name: str, tv_symbol: str,
                              date_str: str, time_slug: str) -> dict | None:
    """
    Screenshot a single stock chart. Returns latest/archive paths or None on error.
    """
    url = tradingview_url(tv_symbol, CHART_TIMEFRAME, CHART_THEME)
    latest_dir = Path(SCREENSHOT_DIR) / date_str
    archive_dir = latest_dir / time_slug
    latest_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    latest_path = latest_dir / f"{name}.png"
    archive_path = archive_dir / f"{name}.png"

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        # Wait for the chart canvas to appear
        await page.wait_for_selector("canvas", timeout=15_000)

        # Extra wait for data to render
        await page.wait_for_timeout(CHART_LOAD_WAIT_MS)

        # Hide cookie banners and popups if present
        await page.evaluate("""() => {
            const selectors = [
                '[class*="cookie"]', '[class*="banner"]',
                '[class*="dialog"]', '[class*="popup"]',
                '[class*="notification"]', '[id*="cookie"]'
            ];
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => el.remove());
            });
        }""")

        await page.screenshot(path=str(archive_path), full_page=False)
        shutil.copyfile(archive_path, latest_path)
        print(f"  📸 {name}: {archive_path}")
        return {
            "latest_path": str(latest_path),
            "archive_path": str(archive_path),
            "time_slug": time_slug,
        }

    except Exception as e:
        print(f"  ⚠️  Failed to screenshot {name}: {e}")
        return None


async def screenshot_all_stocks() -> dict[str, dict]:
    """
    Screenshot all 20 stocks. Returns {symbol: {latest_path, archive_path}} dict.
    Uses a single persistent browser for efficiency.
    """
    from playwright.async_api import async_playwright

    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    time_str = datetime.now(IST).strftime("%H:%M")
    time_slug = datetime.now(IST).strftime("%H-%M")
    results  = {}

    print(f"\n📸 Screenshotting {len(STOCK_BASKET)} charts at {time_str} IST...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1400,700",
            ]
        )

        # One page, reused for all stocks (faster than new page each time)
        page = await browser.new_page(
            viewport={"width": CHART_WIDTH, "height": CHART_HEIGHT},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )

        for name, tv_symbol in STOCK_BASKET:
            paths = await screenshot_single(page, name, tv_symbol, date_str, time_slug)
            if paths:
                results[name] = paths
            # Small delay between stocks to be respectful
            await asyncio.sleep(1.5)

        await browser.close()

    print(f"\n  ✅ {len(results)}/{len(STOCK_BASKET)} charts captured.")
    return results


def run_screenshots() -> dict[str, dict]:
    """Synchronous wrapper — call this from the scheduler."""
    return asyncio.run(screenshot_all_stocks())


if __name__ == "__main__":
    results = run_screenshots()
    print(f"\nSaved {len(results)} screenshots:")
    for name, paths in results.items():
        print(f"  {name}: {paths['archive_path']}")
