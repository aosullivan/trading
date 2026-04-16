from __future__ import annotations

import numpy as np
import pandas as pd

from lib.macro_regime import MacroRegimeConfig, build_macro_regime_frame
from lib.technical_indicators import (
    _compute_wilder_atr,
    compute_cci_hysteresis,
    compute_corpus_trend_signal,
    compute_trend_ribbon,
)


TREND_SR_MACRO_KEY = "trend_sr_macro_v1"
TREND_SR_MACRO_LABEL = "Trend SR + Macro v1"

_DAILY_STARTER_FRACTION = 0.85
_WEEKLY_CONFIRMED_FRACTION = 0.15
_FRAME_LOOKBACK = 40
_WEEKLY_FRAME_LOOKBACK = 12
_BASE_ENTRY_THRESHOLD = 55.0
_BASE_EXIT_THRESHOLD = 72.0
_BASE_CONFIRM_THRESHOLD = 54.0

TREND_SR_MACRO_CONFIG = MacroRegimeConfig(
    yield_lookback_bars=63,
    yield_good_bps=-20.0,
    yield_bad_bps=20.0,
    yield_weight=0.40,
    election_weight=0.10,
    breadth_weight=0.65,
    breadth_good_pct=0.67,
    breadth_bad_pct=0.33,
    benchmark_weight=0.35,
    benchmark_lookback_bars=63,
    benchmark_good_pct=10.0,
    benchmark_bad_pct=-10.0,
    risk_on_threshold=0.55,
    risk_off_threshold=-0.35,
)


def _resample_ohlcv(df: pd.DataFrame, rule: str = "W-FRI") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    return (
        df.sort_index()
        .resample(rule)
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna(subset=["Open", "High", "Low", "Close"])
    )


def _align_to_daily(series: pd.Series, daily_index: pd.Index) -> pd.Series:
    return series.reindex(daily_index).ffill().fillna(0)


def _closeness_score(distance_atr: pd.Series, max_distance: float = 4.0) -> pd.Series:
    clipped = distance_atr.clip(lower=0.0, upper=max_distance)
    return ((1.0 - (clipped / max_distance)) * 100.0).fillna(0.0)


def _rolling_room_score(
    upside_atr: pd.Series,
    downside_atr: pd.Series,
    *,
    bullish: bool,
) -> pd.Series:
    delta = upside_atr - downside_atr if bullish else downside_atr - upside_atr
    return ((np.tanh(delta.fillna(0.0) / 2.0) + 1.0) * 50.0).clip(0.0, 100.0)


def _nearest_aligned_ma_distance_atr(
    close: pd.Series,
    atr: pd.Series,
    ma_frame: pd.DataFrame,
    *,
    bullish: bool,
) -> pd.Series:
    distances = []
    for column in ma_frame.columns:
        ma = ma_frame[column]
        aligned = ma.le(close) if bullish else ma.ge(close)
        distance = ((close - ma).abs() / atr).where(aligned)
        distances.append(distance)
    if not distances:
        return pd.Series(np.nan, index=close.index, dtype=float)
    return pd.concat(distances, axis=1).min(axis=1, skipna=True)


def _safe_macro_frame(
    index: pd.Index,
    direction_inputs: dict[str, pd.Series],
    ticker_data: dict[str, pd.DataFrame],
    *,
    treasury_history: pd.DataFrame | None = None,
    config: MacroRegimeConfig | None = None,
) -> pd.DataFrame:
    try:
        return build_macro_regime_frame(
            index,
            direction_inputs,
            ticker_data=ticker_data,
            treasury_history=treasury_history,
            config=config or TREND_SR_MACRO_CONFIG,
        )
    except Exception:
        return pd.DataFrame(
            {
                "macro_score": pd.Series(0.0, index=index, dtype=float),
                "regime_band": pd.Series("neutral", index=index, dtype=object),
            },
            index=index,
        )


