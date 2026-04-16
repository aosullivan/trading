"""Portfolio-level regime strategies built from the full basket context."""

from __future__ import annotations

import pandas as pd

from lib.macro_regime import build_close_frame, month_end_observation_dates


MONTHLY_BREADTH_GUARD_KEY = "monthly_breadth_guard_v1"
MONTHLY_BREADTH_GUARD_LABEL = "Monthly Breadth Guard"
MONTHLY_BREADTH_GUARD_LADDER_KEY = "monthly_breadth_guard_ladder_v1"
MONTHLY_BREADTH_GUARD_LADDER_LABEL = "Monthly Breadth Guard Ladder"
MONTHLY_BREADTH_GUARD_LOOKBACK_MONTHS = 10
MONTHLY_BREADTH_GUARD_CONFIRM_MONTHS = 2
MONTHLY_BREADTH_GUARD_REENTRY_BUFFER_PCT = 0.02
MONTHLY_BREADTH_GUARD_RISK_ON_BREADTH_PCT = 0.60
MONTHLY_BREADTH_GUARD_RISK_OFF_BREADTH_PCT = 0.40
MONTHLY_BREADTH_GUARD_SHORT_STRENGTH_MONTHS = 6
MONTHLY_BREADTH_GUARD_LONG_STRENGTH_MONTHS = 12
MONTHLY_BREADTH_GUARD_MAX_NAMES = 2
MONTHLY_BREADTH_GUARD_LADDER_MAX_NAMES = 4
MONTHLY_BREADTH_GUARD_LADDER_RUNG_1_DRAWDOWN_PCT = 0.25
MONTHLY_BREADTH_GUARD_LADDER_RUNG_2_DRAWDOWN_PCT = 0.35
MONTHLY_BREADTH_GUARD_LADDER_RUNG_3_DRAWDOWN_PCT = 0.45
MONTHLY_BREADTH_GUARD_LADDER_STABILITY_BREADTH_PCT = 0.25
MONTHLY_BREADTH_GUARD_LADDER_RUNG_2_BREADTH_PCT = 0.30
MONTHLY_BREADTH_GUARD_LADDER_RUNG_3_BREADTH_PCT = 0.35


