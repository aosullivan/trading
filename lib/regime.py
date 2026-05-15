"""Market regime detection — maps current price-based signals to S1/S2/S3.

Signals checked:
  1. SPY vs 200-day moving average
  2. SPY drawdown from 1-year peak
  3. VIX level (^VIX)
  4. HY credit-spread proxy (HYG/LQD ratio)
  5. AHLT trend slope (5d vs 50d MA) — the user's own trend hedge

Composite score maps to regime:
  >= +4   : Scenario 1 (Bull continuation)
  -2..+3  : Transition (watch closely)
  -6..-3  : Scenario 2 (Pullback)
  <= -7   : Scenario 3 (Bubble pop / bear)

Results are cached for 15 minutes via lib.cache to avoid hammering Yahoo.
"""
from __future__ import annotations

from typing import Any

from lib.cache import _cache_get, _cache_set, _yf_rate_limited_download

REGIME_CACHE_KEY = "regime:current"
REGIME_CACHE_TTL_SECONDS = 15 * 60


def _fetch_closes(symbol: str, period: str) -> list[float]:
    cache_key = f"regime:closes:{symbol}:{period}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    df = _yf_rate_limited_download(
        symbol,
        period=period,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        return []
    close = df["Close"].dropna()
    if hasattr(close, "values") and close.values.ndim > 1:
        closes = [float(v) for v in close.values[:, 0]]
    else:
        closes = [float(v) for v in close.values]
    _cache_set(cache_key, closes, ttl=REGIME_CACHE_TTL_SECONDS)
    return closes


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _signal_spy_200dma(spy: list[float]) -> dict | None:
    spy_200 = _sma(spy, 200)
    if spy_200 is None or not spy:
        return None
    ratio = (spy[-1] / spy_200 - 1) * 100
    if ratio > 5:
        verdict, score = "Strong bull (>5% above 200dma)", 2
    elif ratio > 0:
        verdict, score = "Bull (above 200dma)", 1
    elif ratio > -5:
        verdict, score = "Wobble (just below 200dma)", -1
    elif ratio > -15:
        verdict, score = "Bear (well below 200dma)", -2
    else:
        verdict, score = "Deep bear (>15% below 200dma)", -3
    return {"name": "SPY vs 200dma", "value": f"{ratio:+.2f}%", "score": score, "verdict": verdict}


def _signal_spy_drawdown(spy: list[float]) -> dict | None:
    if not spy:
        return None
    drawdown = (spy[-1] / max(spy) - 1) * 100
    if drawdown > -3:
        verdict, score = "Near all-time highs", 2
    elif drawdown > -10:
        verdict, score = "Mild pullback", 0
    elif drawdown > -15:
        verdict, score = "Correction territory (S2 range)", -1
    elif drawdown > -25:
        verdict, score = "Bear market entry", -2
    else:
        verdict, score = "Severe bear", -3
    return {"name": "SPY drawdown from 1y peak", "value": f"{drawdown:+.2f}%", "score": score, "verdict": verdict}


def _signal_vix(vix: list[float]) -> dict | None:
    if not vix:
        return None
    v = vix[-1]
    if v < 15:
        verdict, score = "Complacency", 2
    elif v < 20:
        verdict, score = "Normal", 1
    elif v < 25:
        verdict, score = "Elevated", 0
    elif v < 35:
        verdict, score = "Stressed", -2
    else:
        verdict, score = "Panic", -3
    return {"name": "VIX", "value": f"{v:.2f}", "score": score, "verdict": verdict}


def _signal_hyg_lqd(hyg: list[float], lqd: list[float]) -> dict | None:
    if not hyg or not lqd or len(hyg) != len(lqd):
        return None
    ratios = [h / l for h, l in zip(hyg, lqd)]
    ratio_ma = _sma(ratios, 60)
    if ratio_ma is None:
        return None
    ratio_chg = (ratios[-1] / ratio_ma - 1) * 100
    if ratio_chg > 1:
        verdict, score = "Risk-on (HY outperforming IG)", 1
    elif ratio_chg > -1:
        verdict, score = "Neutral", 0
    elif ratio_chg > -3:
        verdict, score = "Mild HY weakness", -1
    else:
        verdict, score = "Credit stress", -2
    return {"name": "HYG/LQD vs 60d MA", "value": f"{ratio_chg:+.2f}%", "score": score, "verdict": verdict}


