"""Market regime detection — maps current price-based signals to S1/S2/S3.

Signals checked:
  1. SPY vs 200-day moving average
  2. SPY drawdown from 1-year peak
  3. VIX level (^VIX)
  4. HY credit-spread proxy (HYG/LQD ratio)
  5. AHLT trend slope (5d vs 50d MA) — the user's own trend hedge

Allocation strategy:
  SPY drawdown <= -5% from 1y peak   : move toward Confident Bull
  SPY drawdown <= -10% from 1y peak  : move toward Bubble Pop (S3)

Composite score is still shown as supporting evidence, but the staged
allocation trigger controls S2/S3 rotation so de-risking follows a simple
price-based glide path.

Results are cached for 15 minutes via lib.cache to avoid hammering Yahoo.
"""
from __future__ import annotations

from typing import Any

from lib.cache import _cache_get, _cache_set, _yf_rate_limited_download

REGIME_CACHE_KEY = "regime:current"
REGIME_CACHE_TTL_SECONDS = 15 * 60
DRAWDOWN_TRIGGER_EPSILON = 1e-9


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
    drawdown = _spy_drawdown_pct(spy)
    if drawdown is None:
        return None
    if _trigger_reached(drawdown, -25):
        verdict, score = "Severe bear", -3
    elif _trigger_reached(drawdown, -15):
        verdict, score = "Bear market entry", -2
    elif _trigger_reached(drawdown, -10):
        verdict, score = "Bubble Pop trigger (-10%)", -2
    elif _trigger_reached(drawdown, -5):
        verdict, score = "Confident Bull trigger (-5%)", -1
    elif _trigger_reached(drawdown, -3):
        verdict, score = "Early pullback; stay Max Conviction", 0
    else:
        verdict, score = "Near all-time highs", 2
    return {"name": "SPY drawdown from 1y peak", "value": f"{drawdown:+.2f}%", "score": score, "verdict": verdict}


def _trigger_reached(drawdown: float, threshold: float) -> bool:
    return drawdown <= threshold + DRAWDOWN_TRIGGER_EPSILON


def _spy_drawdown_pct(spy: list[float]) -> float | None:
    if not spy:
        return None
    return (spy[-1] / max(spy) - 1) * 100


def _allocation_trigger_signal(spy_drawdown: float | None) -> dict | None:
    if spy_drawdown is None:
        return None
    if _trigger_reached(spy_drawdown, -10):
        verdict = "Move to Bubble Pop (S3)"
        score = -2
    elif _trigger_reached(spy_drawdown, -5):
        verdict = "Move to Confident Bull"
        score = -1
    else:
        verdict = "Stay Max Conviction"
        score = 1
    return {
        "name": "Allocation trigger",
        "value": f"{spy_drawdown:+.2f}%",
        "score": score,
        "verdict": verdict,
    }


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


def _classify(score: int, spy_drawdown: float | None = None) -> dict[str, str]:
    if spy_drawdown is not None and _trigger_reached(spy_drawdown, -10):
        return {
            "label": "Scenario 3 — Bubble Pop trigger",
            "tag": "s3",
            "guidance": "SPY is down at least 10% from its 1-year peak. Move toward Bubble Pop (S3): US equity ~25%, money-market cash ~19%, trend ~12%, gold ~10%.",
        }
    if spy_drawdown is not None and _trigger_reached(spy_drawdown, -5):
        return {
            "label": "Scenario 2 — Confident Bull trigger",
            "tag": "s2",
            "guidance": "SPY is down at least 5% from its 1-year peak. Move gradually toward Confident Bull before the next leg lower.",
        }
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
            "label": "Scenario 1/2 stress — wait for price trigger",
            "tag": "s1s2",
            "guidance": "Stress is building, but the -5% drawdown trigger has not fired. Prepare Confident Bull trades; wait for price confirmation.",
        }
    return {
        "label": "Scenario 2 — severe stress, awaiting -10% trigger",
        "tag": "s2",
        "guidance": "Composite stress is severe. Move toward Confident Bull, favoring productive money-market cash and trend, but reserve full Bubble Pop rotation for the -10% SPY drawdown trigger.",
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

    spy_drawdown = _spy_drawdown_pct(spy)
    signals = [
        s for s in (
            _allocation_trigger_signal(spy_drawdown),
            _signal_spy_200dma(spy),
            _signal_spy_drawdown(spy),
            _signal_vix(vix),
            _signal_hyg_lqd(hyg, lqd),
            _signal_ahlt_trend(ahlt),
        ) if s is not None
    ]
    score = sum(s["score"] for s in signals)
    classification = _classify(score, spy_drawdown=spy_drawdown)
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