def _monthly_close_frame(ticker_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close_frame = build_close_frame(ticker_data)
    if close_frame.empty:
        return close_frame
    month_end_dates = month_end_observation_dates(close_frame.index)
    if not month_end_dates:
        return pd.DataFrame(columns=close_frame.columns, index=pd.DatetimeIndex([]))
    monthly_close = close_frame.loc[month_end_dates].copy()
    monthly_close.index = pd.DatetimeIndex(monthly_close.index)
    return monthly_close


def _empty_bearish_directions(ticker_data: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
    return {
        ticker: pd.Series(-1, index=df.index, dtype=int)
        for ticker, df in ticker_data.items()
    }


def _equal_weight_basket_index(monthly_close: pd.DataFrame) -> pd.Series:
    anchors: dict[str, float] = {}
    for ticker in monthly_close.columns:
        valid = monthly_close[ticker].dropna()
        anchors[ticker] = float(valid.iloc[0]) if not valid.empty else pd.NA
    anchor_series = pd.Series(anchors, dtype=float).replace(0, pd.NA)
    normalized = monthly_close.divide(anchor_series, axis=1)
    return normalized.mean(axis=1, skipna=True) * 100.0


def _strength_filter_and_score(
    monthly_close: pd.DataFrame,
    *,
    short_lookback: int,
    long_lookback: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    short_strength = monthly_close.pct_change(short_lookback)
    long_strength = monthly_close.pct_change(long_lookback)
    effective_long_strength = long_strength.where(long_strength.notna(), short_strength)
    positive_strength = short_strength.gt(0.0) & effective_long_strength.gt(0.0)
    blended_score = (
        short_strength.fillna(-1.0) * 0.60
        + effective_long_strength.fillna(-1.0) * 0.40
    )
    return positive_strength.fillna(False), blended_score


def _rebound_filter_and_score(
    monthly_close: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    one_month_rebound = monthly_close.pct_change(1)
    three_month_rebound = monthly_close.pct_change(3)
    six_month_rebound = monthly_close.pct_change(6)
    effective_three_month = three_month_rebound.where(three_month_rebound.notna(), one_month_rebound)
    effective_six_month = six_month_rebound.where(six_month_rebound.notna(), effective_three_month)
    short_trend = monthly_close.rolling(window=3, min_periods=3).mean()
    short_trend_margin = (monthly_close / short_trend.replace(0, pd.NA)) - 1.0
    rebound_candidates = one_month_rebound.gt(0.0) & short_trend_margin.ge(0.0)
    rebound_score = (
        one_month_rebound.fillna(-1.0) * 0.55
        + effective_three_month.fillna(-1.0) * 0.30
        + effective_six_month.fillna(-1.0) * 0.15
    )
    return rebound_candidates.fillna(False), rebound_score, short_trend_margin.fillna(0.0)


def _monthly_regime_components(
    monthly_close: pd.DataFrame,
    *,
    lookback_months: int,
    confirm_months: int,
    reentry_buffer_pct: float,
    breadth_risk_on_pct: float,
    breadth_risk_off_pct: float,
) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    individual_trend = monthly_close.rolling(
        window=lookback_months,
        min_periods=lookback_months,
    ).mean()
    individual_above_trend = monthly_close.gt(individual_trend)
    covered_names = monthly_close.notna().sum(axis=1)
    bullish_names = individual_above_trend.fillna(False).sum(axis=1)
    breadth_pct = bullish_names.divide(covered_names.where(covered_names > 0, pd.NA)).fillna(0.0)

    basket_index = _equal_weight_basket_index(monthly_close)
    basket_trend = basket_index.rolling(
        window=lookback_months,
        min_periods=lookback_months,
    ).mean()

    state = -1
    risk_on_streak = 0
    risk_off_streak = 0
    regime_values: list[int] = []
    for ts in monthly_close.index:
        basket_value = basket_index.loc[ts]
        trend_value = basket_trend.loc[ts]
        breadth_value = breadth_pct.loc[ts]
        if pd.isna(basket_value) or pd.isna(trend_value):
            regime_values.append(state)
            continue

        risk_on_candidate = (
            basket_value > (trend_value * (1.0 + reentry_buffer_pct))
            and breadth_value >= breadth_risk_on_pct
        )
        risk_off_candidate = (
            basket_value < trend_value
            and breadth_value <= breadth_risk_off_pct
        )

        if risk_on_candidate:
            risk_on_streak += 1
            risk_off_streak = 0
        elif risk_off_candidate:
            risk_off_streak += 1
            risk_on_streak = 0
        else:
            risk_on_streak = 0
            risk_off_streak = 0

        if state != 1 and risk_on_streak >= confirm_months:
            state = 1
        elif state != -1 and risk_off_streak >= confirm_months:
            state = -1

        regime_values.append(state)

    regime_state = pd.Series(regime_values, index=monthly_close.index, dtype=int)
    return (
        regime_state,
        individual_trend,
        individual_above_trend.fillna(False),
        basket_index,
        breadth_pct,
    )


def _select_ranked_names(
    monthly_close: pd.DataFrame,
    candidates_mask: pd.DataFrame,
    score_frame: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    slot_count: int,
    tie_break_frame: pd.DataFrame | None = None,
) -> list[str]:
    ranked: list[tuple[str, float, float]] = []
    slots = max(0, int(slot_count))
    if slots <= 0:
        return []

    for ticker in monthly_close.columns:
        if not bool(candidates_mask.at[as_of, ticker]):
            continue
        score = score_frame.at[as_of, ticker]
        close_value = monthly_close.at[as_of, ticker]
        if pd.isna(score) or pd.isna(close_value):
            continue
        tie_break = 0.0
        if tie_break_frame is not None:
            tie_break_value = tie_break_frame.at[as_of, ticker]
            tie_break = float(tie_break_value) if not pd.isna(tie_break_value) else 0.0
        ranked.append((ticker, float(score), tie_break))

    ranked.sort(key=lambda item: (-item[1], -item[2], item[0]))
    return [ticker for ticker, _score, _tie_break in ranked[:slots]]


def _drawdown_ladder_slot_counts(
    regime_state: pd.Series,
    basket_index: pd.Series,
    ladder_breadth_pct: pd.Series,
    *,
    max_names: int,
    rung_1_drawdown_pct: float,
    rung_2_drawdown_pct: float,
    rung_3_drawdown_pct: float,
    stability_breadth_pct: float,
    rung_2_breadth_pct: float,
    rung_3_breadth_pct: float,
) -> pd.Series:
    basket_drawdown = 1.0 - basket_index.divide(basket_index.cummax().replace(0, pd.NA))
    basket_monthly_return = basket_index.pct_change(1).fillna(0.0)
    breadth_delta = ladder_breadth_pct.diff(1).fillna(0.0)
    slot_counts = pd.Series(0, index=regime_state.index, dtype=int)

    for ts in slot_counts.index:
        if int(regime_state.loc[ts]) == 1:
            slot_counts.loc[ts] = max_names
            continue

        drawdown_pct = float(basket_drawdown.loc[ts]) if not pd.isna(basket_drawdown.loc[ts]) else 0.0
        breadth_value = float(ladder_breadth_pct.loc[ts]) if not pd.isna(ladder_breadth_pct.loc[ts]) else 0.0
        monthly_return = float(basket_monthly_return.loc[ts]) if not pd.isna(basket_monthly_return.loc[ts]) else 0.0
        breadth_change = float(breadth_delta.loc[ts]) if not pd.isna(breadth_delta.loc[ts]) else 0.0
        stabilizing = (
            monthly_return >= 0.0
            and breadth_change >= 0.0
            and breadth_value >= stability_breadth_pct
        )

        slots = 0
        if stabilizing and drawdown_pct >= rung_1_drawdown_pct:
            slots = 1
        if stabilizing and drawdown_pct >= rung_2_drawdown_pct and breadth_value >= rung_2_breadth_pct:
            slots = 2
        if stabilizing and drawdown_pct >= rung_3_drawdown_pct and breadth_value >= rung_3_breadth_pct:
            slots = 3
        slot_counts.loc[ts] = min(max_names, slots)
    return slot_counts


def compute_monthly_breadth_guard_directions(
    ticker_data: dict[str, pd.DataFrame],
    *,
    lookback_months: int = MONTHLY_BREADTH_GUARD_LOOKBACK_MONTHS,
    confirm_months: int = MONTHLY_BREADTH_GUARD_CONFIRM_MONTHS,
    reentry_buffer_pct: float = MONTHLY_BREADTH_GUARD_REENTRY_BUFFER_PCT,
    breadth_risk_on_pct: float = MONTHLY_BREADTH_GUARD_RISK_ON_BREADTH_PCT,
    breadth_risk_off_pct: float = MONTHLY_BREADTH_GUARD_RISK_OFF_BREADTH_PCT,
    short_strength_months: int = MONTHLY_BREADTH_GUARD_SHORT_STRENGTH_MONTHS,
    long_strength_months: int = MONTHLY_BREADTH_GUARD_LONG_STRENGTH_MONTHS,
    max_names: int = MONTHLY_BREADTH_GUARD_MAX_NAMES,
) -> dict[str, pd.Series]:
    """Return daily-aligned long/cash directions from a slow monthly basket regime.

    The strategy only turns risk-on after the basket itself is back above its
    long trend with a small re-entry buffer and a healthy fraction of names are
    also above trend. When risk-on, it holds only the strongest few names.
    """

    if not ticker_data:
        return {}

    monthly_close = _monthly_close_frame(ticker_data)
    if monthly_close.empty:
        return _empty_bearish_directions(ticker_data)

    regime_state, individual_trend, individual_above_trend, _basket_index, _breadth_pct = _monthly_regime_components(
        monthly_close,
        lookback_months=lookback_months,
        confirm_months=confirm_months,
        reentry_buffer_pct=reentry_buffer_pct,
        breadth_risk_on_pct=breadth_risk_on_pct,
        breadth_risk_off_pct=breadth_risk_off_pct,
    )
    positive_strength, blended_score = _strength_filter_and_score(
        monthly_close,
        short_lookback=short_strength_months,
        long_lookback=long_strength_months,
    )
    trend_margin = ((monthly_close / individual_trend.replace(0, pd.NA)) - 1.0).fillna(0.0)

    monthly_direction = pd.DataFrame(
        -1,
        index=monthly_close.index,
        columns=monthly_close.columns,
        dtype=int,
    )

    for ts in monthly_close.index:
        if int(regime_state.loc[ts]) != 1:
            continue

        selected = _select_ranked_names(
            monthly_close,
            individual_above_trend & positive_strength,
            blended_score,
            as_of=ts,
            slot_count=max_names,
            tie_break_frame=trend_margin,
        )
        for ticker in selected:
            monthly_direction.at[ts, ticker] = 1

    directions: dict[str, pd.Series] = {}
    for ticker, df in ticker_data.items():
        if ticker not in monthly_direction.columns:
            directions[ticker] = pd.Series(-1, index=df.index, dtype=int)
            continue
        directions[ticker] = (
            monthly_direction[ticker]
            .reindex(df.index)
            .ffill()
            .fillna(-1)
            .astype(int)
        )
    return directions


def compute_monthly_breadth_guard_ladder_directions(
    ticker_data: dict[str, pd.DataFrame],
    *,
    lookback_months: int = MONTHLY_BREADTH_GUARD_LOOKBACK_MONTHS,
    confirm_months: int = MONTHLY_BREADTH_GUARD_CONFIRM_MONTHS,
    reentry_buffer_pct: float = MONTHLY_BREADTH_GUARD_REENTRY_BUFFER_PCT,
    breadth_risk_on_pct: float = MONTHLY_BREADTH_GUARD_RISK_ON_BREADTH_PCT,
    breadth_risk_off_pct: float = MONTHLY_BREADTH_GUARD_RISK_OFF_BREADTH_PCT,
    short_strength_months: int = MONTHLY_BREADTH_GUARD_SHORT_STRENGTH_MONTHS,
    long_strength_months: int = MONTHLY_BREADTH_GUARD_LONG_STRENGTH_MONTHS,
    max_names: int = MONTHLY_BREADTH_GUARD_LADDER_MAX_NAMES,
    rung_1_drawdown_pct: float = MONTHLY_BREADTH_GUARD_LADDER_RUNG_1_DRAWDOWN_PCT,
    rung_2_drawdown_pct: float = MONTHLY_BREADTH_GUARD_LADDER_RUNG_2_DRAWDOWN_PCT,
    rung_3_drawdown_pct: float = MONTHLY_BREADTH_GUARD_LADDER_RUNG_3_DRAWDOWN_PCT,
    stability_breadth_pct: float = MONTHLY_BREADTH_GUARD_LADDER_STABILITY_BREADTH_PCT,
    rung_2_breadth_pct: float = MONTHLY_BREADTH_GUARD_LADDER_RUNG_2_BREADTH_PCT,
    rung_3_breadth_pct: float = MONTHLY_BREADTH_GUARD_LADDER_RUNG_3_BREADTH_PCT,
) -> dict[str, pd.Series]:
    """Return daily-aligned directions for a crash-aware monthly ladder strategy.

    The normal monthly breadth guard still controls full risk-on transitions.
    During deep drawdowns, the ladder allows a partial re-entry into the
    strongest rebound names once the basket stops worsening month-over-month.
    """

    if not ticker_data:
        return {}

    monthly_close = _monthly_close_frame(ticker_data)
    if monthly_close.empty:
        return _empty_bearish_directions(ticker_data)

    regime_state, individual_trend, individual_above_trend, basket_index, breadth_pct = _monthly_regime_components(
        monthly_close,
        lookback_months=lookback_months,
        confirm_months=confirm_months,
        reentry_buffer_pct=reentry_buffer_pct,
        breadth_risk_on_pct=breadth_risk_on_pct,
        breadth_risk_off_pct=breadth_risk_off_pct,
    )
    positive_strength, blended_score = _strength_filter_and_score(
        monthly_close,
        short_lookback=short_strength_months,
        long_lookback=long_strength_months,
    )
    rebound_candidates, rebound_score, rebound_margin = _rebound_filter_and_score(monthly_close)
    covered_names = monthly_close.notna().sum(axis=1)
    rebound_breadth_pct = rebound_candidates.sum(axis=1).divide(
        covered_names.where(covered_names > 0, pd.NA)
    ).fillna(0.0)
    trend_margin = ((monthly_close / individual_trend.replace(0, pd.NA)) - 1.0).fillna(0.0)
    slot_counts = _drawdown_ladder_slot_counts(
        regime_state,
        basket_index,
        rebound_breadth_pct,
        max_names=max_names,
        rung_1_drawdown_pct=rung_1_drawdown_pct,
        rung_2_drawdown_pct=rung_2_drawdown_pct,
        rung_3_drawdown_pct=rung_3_drawdown_pct,
        stability_breadth_pct=stability_breadth_pct,
        rung_2_breadth_pct=rung_2_breadth_pct,
        rung_3_breadth_pct=rung_3_breadth_pct,
    )

    monthly_direction = pd.DataFrame(
        -1,
        index=monthly_close.index,
        columns=monthly_close.columns,
        dtype=int,
    )

    for ts in monthly_close.index:
        slot_count = int(slot_counts.loc[ts])
        if slot_count <= 0:
            continue

        if int(regime_state.loc[ts]) == 1:
            selected = _select_ranked_names(
                monthly_close,
                individual_above_trend & positive_strength,
                blended_score,
                as_of=ts,
                slot_count=slot_count,
                tie_break_frame=trend_margin,
            )
        else:
            selected = _select_ranked_names(
                monthly_close,
                rebound_candidates,
                rebound_score,
                as_of=ts,
                slot_count=slot_count,
                tie_break_frame=rebound_margin,
            )

        for ticker in selected:
            monthly_direction.at[ts, ticker] = 1

    directions: dict[str, pd.Series] = {}
    for ticker, df in ticker_data.items():
        if ticker not in monthly_direction.columns:
            directions[ticker] = pd.Series(-1, index=df.index, dtype=int)
            continue
        directions[ticker] = (
            monthly_direction[ticker]
            .reindex(df.index)
            .ffill()
            .fillna(-1)
            .astype(int)
        )
    return directions
