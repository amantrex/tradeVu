"""
agent/vision_analyst.py — Gemini vision chart analyzer

Sends chart screenshots to Gemini as images.
The model reads the candlesticks, volume, and indicators visually —
just like a human trader would look at a chart.
"""

import json
from pathlib import Path

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL
from data.db import get_recent_learnings

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """You are an expert intraday stock trader analyzing NSE Indian market charts.

You will be shown a TradingView chart screenshot. Analyze it visually and make a precise trade decision.

This strategy is strict. Only propose clean breakout or breakdown trades after the opening noise has settled.

## What to look for
- Candlestick patterns: engulfing, doji, hammer, shooting star, inside bar
- Trend: higher highs/lows (bullish) or lower highs/lows (bearish)
- Support and resistance levels from recent price action
- Volume: is it confirming the move? Spike = conviction
- RSI: overbought (>70), oversold (<30), divergence
- MACD: crossovers, histogram direction
- EMA crossovers if visible

## Indian market context
- Market opens 9:15 AM IST, closes 3:30 PM IST
- Morning volatility (9:15–10:00) is highest — patterns are less reliable
- Preferred entry window is 9:45 AM to 1:30 PM IST
- Avoid trading against Nifty 50 broad direction

## Risk rules (STRICT — never violate)
- Only take breakout or breakdown setups confirmed by candle close and volume
- Enter only after a candle has closed beyond support or resistance
- Stoploss must come from structure first, then be capped at ≤ 1.25% from entry price
- Risk:Reward must be ≥ 1:2
- Only recommend action if confidence ≥ 60%
- When in doubt, say NO_ACTION — patience is a position

## Response format
Respond ONLY in this exact JSON (no markdown, no explanation):
{
  "action": "BUY" | "SELL" | "NO_ACTION",
  "current_price": <float or null>,
  "entry_price": <float or null>,
  "stoploss": <float or null>,
  "target": <float or null>,
  "confidence": <int 0-100>,
  "pattern": "<detected pattern or None>",
  "trend": "BULLISH" | "BEARISH" | "SIDEWAYS",
  "rr_ratio": <float>,
  "reasoning": ["<point 1>", "<point 2>", "<point 3>"],
  "risk_note": "<any caution or None>"
}"""


def analyze_chart(symbol: str, image_path: str,
                  capital: float, phase: str) -> dict:
    """
    Send chart image to Gemini for visual analysis.
    Returns structured trade decision.
    """
    if not Path(image_path).exists():
        return _no_action(symbol, "Chart image not found")

    learnings = get_recent_learnings(limit=10)
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    prompt = f"""Analyze this {symbol} chart (NSE, 15-minute timeframe).

Phase: {phase} ({'Paper trade — no real money' if phase == 'OBSERVE' else f'LIVE — ₹{capital:,.0f} real capital'})
Available capital: ₹{capital:,.0f}

Past learnings from my trading history:
{learnings}

Look at the chart carefully. What do you see? Make a trade decision."""

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type="image/png",
                ),
                prompt
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
            )
        )

        raw = (response.text or "").strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        decision = json.loads(raw.strip())
        decision["symbol"] = symbol
        decision["image_path"] = image_path

        usage = response.usage_metadata
        prompt_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        candidates_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
        cached_tokens = getattr(usage, "cached_content_token_count", 0) if usage else 0
        print(f"    🧠 {symbol}: {decision['action']} | "
              f"Confidence: {decision['confidence']}% | "
              f"Pattern: {decision.get('pattern','?')} | "
              f"Tokens in:{prompt_tokens} "
              f"cached:{cached_tokens} out:{candidates_tokens}")

        return decision

    except json.JSONDecodeError as e:
        print(f"  ❌ JSON error for {symbol}: {e}")
        return _no_action(symbol, "Parse error")
    except Exception as e:
        print(f"  ❌ Vision API error for {symbol}: {e}")
        return _no_action(symbol, str(e))


def generate_trade_learning(symbol: str, action: str, pattern: str,
                            pnl: float, reasoning: list, outcome: str) -> str:
    """Ask Gemini to extract one learning from a completed trade."""
    prompt = f"""I completed a trade. Extract ONE concise lesson.

Symbol: {symbol}
Action: {action}
Pattern I saw: {pattern}
My reasoning: {'; '.join(reasoning)}
Outcome: {outcome}
Result: ₹{pnl:.2f}

If the trade lost, focus on what to avoid.
If the trade won, focus on what to repeat.

Format:
- For a loss: "LOSS: When [condition], avoid [action] because [reason]"
- For a win: "WIN: When [condition], repeat [action] because [reason]"
- For breakeven: "BREAKEVEN: When [condition], watch [factor] because [reason]"
One sentence only."""

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        return (response.text or "").strip()
    except Exception:
        return f"Trade on {symbol} lost — review the {pattern} setup conditions."


def _no_action(symbol: str, reason: str) -> dict:
    return {
        "action": "NO_ACTION",
        "current_price": None,
        "entry_price": None,
        "stoploss": None,
        "target": None,
        "confidence": 0,
        "pattern": "None",
        "trend": "UNKNOWN",
        "rr_ratio": 0.0,
        "reasoning": [f"Skipped: {reason}"],
        "risk_note": None,
        "symbol": symbol,
        "image_path": "",
    }
