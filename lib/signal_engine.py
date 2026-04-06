"""Forward-looking signal generator with position sizing.

Computes the current ribbon regime direction and recommended position size
for a given ticker, reusing the same indicator math as the chart/backtest
pipeline.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from lib.backtesting import build_weekly_confirmed_ribbon_direction
from lib.data_fetching import cached_download
from lib.settings import DAILY_WARMUP_DAYS
from lib.technical_indicators import compute_trend_ribbon
from lib.trend_ribbon_profile import (
    trend_ribbon_regime_kwargs,
    trend_ribbon_signal_kwargs,
)


def _carry_neutral(direction: pd.Series) -> pd.Series:
    return direction.replace(0, pd.NA).ffill().fillna(0).astype(int)


def _align_weekly(weekly_dir: pd.Series, daily_index: pd.Index) -> pd.Series:
    return weekly_dir.reindex(daily_index).ffill().bfill().fillna(0).astype(int)


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.sort_index()
        .resample("W-FRI")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna()
    )


def _compute_atr(df: pd.DataFrame, period: int = 20) -> float | None:
    if len(df) < period + 1:
        return None
    highs = df["High"]
    lows = df["Low"]
    closes = df["Close"]
    tr_vals = []
    for j in range(len(df) - period, len(df)):
        hi, lo = float(highs.iloc[j]), float(lows.iloc[j])
        prev_c = float(closes.iloc[j - 1])
        tr_vals.append(max(hi - lo, abs(hi - prev_c), abs(lo - prev_c)))
    return sum(tr_vals) / len(tr_vals)


def _compute_vol_position_size(
    df: pd.DataFrame,
    capital: float,
    vol_scale_factor: float = 0.001,
    vol_lookback: int = 100,
) -> float:
    start = max(0, len(df) - vol_lookback)
    if len(df) - start < 2:
        return 0.0
    changes = df["Close"].iloc[start:].diff().dropna()
    stddev = float(changes.std()) if len(changes) > 1 else 0.0
    if stddev <= 0:
        return 0.0
    return vol_scale_factor * capital / stddev


def _compute_fixed_fraction_position_size(
    df: pd.DataFrame,
    capital: float,
    risk_fraction: float = 0.01,
    stop_dist: float | None = None,
) -> float:
    risk_per_share = stop_dist
    if risk_per_share is None or risk_per_share <= 0:
        atr = _compute_atr(df)
        price = float(df["Close"].iloc[-1])
        risk_per_share = atr if atr and atr > 0 else price * 0.02
    return (capital * risk_fraction) / risk_per_share


def _compute_stop_level(
    df: pd.DataFrame,
    stop_type: str = "atr",
    stop_atr_multiple: float = 3.0,
    stop_pct: float = 0.05,
) -> tuple[float | None, float | None]:
    """Return (stop_level, stop_distance) for the latest bar."""
    price = float(df["Close"].iloc[-1])
    if stop_type == "atr":
        atr = _compute_atr(df)
        if atr is not None and atr > 0:
            dist = atr * stop_atr_multiple
            return round(price - dist, 2), dist
        return None, None
    elif stop_type == "pct":
        dist = price * stop_pct
        return round(price - dist, 2), dist
    return None, None


def _fetch_ohlcv(ticker: str) -> pd.DataFrame | None:
    from datetime import datetime, timedelta

    end_date = datetime.now().strftime("%Y-%m-%d")
    warmup_days = DAILY_WARMUP_DAYS
    start_date = (datetime.now() - timedelta(days=warmup_days)).strftime("%Y-%m-%d")
    try:
        df = cached_download(ticker, interval="1d", start=start_date, end=end_date, progress=False)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep="last")]
    return df.sort_index()


def compute_ticker_signal(ticker: str, settings: dict) -> dict:
    """Compute the current ribbon regime signal and position size for a ticker."""
    df = _fetch_ohlcv(ticker)
    if df is None or len(df) < 50:
        return {
            "ticker": ticker,
            "direction": "NO_DATA",
            "last_flip_date": None,
            "price": None,
            "atr": None,
            "shares": 0,
            "notional": 0,
            "stop_level": None,
            "risk_per_share": None,
            "position_risk": 0,
            "weight": 0,
        }

    daily_kwargs = trend_ribbon_signal_kwargs(ticker, timeframe="daily")
    _, _, _, _, daily_dir = compute_trend_ribbon(df, **daily_kwargs)

    df_w = _resample_weekly(df)
    weekly_kwargs = trend_ribbon_signal_kwargs(ticker, timeframe="weekly")
    _, _, _, _, weekly_dir = compute_trend_ribbon(df_w, **weekly_kwargs)

    daily_carried = _carry_neutral(daily_dir)
    weekly_aligned = _align_weekly(weekly_dir, df.index)

    regime_kwargs = trend_ribbon_regime_kwargs(ticker)
    confirmed = build_weekly_confirmed_ribbon_direction(
        daily_carried,
        weekly_aligned,
        reentry_cooldown_bars=regime_kwargs["reentry_cooldown_bars"],
        reentry_cooldown_ratio=regime_kwargs["reentry_cooldown_ratio"],
        weekly_nonbull_confirm_bars=regime_kwargs["weekly_nonbull_confirm_bars"],
        max_dd_exit_gate=regime_kwargs.get("max_dd_exit_gate"),
        price_series=df["Close"],
    )

    current_dir = int(confirmed.iloc[-1]) if len(confirmed) > 0 else 0
    direction = "LONG" if current_dir == 1 else "FLAT"

    last_flip_date = None
    if len(confirmed) > 1:
        for i in range(len(confirmed) - 1, 0, -1):
            if confirmed.iloc[i] != confirmed.iloc[i - 1]:
                last_flip_date = str(confirmed.index[i].date())
                break

    price = round(float(df["Close"].iloc[-1]), 2)
    atr = _compute_atr(df)
    atr_rounded = round(atr, 2) if atr else None

    capital = float(settings.get("portfolio_capital", 100_000))
    sizing_model = settings.get("sizing_model", "vol")
    stop_type = settings.get("stop_type", "atr")
    stop_atr_multiple = float(settings.get("stop_atr_multiple", 3.0))
    stop_pct = float(settings.get("stop_pct", 0.05))

    stop_level, stop_dist = _compute_stop_level(df, stop_type, stop_atr_multiple, stop_pct)

    shares = 0.0
    if direction == "LONG":
        if sizing_model == "vol":
            shares = _compute_vol_position_size(
                df, capital,
                vol_scale_factor=float(settings.get("vol_scale_factor", 0.001)),
            )
        elif sizing_model == "fixed_fraction":
            shares = _compute_fixed_fraction_position_size(
                df, capital,
                risk_fraction=float(settings.get("risk_fraction", 0.01)),
                stop_dist=stop_dist,
            )
        shares = max(0, math.floor(shares))

    notional = round(shares * price, 2)
    risk_per_share = round(stop_dist, 2) if stop_dist else None
    position_risk = round(shares * stop_dist, 2) if stop_dist and shares > 0 else 0
    weight = round(notional / capital, 4) if capital > 0 else 0

    return {
        "ticker": ticker,
        "direction": direction,
        "last_flip_date": last_flip_date,
        "price": price,
        "atr": atr_rounded,
        "shares": shares,
        "notional": notional,
        "stop_level": stop_level if direction == "LONG" else None,
        "risk_per_share": risk_per_share,
        "position_risk": position_risk,
        "weight": weight,
    }


def compute_portfolio_signals(tickers: list[str], settings: dict) -> dict:
    """Compute signals for all tickers and aggregate portfolio heat."""
    capital = float(settings.get("portfolio_capital", 100_000))
    heat_limit = float(settings.get("heat_limit", 0.20))

    signals = []
    for ticker in tickers:
        sig = compute_ticker_signal(ticker, settings)
        signals.append(sig)

    total_risk = sum(s["position_risk"] for s in signals)
    total_notional = sum(s["notional"] for s in signals)
    positions_count = sum(1 for s in signals if s["direction"] == "LONG")
    total_heat = round(total_risk / capital, 4) if capital > 0 else 0

    return {
        "signals": signals,
        "portfolio": {
            "capital": capital,
            "total_notional": round(total_notional, 2),
            "cash_remaining": round(capital - total_notional, 2),
            "positions_count": positions_count,
            "total_risk": round(total_risk, 2),
            "total_heat": total_heat,
            "heat_limit": heat_limit,
            "heat_exceeded": total_heat > heat_limit,
        },
        "settings": settings,
    }