def _frame_strength_scores(
    df: pd.DataFrame,
    ribbon_direction: pd.Series,
    ribbon_strength: pd.Series,
    *,
    lookback: int,
    macro_frame: pd.DataFrame | None = None,
    weekly_ma_frame: pd.DataFrame | None = None,
) -> tuple[pd.Series, pd.Series]:
    if df is None or df.empty:
        empty = pd.Series(dtype=float, index=df.index if df is not None else None)
        return empty, empty

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    atr = _compute_wilder_atr(high, low, close, 14).replace(0, np.nan)

    support = low.rolling(lookback).min().shift(1)
    resistance = high.rolling(lookback).max().shift(1)
    support_distance_atr = ((close - support).abs() / atr).where(support <= close)
    resistance_distance_atr = ((close - resistance).abs() / atr).where(
        resistance >= close
    )

    ma_frame = pd.DataFrame(
        {
            "sma20": close.rolling(20).mean(),
            "sma50": close.rolling(50).mean(),
            "sma100": close.rolling(100).mean(),
            "sma200": close.rolling(200).mean(),
        },
        index=df.index,
    )
    if weekly_ma_frame is not None and not weekly_ma_frame.empty:
        ma_frame = pd.concat([ma_frame, weekly_ma_frame.reindex(df.index)], axis=1)

    bullish_ma_distance = _nearest_aligned_ma_distance_atr(
        close,
        atr,
        ma_frame,
        bullish=True,
    )
    bearish_ma_distance = _nearest_aligned_ma_distance_atr(
        close,
        atr,
        ma_frame,
        bullish=False,
    )

    upside_atr = (resistance - close).abs() / atr
    downside_atr = (close - support).abs() / atr

    trend_component = ribbon_strength.abs().clip(0.0, 1.0) * 100.0
    bull_level = _closeness_score(support_distance_atr)
    bear_level = _closeness_score(resistance_distance_atr)
    bull_ma = _closeness_score(bullish_ma_distance)
    bear_ma = _closeness_score(bearish_ma_distance)
    bull_room = _rolling_room_score(upside_atr, downside_atr, bullish=True)
    bear_room = _rolling_room_score(upside_atr, downside_atr, bullish=False)

    macro_score = (
        macro_frame.get("macro_score", pd.Series(0.0, index=df.index))
        if macro_frame is not None
        else pd.Series(0.0, index=df.index)
    )
    bull_macro_bonus = macro_score.clip(lower=0.0) * 8.0
    bear_macro_bonus = (-macro_score).clip(lower=0.0) * 10.0
    risk_off_penalty = (-macro_score).clip(lower=0.0) * 4.0
    risk_on_penalty = macro_score.clip(lower=0.0) * 3.0

    bull_alignment = pd.Series(np.where(ribbon_direction == 1, 1.0, 0.0), index=df.index)
    bear_alignment = pd.Series(np.where(ribbon_direction == -1, 1.0, 0.0), index=df.index)

    bull_score = (
        0.65 * trend_component
        + 0.15 * bull_level
        + 0.08 * bull_ma
        + 0.12 * bull_room
        + bull_macro_bonus
        - risk_off_penalty
    ) * bull_alignment
    bear_score = (
        0.60 * trend_component
        + 0.20 * bear_level
        + 0.08 * bear_ma
        + 0.12 * bear_room
        + bear_macro_bonus
        - risk_on_penalty
    ) * bear_alignment
    return bull_score.clip(0.0, 100.0), bear_score.clip(0.0, 100.0)


