"""MU ATR Outer-Threshold Mean-Reversion strategy.

Z-score-style oscillator on price distance from a moving mean, normalized
by ATR. Long-only. Enters on the first up-tick after the oscillator dips
below the lower outer threshold; exits on the first down-tick after it
rises above the upper outer threshold.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from lib.technical_indicators import _compute_wilder_atr


MU_ATR_MR_KEY = "mu_atr_mr"
MU_ATR_MR_LABEL = "MU ATR Outer Threshold MR"

MU_ATR_MR_LOOKBACK = 40
MU_ATR_MR_LOWER_THRESHOLD = -0.4
MU_ATR_MR_UPPER_THRESHOLD = 0.4
MU_ATR_MR_INNER_EXIT = None  # e.g. 0.0 or 0.15 to take profit at inner band
MU_ATR_MR_REGIME_MA = None  # e.g. 200 to require Close > SMA(N) for entries


def _empty_float(index: pd.Index) -> pd.Series:
    return pd.Series(index=index, dtype=float)


def _empty_int(index: pd.Index) -> pd.Series:
    return pd.Series(index=index, dtype=int)


def compute_mu_atr_zscore(
    df: pd.DataFrame,
    lookback: int = MU_ATR_MR_LOOKBACK,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (sma, atr, zscore) where zscore = (Close - SMA) / ATR."""
    close = df["Close"]
    sma = close.rolling(lookback).mean()
    atr = _compute_wilder_atr(df["High"], df["Low"], close, lookback)
    zscore = (close - sma) / atr.replace(0, np.nan)
    return sma, atr, zscore


def compute_mu_atr_mr_strategy(
    df: pd.DataFrame,
    lookback: int = MU_ATR_MR_LOOKBACK,
    lower_threshold: float = MU_ATR_MR_LOWER_THRESHOLD,
    upper_threshold: float = MU_ATR_MR_UPPER_THRESHOLD,
    inner_exit: float | None = MU_ATR_MR_INNER_EXIT,
    regime_ma: int | None = MU_ATR_MR_REGIME_MA,
) -> dict[str, pd.Series]:
    if df is None or df.empty:
        empty_index = pd.Index([])
        return {
            "sma": _empty_float(empty_index),
            "atr": _empty_float(empty_index),
            "zscore": _empty_float(empty_index),
            "daily_direction": _empty_int(empty_index),
        }

    sma, atr, zscore = compute_mu_atr_zscore(df, lookback)

    regime_ok: pd.Series | None = None
    if regime_ma is not None and regime_ma > 0:
        regime_sma = df["Close"].rolling(regime_ma).mean()
        regime_ok = (df["Close"] > regime_sma).fillna(False)

    direction = _generate_direction(
        zscore,
        lower_threshold,
        upper_threshold,
        df.index,
        inner_exit=inner_exit,
        regime_ok=regime_ok,
    )

    return {
        "sma": sma,
        "atr": atr,
        "zscore": zscore,
        "daily_direction": direction,
    }


def _generate_direction(
    zscore: pd.Series,
    lower: float,
    upper: float,
    index: pd.Index,
    inner_exit: float | None = None,
    regime_ok: pd.Series | None = None,
) -> pd.Series:
    """Long-only direction series.

    State machine:
      - flat, watching: if z dips below `lower`, arm a long entry
      - armed long: when z ticks up from its running trough below `lower`, go long
        (skipped if regime_ok provided and False at entry bar)
      - in position: exit when either
        (a) z >= inner_exit  (take-profit at inner band, if set), or
        (b) z >= upper and then ticks down from running peak (full reversal)
    """
    direction = pd.Series(-1, index=index, dtype=int)
    z = zscore.values
    regime_vals = regime_ok.values if regime_ok is not None else None

    in_position = False
    armed_entry = False
    armed_exit = False
    trough = np.inf
    peak = -np.inf

    for i in range(len(z)):
        zi = z[i]
        if np.isnan(zi):
            direction.iloc[i] = 1 if in_position else -1
            continue

        if not in_position:
            if zi <= lower:
                armed_entry = True
                trough = min(trough, zi)
            if armed_entry and zi > trough:
                regime_pass = True if regime_vals is None else bool(regime_vals[i])
                if regime_pass:
                    in_position = True
                armed_entry = False
                trough = np.inf
                peak = -np.inf
        else:
            if inner_exit is not None and zi >= inner_exit:
                in_position = False
                armed_exit = False
                peak = -np.inf
                trough = np.inf
            else:
                if zi >= upper:
                    armed_exit = True
                    peak = max(peak, zi)
                if armed_exit and zi < peak:
                    in_position = False
                    armed_exit = False
                    peak = -np.inf
                    trough = np.inf

        direction.iloc[i] = 1 if in_position else -1

    return direction
