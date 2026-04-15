"""Deterministic synthetic stress scenario helpers for portfolio research."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SyntheticStressScenario:
    """Reviewable synthetic market-factor scenario."""

    id: str
    label: str
    shock_start_offset_bars: int = 63
    shock_bars: int = 84
    trough_factor: float = 0.60
    hold_bars: int = 42
    recovery_bars: int = 126
    recovery_factor: float = 0.85
    volatility_boost: float = 0.20
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_SYNTHETIC_STRESS_SCENARIOS = [
    SyntheticStressScenario(
        id="global_macro_crash_40",
        label="Global Macro Crash 40",
        shock_start_offset_bars=63,
        shock_bars=84,
        trough_factor=0.60,
        hold_bars=42,
        recovery_bars=126,
        recovery_factor=0.85,
        volatility_boost=0.25,
        notes="Modeled deep drawdown with a partial recovery.",
    ),
    SyntheticStressScenario(
        id="grind_down_40",
        label="Grind Down 40",
        shock_start_offset_bars=42,
        shock_bars=168,
        trough_factor=0.60,
        hold_bars=42,
        recovery_bars=84,
        recovery_factor=0.75,
        volatility_boost=0.15,
        notes="Slow and sustained downside meant to punish late detectors.",
    ),
    SyntheticStressScenario(
        id="crash_40_full_recovery",
        label="Crash 40 Full Recovery",
        shock_start_offset_bars=63,
        shock_bars=63,
        trough_factor=0.60,
        hold_bars=21,
        recovery_bars=210,
        recovery_factor=1.05,
        volatility_boost=0.20,
        notes="Fast drawdown followed by a full recovery to slightly above the starting level.",
    ),
]


def synthetic_stress_scenario_catalog(
    scenario_ids: Iterable[str] | None = None,
) -> list[dict]:
    scenarios = {item.id: item for item in DEFAULT_SYNTHETIC_STRESS_SCENARIOS}
    if scenario_ids in (None, "", []):
        order = [item.id for item in DEFAULT_SYNTHETIC_STRESS_SCENARIOS]
    else:
        values = scenario_ids
        if isinstance(values, str):
            values = [part.strip() for part in values.split(",")]
        order = [str(item).strip() for item in values if str(item).strip()]
        unknown = [item for item in order if item not in scenarios]
        if unknown:
            supported = ", ".join(sorted(scenarios))
            raise ValueError(f"Unsupported synthetic scenarios: {', '.join(unknown)}. Supported: {supported}")
    return [scenarios[item].to_dict() for item in order]


def _piecewise_linear_segment(start: float, end: float, length: int) -> np.ndarray:
    if length <= 0:
        return np.array([], dtype=float)
    if length == 1:
        return np.array([float(end)], dtype=float)
    return np.linspace(float(start), float(end), num=length + 1, dtype=float)[1:]


def build_synthetic_stress_factor(
    index: Iterable,
    scenario: SyntheticStressScenario,
) -> pd.Series:
    """Build a deterministic market-factor shock curve over the supplied index."""

    aligned_index = pd.DatetimeIndex(index).sort_values().unique()
    if aligned_index.empty:
        return pd.Series(dtype=float)

    factor = pd.Series(1.0, index=aligned_index, dtype=float)
    n = len(aligned_index)
    cursor = min(max(int(scenario.shock_start_offset_bars), 0), n - 1)
    current = 1.0

    for end_value, bars in (
        (scenario.trough_factor, int(scenario.shock_bars)),
        (scenario.trough_factor, int(scenario.hold_bars)),
        (scenario.recovery_factor, int(scenario.recovery_bars)),
    ):
        if cursor >= n:
            break
        length = min(max(int(bars), 0), n - cursor)
        if length <= 0:
            current = float(end_value)
            continue
        segment = _piecewise_linear_segment(current, end_value, length)
        factor.iloc[cursor : cursor + length] = segment
        cursor += length
        current = float(segment[-1])

    if cursor < n:
        factor.iloc[cursor:] = current
    return factor.round(6)


def scenario_start_timestamp(factor: pd.Series) -> Optional[pd.Timestamp]:
    if factor is None or factor.empty:
        return None
    stressed = factor[factor < 0.999999]
    if stressed.empty:
        return None
    return pd.Timestamp(stressed.index[0])


def scenario_trough_drawdown_pct(factor: pd.Series) -> float:
    if factor is None or factor.empty:
        return 0.0
    trough = float(factor.min())
    return round((1.0 - trough) * 100.0, 2)


def apply_synthetic_stress_to_frame(
    df: pd.DataFrame,
    factor: pd.Series,
    *,
    volatility_boost: float = 0.0,
) -> pd.DataFrame:
    """Apply a deterministic market-factor curve to an OHLC frame."""

    if df is None or df.empty:
        return pd.DataFrame(columns=list(df.columns) if df is not None else None)

    aligned_factor = factor.reindex(df.index).ffill().fillna(1.0).astype(float)
    stressed = df.copy()
    price_cols = [col for col in ("Open", "High", "Low", "Close") if col in stressed.columns]
    for column in price_cols:
        stressed[column] = (stressed[column].astype(float) * aligned_factor).round(6)

    if volatility_boost > 0 and {"Open", "High", "Low", "Close"}.issubset(stressed.columns):
        drawdown_intensity = (1.0 - aligned_factor.divide(aligned_factor.cummax())).clip(lower=0.0)
        expansion = 1.0 + drawdown_intensity * float(volatility_boost)
        stressed["High"] = (
            stressed[["Open", "Close", "High"]].max(axis=1) * expansion
        ).round(6)
        stressed["Low"] = (
            stressed[["Open", "Close", "Low"]].min(axis=1) / expansion
        ).round(6)

    if "Volume" in stressed.columns:
        stressed["Volume"] = stressed["Volume"].astype(float)
    return stressed


def apply_synthetic_stress(
    ticker_data: dict[str, pd.DataFrame],
    scenario: SyntheticStressScenario,
) -> tuple[dict[str, pd.DataFrame], pd.Series]:
    """Apply a synthetic stress factor to a multi-ticker OHLC panel."""

    all_indices = [df.index for df in ticker_data.values() if df is not None and not df.empty]
    if not all_indices:
        return {}, pd.Series(dtype=float)

    union_index = all_indices[0]
    for idx in all_indices[1:]:
        union_index = union_index.union(idx)
    union_index = union_index.sort_values()
    factor = build_synthetic_stress_factor(union_index, scenario)
    stressed = {
        ticker: apply_synthetic_stress_to_frame(
            df,
            factor,
            volatility_boost=scenario.volatility_boost,
        )
        for ticker, df in ticker_data.items()
    }
    return stressed, factor


def curve_max_drawdown_pct(curve: list[dict]) -> float:
    peak = None
    max_drawdown = 0.0
    for point in curve or []:
        value = float(point["value"])
        if peak is None or value > peak:
            peak = value
        if not peak:
            continue
        drawdown = ((peak - value) / peak) * 100.0
        max_drawdown = max(max_drawdown, drawdown)
    return round(max_drawdown, 2)


def compute_detection_lag_bars(
    regime_frame: pd.DataFrame | None,
    factor: pd.Series | None,
    *,
    target_band: str = "risk_off",
) -> Optional[int]:
    if regime_frame is None or regime_frame.empty or factor is None or factor.empty:
        return None
    start_ts = scenario_start_timestamp(factor)
    if start_ts is None:
        return None
    aligned = regime_frame.reindex(regime_frame.index.union(factor.index)).sort_index().ffill()
    if start_ts not in aligned.index:
        start_ts = aligned.index[aligned.index.get_indexer([start_ts], method="bfill")[0]]
    start_pos = aligned.index.get_loc(start_ts)
    target = aligned.iloc[start_pos:][aligned.iloc[start_pos:]["regime_band"] == target_band]
    if target.empty:
        return None
    return int(aligned.index.get_loc(target.index[0]) - start_pos)


def compute_drawdown_capture_metrics(
    *,
    strategy_max_drawdown_pct: float,
    buy_hold_max_drawdown_pct: float,
    factor: pd.Series | None = None,
    regime_frame: pd.DataFrame | None = None,
) -> dict:
    downside_capture_pct = None
    if buy_hold_max_drawdown_pct > 0:
        downside_capture_pct = round((strategy_max_drawdown_pct / buy_hold_max_drawdown_pct) * 100.0, 2)
    target_drawdown_pct = scenario_trough_drawdown_pct(factor) if factor is not None else None
    drawdown_saved_pct = round(buy_hold_max_drawdown_pct - strategy_max_drawdown_pct, 2)
    protected_share_of_modeled_drawdown_pct = None
    if target_drawdown_pct and target_drawdown_pct > 0:
        protected_share_of_modeled_drawdown_pct = round((drawdown_saved_pct / target_drawdown_pct) * 100.0, 2)
    return {
        "downside_capture_pct": downside_capture_pct,
        "drawdown_saved_pct": drawdown_saved_pct,
        "modeled_drawdown_pct": target_drawdown_pct,
        "protected_share_of_modeled_drawdown_pct": protected_share_of_modeled_drawdown_pct,
        "protection_lag_bars": compute_detection_lag_bars(regime_frame, factor),
    }


def upside_capture_pct(strategy_return_pct: float, buy_hold_return_pct: float) -> Optional[float]:
    if buy_hold_return_pct <= 0:
        return None
    return round((float(strategy_return_pct) / float(buy_hold_return_pct)) * 100.0, 2)
