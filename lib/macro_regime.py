"""Macro-regime feature helpers and empirical research utilities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import pandas as pd

from lib.data_fetching import _fetch_treasury_yield_history


@dataclass(frozen=True)
class MacroRegimeConfig:
    """Explicit, tuneable regime-scale inputs for macro-aware overlay research."""

    treasury_ticker: str = "UST2Y"
    yield_lookback_bars: int = 63
    yield_good_bps: float = -20.0
    yield_bad_bps: float = 25.0
    yield_weight: float = 0.55
    election_weight: float = 0.25
    breadth_weight: float = 0.85
    breadth_good_pct: float = 0.67
    breadth_bad_pct: float = 0.34
    benchmark_weight: float = 0.0
    benchmark_lookback_bars: int = 63
    benchmark_good_pct: float = 8.0
    benchmark_bad_pct: float = -8.0
    risk_on_threshold: float = 0.75
    risk_off_threshold: float = -0.35
    risk_on_core_pct: float = 0.90
    neutral_core_pct: float = 0.60
    risk_off_core_pct: float = 0.30
    positive_election_phases: tuple[str, ...] = ("pre_election", "election")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict | None) -> "MacroRegimeConfig":
        if not payload:
            return cls()
        values = dict(payload)
        if values.get("positive_election_phases") is not None:
            values["positive_election_phases"] = tuple(values["positive_election_phases"])
        return cls(**values)


def election_cycle_phase(value) -> str:
    """Return the U.S. presidential-cycle phase for the supplied date."""

    ts = pd.Timestamp(value)
    election_offset = (ts.year - 2000) % 4
    if election_offset == 0:
        return "election"
    if election_offset == 3:
        return "pre_election"
    return "other"


def build_rate_feature_frame(
    index: Iterable,
    *,
    treasury_ticker: str = "UST2Y",
    treasury_history: pd.DataFrame | None = None,
    lookbacks: Iterable[int] = (21, 63),
) -> pd.DataFrame:
    """Build aligned Treasury-yield feature columns for a target index."""

    aligned_index = pd.DatetimeIndex(index).sort_values().unique()
    treasury_history = treasury_history if treasury_history is not None else _fetch_treasury_yield_history(treasury_ticker)
    close = (
        treasury_history.get("Close", pd.Series(dtype=float))
        .reindex(aligned_index)
        .ffill()
    )
    features = pd.DataFrame(
        {
            f"{treasury_ticker.lower()}_close": close,
        },
        index=aligned_index,
    )
    for lookback in sorted({int(value) for value in lookbacks if int(value) > 0}):
        features[f"{treasury_ticker.lower()}_change_bps_{lookback}"] = (close - close.shift(lookback)) * 100.0
    return features


def build_portfolio_breadth_frame(
    index: Iterable,
    ticker_directions: dict[str, pd.Series],
) -> pd.DataFrame:
    """Build breadth metrics from per-ticker retained strategy directions."""

    aligned_index = pd.DatetimeIndex(index).sort_values().unique()
    if not ticker_directions:
        return pd.DataFrame(
            {
                "covered_names": 0,
                "bullish_names": 0,
                "bullish_pct": 0.0,
            },
            index=aligned_index,
        )

    aligned = {
        ticker: direction.reindex(aligned_index)
        for ticker, direction in ticker_directions.items()
    }
    frame = pd.DataFrame(aligned, index=aligned_index)
    covered = frame.notna().sum(axis=1)
    bullish = frame.eq(1).sum(axis=1)
    bullish_pct = bullish.divide(covered.where(covered > 0, pd.NA)).fillna(0.0)
    return pd.DataFrame(
        {
            "covered_names": covered.astype(int),
            "bullish_names": bullish.astype(int),
            "bullish_pct": bullish_pct.astype(float),
        },
        index=aligned_index,
    )


def build_benchmark_trend_frame(
    index: Iterable,
    ticker_data: dict[str, pd.DataFrame] | None,
    *,
    lookbacks: Iterable[int] = (63,),
) -> pd.DataFrame:
    """Build equal-weight basket trend features for regime scoring."""

    aligned_index = pd.DatetimeIndex(index).sort_values().unique()
    columns = {"benchmark_index": pd.Series(100.0, index=aligned_index, dtype=float)}
    for lookback in sorted({int(value) for value in lookbacks if int(value) > 0}):
        columns[f"benchmark_trend_pct_{lookback}"] = pd.Series(0.0, index=aligned_index, dtype=float)
    if not ticker_data:
        return pd.DataFrame(columns, index=aligned_index)

    close_frame = build_close_frame(ticker_data).reindex(aligned_index).ffill()
    if close_frame.empty:
        return pd.DataFrame(columns, index=aligned_index)

    anchors = close_frame.ffill().bfill().iloc[0].replace(0, pd.NA)
    normalized = close_frame.divide(anchors, axis=1)
    basket_index = normalized.mean(axis=1, skipna=True).fillna(1.0) * 100.0
    frame = pd.DataFrame({"benchmark_index": basket_index.astype(float)}, index=aligned_index)
    for lookback in sorted({int(value) for value in lookbacks if int(value) > 0}):
        frame[f"benchmark_trend_pct_{lookback}"] = (
            (basket_index / basket_index.shift(lookback)) - 1.0
        ).fillna(0.0) * 100.0
    return frame


def classify_rate_environment(
    change_bps: float | None,
    *,
    strong_good_bps: float = -50.0,
    good_bps: float = -10.0,
    bad_bps: float = 10.0,
    strong_bad_bps: float = 50.0,
) -> str:
    """Bucket short-end yield changes into reviewable rate-expectation regimes."""

    if pd.isna(change_bps):
        return "unknown"
    value = float(change_bps)
    if value <= strong_good_bps:
        return "cuts_fast"
    if value <= good_bps:
        return "cuts_priced"
    if value >= strong_bad_bps:
        return "hikes_fast"
    if value >= bad_bps:
        return "hikes_or_no_cuts"
    return "flat"


def _linear_score(value: float | None, *, good_anchor: float, bad_anchor: float) -> float:
    if pd.isna(value):
        return 0.0
    if good_anchor == bad_anchor:
        return 0.0
    score = 1.0 - 2.0 * ((float(value) - good_anchor) / (bad_anchor - good_anchor))
    return max(-1.0, min(1.0, score))


def build_macro_regime_frame(
    index: Iterable,
    ticker_directions: dict[str, pd.Series],
    *,
    ticker_data: dict[str, pd.DataFrame] | None = None,
    treasury_history: pd.DataFrame | None = None,
    config: MacroRegimeConfig | None = None,
) -> pd.DataFrame:
    """Build the first explicit macro-aware regime scale for a date index."""

    config = config or MacroRegimeConfig()
    aligned_index = pd.DatetimeIndex(index).sort_values().unique()
    rate_frame = build_rate_feature_frame(
        aligned_index,
        treasury_ticker=config.treasury_ticker,
        treasury_history=treasury_history,
        lookbacks=(config.yield_lookback_bars,),
    )
    breadth_frame = build_portfolio_breadth_frame(aligned_index, ticker_directions)
    benchmark_frame = build_benchmark_trend_frame(
        aligned_index,
        ticker_data,
        lookbacks=(config.benchmark_lookback_bars,),
    )
    yield_change_col = f"{config.treasury_ticker.lower()}_change_bps_{config.yield_lookback_bars}"
    benchmark_change_col = f"benchmark_trend_pct_{config.benchmark_lookback_bars}"
    frame = pd.concat([rate_frame, breadth_frame, benchmark_frame], axis=1)
    frame["election_cycle_phase"] = [election_cycle_phase(ts) for ts in aligned_index]
    frame["election_score"] = frame["election_cycle_phase"].isin(config.positive_election_phases).astype(float)
    frame["yield_score"] = frame[yield_change_col].apply(
        _linear_score,
        good_anchor=config.yield_good_bps,
        bad_anchor=config.yield_bad_bps,
    )
    frame["breadth_score"] = frame["bullish_pct"].apply(
        _linear_score,
        good_anchor=config.breadth_good_pct,
        bad_anchor=config.breadth_bad_pct,
    )
    frame["benchmark_score"] = frame[benchmark_change_col].apply(
        _linear_score,
        good_anchor=config.benchmark_good_pct,
        bad_anchor=config.benchmark_bad_pct,
    )
    frame["rate_bucket"] = frame[yield_change_col].apply(classify_rate_environment)
    frame["macro_score"] = (
        frame["yield_score"] * config.yield_weight
        + frame["election_score"] * config.election_weight
        + frame["breadth_score"] * config.breadth_weight
        + frame["benchmark_score"] * config.benchmark_weight
    )

    def _band(score: float) -> str:
        if score >= config.risk_on_threshold:
            return "risk_on"
        if score <= config.risk_off_threshold:
            return "risk_off"
        return "neutral"

    frame["regime_band"] = frame["macro_score"].apply(_band)
    frame["passive_core_target_pct"] = frame["regime_band"].map(
        {
            "risk_on": config.risk_on_core_pct,
            "neutral": config.neutral_core_pct,
            "risk_off": config.risk_off_core_pct,
        }
    )
    return frame


def build_close_frame(ticker_data: dict[str, pd.DataFrame], *, price_col: str = "Close") -> pd.DataFrame:
    """Align ticker close histories into a single sorted panel."""

    series = {
        ticker: df[price_col].rename(ticker)
        for ticker, df in ticker_data.items()
        if df is not None and not df.empty and price_col in df.columns
    }
    if not series:
        return pd.DataFrame()
    close_frame = pd.concat(series.values(), axis=1).sort_index()
    close_frame = close_frame[~close_frame.index.duplicated(keep="last")]
    return close_frame


def month_end_observation_dates(index: Iterable) -> list[pd.Timestamp]:
    """Return the last available observation date for each calendar month."""

    aligned_index = pd.DatetimeIndex(index).sort_values().unique()
    if aligned_index.empty:
        return []
    series = pd.Series(aligned_index, index=aligned_index)
    groups = series.groupby([series.index.year, series.index.month], sort=True)
    return [pd.Timestamp(group.iloc[-1]) for _, group in groups]


def compute_forward_equal_weight_path(
    close_frame: pd.DataFrame,
    as_of,
    *,
    forward_days: int = 126,
    min_tickers: int = 3,
) -> pd.Series | None:
    """Build a forward equal-weight basket path from an observation date."""

    if close_frame.empty:
        return None
    as_of_ts = pd.Timestamp(as_of)
    if as_of_ts not in close_frame.index:
        return None
    end_ts = as_of_ts + pd.Timedelta(days=int(forward_days))
    window = close_frame.loc[(close_frame.index >= as_of_ts) & (close_frame.index <= end_ts)]
    if len(window.index) < 2:
        return None
    start_prices = window.iloc[0].dropna()
    if len(start_prices.index) < min_tickers:
        return None
    eligible = list(start_prices.index)
    window = window[eligible].ffill()
    if len(window.index) < 2:
        return None
    normalized = window.divide(start_prices, axis=1)
    path = normalized.mean(axis=1) * 100.0
    return path.round(6)


def compute_path_metrics(path: pd.Series) -> dict[str, float]:
    """Compute simple return and drawdown metrics from a forward portfolio path."""

    if path is None or path.empty:
        return {
            "forward_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "ending_value": 0.0,
        }
    peak = float(path.iloc[0])
    max_drawdown = 0.0
    for value in path:
        value = float(value)
        peak = max(peak, value)
        if peak <= 0:
            continue
        drawdown = ((peak - value) / peak) * 100.0
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    ending_value = float(path.iloc[-1])
    return {
        "forward_return_pct": round(((ending_value / float(path.iloc[0])) - 1.0) * 100.0, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "ending_value": round(ending_value, 2),
    }
