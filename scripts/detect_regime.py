#!/usr/bin/env python3
"""Detect current market regime (Scenario 1, 2, or 3) from price-based signals.

Signals checked:
  1. SPY vs 200-day moving average
  2. SPY drawdown from 1-year peak
  3. VIX level (^VIX)
  4. HY credit-spread proxy (HYG/LQD ratio, falling = stress)
  5. AHLT trend signal (50d MA slope as proxy for "trend up")

A point system maps to S1/S2/S3. Designed to be conservative — Scenario 3
only fires when several signals confirm at once.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fetch(symbol: str, period: str = "1y") -> "tuple[list[float], list[str]]":
    hist = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    closes = hist["Close"].dropna().tolist()
    dates = [d.strftime("%Y-%m-%d") for d in hist.index]
    return closes, dates


def sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def evaluate() -> dict:
    spy, _ = fetch("SPY", "1y")
    vix, _ = fetch("^VIX", "3mo")
    hyg, _ = fetch("HYG", "6mo")
    lqd, _ = fetch("LQD", "6mo")
    ahlt, _ = fetch("AHLT", "6mo")

    signals: list[dict] = []
    score = 0  # negative = bearish, positive = bullish

    # 1. SPY vs 200-day MA
    spy_now = spy[-1]
    spy_200 = sma(spy, 200)
    if spy_200:
        ratio = (spy_now / spy_200 - 1) * 100
        if ratio > 5:
            verdict, pts = "Strong bull (>5% above 200dma)", 2
        elif ratio > 0:
            verdict, pts = "Bull (above 200dma)", 1
        elif ratio > -5:
            verdict, pts = "Wobble (just below 200dma)", -1
        elif ratio > -15:
            verdict, pts = "Bear (well below 200dma)", -2
        else:
            verdict, pts = "Deep bear (>15% below 200dma)", -3
        signals.append({"name": "SPY vs 200dma", "value": f"{ratio:+.2f}%", "verdict": verdict, "score": pts})
        score += pts

    # 2. SPY drawdown from 1y peak
    peak = max(spy)
    drawdown = (spy_now / peak - 1) * 100
    if drawdown > -3:
        verdict, pts = "Near all-time highs", 2
    elif drawdown > -10:
        verdict, pts = "Mild pullback", 0
    elif drawdown > -15:
        verdict, pts = "Correction territory (S2 range)", -1
    elif drawdown > -25:
        verdict, pts = "Bear market entry", -2
    else:
        verdict, pts = "Severe bear", -3
    signals.append({"name": "SPY drawdown from 1y peak", "value": f"{drawdown:+.2f}%", "verdict": verdict, "score": pts})
    score += pts

    # 3. VIX
    vix_now = vix[-1]
    if vix_now < 15:
        verdict, pts = "Complacency", 2
    elif vix_now < 20:
        verdict, pts = "Normal", 1
    elif vix_now < 25:
        verdict, pts = "Elevated", 0
    elif vix_now < 35:
        verdict, pts = "Stressed", -2
    else:
        verdict, pts = "Panic", -3
    signals.append({"name": "VIX", "value": f"{vix_now:.2f}", "verdict": verdict, "score": pts})
    score += pts

    # 4. HYG / LQD ratio (proxy for HY-IG spread). Falling => HY underperforming => spreads widening
    hyg_lqd_now = hyg[-1] / lqd[-1]
    hyg_lqd_ma = sma([h / l for h, l in zip(hyg, lqd)], 60)
    if hyg_lqd_ma:
        ratio_chg = (hyg_lqd_now / hyg_lqd_ma - 1) * 100
        if ratio_chg > 1:
            verdict, pts = "Risk-on (HY outperforming)", 1
        elif ratio_chg > -1:
            verdict, pts = "Neutral", 0
        elif ratio_chg > -3:
            verdict, pts = "Mild HY weakness", -1
        else:
            verdict, pts = "Credit stress", -2
        signals.append({"name": "HYG/LQD vs 60d MA", "value": f"{ratio_chg:+.2f}%", "verdict": verdict, "score": pts})
        score += pts

    # 5. AHLT trend slope (5d vs 50d MA — if 5d > 50d and rising, trend regime is firing)
    ahlt_5 = sma(ahlt, 5)
    ahlt_50 = sma(ahlt, 50)
    if ahlt_5 and ahlt_50:
        slope_pct = (ahlt_5 / ahlt_50 - 1) * 100
        if slope_pct > 2:
            verdict, pts = "Trend firing (bearish for equities)", -2
        elif slope_pct > 0:
            verdict, pts = "Trend mildly up", -1
        elif slope_pct > -2:
            verdict, pts = "Trend flat", 0
        else:
            verdict, pts = "Trend down (equity-friendly)", 1
        signals.append({"name": "AHLT 5d vs 50d MA", "value": f"{slope_pct:+.2f}%", "verdict": verdict, "score": pts})
        score += pts

    if score >= 4:
        regime = "Scenario 1 — Bull continuation"
    elif score >= -2:
        regime = "Scenario 1/2 transition — watch closely"
    elif score >= -6:
        regime = "Scenario 2 — Pullback territory"
    else:
        regime = "Scenario 3 — Bear / bubble pop"

    return {"regime": regime, "score": score, "signals": signals}


def main() -> int:
    result = evaluate()
    print(f"\nCurrent regime: {result['regime']}  (composite score {result['score']:+d})\n")
    print(f"{'Signal':<30} {'Value':>12} {'Score':>7}  Verdict")
    print("-" * 100)
    for s in result["signals"]:
        print(f"{s['name']:<30} {s['value']:>12} {s['score']:>+7}  {s['verdict']}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