def _signal_ahlt_trend(ahlt: list[float]) -> dict | None:
    ahlt_5 = _sma(ahlt, 5)
    ahlt_50 = _sma(ahlt, 50)
    if ahlt_5 is None or ahlt_50 is None:
        return None
    slope = (ahlt_5 / ahlt_50 - 1) * 100
    if slope > 2:
        verdict, score = "Trend firing (bearish signal)", -2
    elif slope > 0:
        verdict, score = "Trend mildly up", -1
    elif slope > -2:
        verdict, score = "Trend flat", 0
    else:
        verdict, score = "Trend down (equity-friendly)", 1
    return {"name": "AHLT 5d vs 50d MA", "value": f"{slope:+.2f}%", "score": score, "verdict": verdict}


def _classify(score: int) -> dict[str, str]:
    if score >= 4:
        return {
            "label": "Scenario 1 — Bull continuation",
            "tag": "s1",
            "guidance": "HODL US equity. Use new contributions to build hedges toward S1 targets.",
        }
    if score >= -2:
        return {
            "label": "Scenario 1/2 transition — watch closely",
            "tag": "s1s2",
            "guidance": "Mixed signals. Maintain S1 posture; do not preemptively rotate. Watch for confirmation.",
        }
    if score >= -6:
        return {
            "label": "Scenario 2 — Pullback territory",
            "tag": "s2",
            "guidance": "HODL US equity. Accelerate DCA into bargains. Trim cash to ~6%.",
        }
    return {
        "label": "Scenario 3 — Bear / bubble pop",
        "tag": "s3",
        "guidance": "Rotate to defensive. Scale trend to 10-12%, US equity down to ~25%, raise cash to 12-15%.",
    }


def evaluate_regime(use_cache: bool = True, peek_only: bool = False) -> dict[str, Any]:
    if use_cache:
        cached = _cache_get(REGIME_CACHE_KEY)
        if cached is not None:
            return cached
    if peek_only:
        # The /positions HTML render uses this so the page doesn't block on
        # five rate-limited yfinance calls. JS auto-fetches /api/regime to
        # populate the panel as soon as the page loads.
        return {
            "regime": "Loading market regime…",
            "tag": "loading",
            "score": 0,
            "signals": [],
            "guidance": "Fetching SPY / VIX / HYG / LQD / AHLT signals…",
            "error": None,
        }

    try:
        spy = _fetch_closes("SPY", "1y")
        vix = _fetch_closes("^VIX", "3mo")
        hyg = _fetch_closes("HYG", "6mo")
        lqd = _fetch_closes("LQD", "6mo")
        ahlt = _fetch_closes("AHLT", "6mo")
    except Exception as exc:
        return {
            "error": f"Data fetch failed: {exc}",
            "regime": "Unknown",
            "score": None,
            "signals": [],
            "guidance": "Could not evaluate signals.",
        }

    signals = [
        s for s in (
            _signal_spy_200dma(spy),
            _signal_spy_drawdown(spy),
            _signal_vix(vix),
            _signal_hyg_lqd(hyg, lqd),
            _signal_ahlt_trend(ahlt),
        ) if s is not None
    ]
    score = sum(s["score"] for s in signals)
    classification = _classify(score)
    result = {
        "regime": classification["label"],
        "tag": classification["tag"],
        "guidance": classification["guidance"],
        "score": score,
        "signals": signals,
        "error": None,
    }
    _cache_set(REGIME_CACHE_KEY, result, ttl=REGIME_CACHE_TTL_SECONDS)
    return result