def _dynamic_thresholds(macro_frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    regime_band = macro_frame.get("regime_band", pd.Series("neutral", index=macro_frame.index))
    entry = pd.Series(_BASE_ENTRY_THRESHOLD, index=macro_frame.index, dtype=float)
    exit_ = pd.Series(_BASE_EXIT_THRESHOLD, index=macro_frame.index, dtype=float)
    confirm = pd.Series(_BASE_CONFIRM_THRESHOLD, index=macro_frame.index, dtype=float)

    entry = entry.where(regime_band != "risk_on", entry - 8.0)
    entry = entry.where(regime_band != "risk_off", entry + 8.0)

    exit_ = exit_.where(regime_band != "risk_on", exit_ + 6.0)
    exit_ = exit_.where(regime_band != "risk_off", exit_ - 8.0)

    confirm = confirm.where(regime_band != "risk_on", confirm - 3.0)
    confirm = confirm.where(regime_band != "risk_off", confirm + 6.0)
    return entry, exit_, confirm


def _stateful_daily_direction(
    ribbon_direction: pd.Series,
    weekly_direction: pd.Series,
    weekly_strength: pd.Series,
    bull_score: pd.Series,
    bear_score: pd.Series,
    entry_threshold: pd.Series,
    exit_threshold: pd.Series,
    close: pd.Series,
    sma50: pd.Series,
    sma100: pd.Series,
    sma200: pd.Series,
    macro_frame: pd.DataFrame,
) -> pd.Series:
    state = -1
    output = []
    for i in range(len(ribbon_direction)):
        ribbon_state = int(ribbon_direction.iloc[i]) if not pd.isna(ribbon_direction.iloc[i]) else 0
        weekly_state = int(weekly_direction.iloc[i]) if not pd.isna(weekly_direction.iloc[i]) else 0
        weekly_strength_value = (
            float(weekly_strength.iloc[i]) if not pd.isna(weekly_strength.iloc[i]) else 0.0
        )
        macro_band = str(macro_frame["regime_band"].iloc[i]) if "regime_band" in macro_frame else "neutral"
        above_sma50 = bool(pd.notna(sma50.iloc[i]) and close.iloc[i] >= sma50.iloc[i])
        above_sma100 = bool(pd.notna(sma100.iloc[i]) and close.iloc[i] >= sma100.iloc[i])
        above_sma200 = bool(pd.notna(sma200.iloc[i]) and close.iloc[i] >= sma200.iloc[i])
        persistent_bull = (
            above_sma50
            and (above_sma100 or above_sma200)
            and weekly_state == 1
            and weekly_strength_value >= (0.15 if macro_band == "risk_on" else 0.25)
            and macro_band != "risk_off"
        )
        structural_break = (
            (pd.notna(sma100.iloc[i]) and close.iloc[i] < sma100.iloc[i])
            or (pd.notna(sma200.iloc[i]) and close.iloc[i] < sma200.iloc[i])
            or weekly_state == -1
            or macro_band == "risk_off"
        )

        if state != 1 and ribbon_state == 1 and bull_score.iloc[i] >= entry_threshold.iloc[i]:
            state = 1
        elif (
            state == 1
            and ribbon_state == -1
            and bear_score.iloc[i] >= exit_threshold.iloc[i]
            and (
                not persistent_bull
                or structural_break
                or bear_score.iloc[i] >= exit_threshold.iloc[i] + 18.0
            )
        ):
            state = -1
        output.append(state)
    return pd.Series(output, index=ribbon_direction.index, dtype=int)


def compute_trend_sr_macro_strategy(
    df: pd.DataFrame,
    *,
    treasury_history: pd.DataFrame | None = None,
    config: MacroRegimeConfig | None = None,
) -> dict[str, pd.Series | pd.DataFrame]:
    if df is None or df.empty:
        empty = pd.Series(dtype=int)
        return {
            "daily_direction": empty,
            "weekly_direction": empty,
            "daily_bull_score": pd.Series(dtype=float),
            "daily_bear_score": pd.Series(dtype=float),
            "weekly_bull_score": pd.Series(dtype=float),
            "macro_frame": pd.DataFrame(),
        }

    daily_center, daily_upper, daily_lower, daily_strength, daily_ribbon = compute_trend_ribbon(df)
    weekly_df = _resample_ohlcv(df)
    (
        weekly_center,
        weekly_upper,
        weekly_lower,
        weekly_strength,
        weekly_ribbon,
    ) = compute_trend_ribbon(weekly_df)
    _corpus_entry, _corpus_exit, _corpus_atr, _corpus_stop, corpus_direction = compute_corpus_trend_signal(df)
    _cci_values, cci_direction = compute_cci_hysteresis(df)

    weekly_ribbon_aligned = _align_to_daily(weekly_ribbon.astype(int), df.index).astype(int)
    weekly_strength_aligned = _align_to_daily(weekly_strength.astype(float), df.index).astype(float)
    weekly_ma_frame = pd.DataFrame(
        {
            "sma50w": _align_to_daily(weekly_df["Close"].rolling(50).mean(), df.index),
            "sma100w": _align_to_daily(weekly_df["Close"].rolling(100).mean(), df.index),
            "sma200w": _align_to_daily(weekly_df["Close"].rolling(200).mean(), df.index),
        },
        index=df.index,
    )

    macro_frame = _safe_macro_frame(
        df.index,
        {
            "daily_ribbon": daily_ribbon.astype(int),
            "weekly_ribbon": weekly_ribbon_aligned.astype(int),
            "corpus_trend": corpus_direction.astype(int),
            "cci_hysteresis": cci_direction.astype(int),
        },
        {"asset": df},
        treasury_history=treasury_history,
        config=config or TREND_SR_MACRO_CONFIG,
    )

    daily_bull_score, daily_bear_score = _frame_strength_scores(
        df,
        daily_ribbon.astype(int),
        daily_strength.astype(float),
        lookback=_FRAME_LOOKBACK,
        macro_frame=macro_frame,
        weekly_ma_frame=weekly_ma_frame,
    )
    daily_bull_score = (
        daily_bull_score
        + np.where(weekly_ribbon_aligned == 1, weekly_strength_aligned.clip(0.0, 1.0) * 12.0, 0.0)
    ).clip(0.0, 100.0)
    daily_bear_score = (
        daily_bear_score
        + np.where(weekly_ribbon_aligned == -1, weekly_strength_aligned.abs().clip(0.0, 1.0) * 10.0, 0.0)
    ).clip(0.0, 100.0)

    weekly_macro_frame = macro_frame.reindex(weekly_df.index).ffill()
    weekly_bull_score, _weekly_bear_score = _frame_strength_scores(
        weekly_df,
        weekly_ribbon.astype(int),
        weekly_strength.astype(float),
        lookback=_WEEKLY_FRAME_LOOKBACK,
        macro_frame=weekly_macro_frame,
    )

    entry_threshold, exit_threshold, confirm_threshold = _dynamic_thresholds(macro_frame)
    sma50 = df["Close"].rolling(50).mean()
    sma100 = df["Close"].rolling(100).mean()
    sma200 = df["Close"].rolling(200).mean()
    daily_direction = _stateful_daily_direction(
        daily_ribbon.astype(int),
        weekly_ribbon_aligned.astype(int),
        weekly_strength_aligned.astype(float),
        daily_bull_score,
        daily_bear_score,
        entry_threshold,
        exit_threshold,
        df["Close"],
        sma50,
        sma100,
        sma200,
        macro_frame,
    )
    weekly_confirm_aligned = _align_to_daily(
        (weekly_bull_score >= confirm_threshold.reindex(weekly_df.index).ffill().fillna(_BASE_CONFIRM_THRESHOLD)).astype(int).replace(0, -1),
        df.index,
    ).astype(int)
    weekly_direction = pd.Series(
        np.where(
            (daily_direction == 1) & (weekly_ribbon_aligned == 1) & (weekly_confirm_aligned == 1),
            1,
            -1,
        ),
        index=df.index,
        dtype=int,
    )

    return {
        "daily_direction": daily_direction,
        "weekly_direction": weekly_direction,
        "daily_bull_score": daily_bull_score.round(2),
        "daily_bear_score": daily_bear_score.round(2),
        "weekly_bull_score": _align_to_daily(weekly_bull_score.round(2), df.index),
        "macro_frame": macro_frame,
        "daily_ribbon_center": daily_center,
        "daily_ribbon_upper": daily_upper,
        "daily_ribbon_lower": daily_lower,
        "daily_ribbon_strength": daily_strength,
        "weekly_ribbon_center": weekly_center,
        "weekly_ribbon_upper": weekly_upper,
        "weekly_ribbon_lower": weekly_lower,
        "weekly_ribbon_strength": weekly_strength,
    }


def trend_sr_macro_backtest_meta(strategy_bundle: dict) -> dict:
    macro_frame = strategy_bundle.get("macro_frame")
    if isinstance(macro_frame, pd.DataFrame) and not macro_frame.empty:
        last_regime = str(macro_frame["regime_band"].iloc[-1])
        last_macro_score = round(float(macro_frame["macro_score"].iloc[-1]), 3)
    else:
        last_regime = "neutral"
        last_macro_score = 0.0
    return {
        "confirmation_supported": False,
        "architecture_label": TREND_SR_MACRO_LABEL,
        "architecture_core_fraction": _DAILY_STARTER_FRACTION,
        "architecture_overlay_fraction": _WEEKLY_CONFIRMED_FRACTION,
        "architecture_hint": (
            "enter an 85% starter sleeve when the daily ribbon flips bullish and the historical "
            "trade-strength proxy is high near support, add the remaining 15% only when the "
            "weekly ribbon also confirms with strong structure, and exit once bearish strength "
            "is elevated near resistance. Macro regime shifts relax long entries in risk-on and "
            "tighten exits in risk-off."
        ),
        "macro_regime_band": last_regime,
        "macro_score": last_macro_score,
    }


def trend_sr_macro_confirmation_config() -> dict:
    return {
        "mode": TREND_SR_MACRO_KEY,
        "starter_fraction": _DAILY_STARTER_FRACTION,
        "confirmed_fraction": _WEEKLY_CONFIRMED_FRACTION,
        "label": TREND_SR_MACRO_LABEL,
        "semantics": "escalation_layered",
    }
