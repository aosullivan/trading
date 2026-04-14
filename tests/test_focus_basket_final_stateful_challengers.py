"""Deterministic v1.14 final stateful challenger comparison harness."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from lib.backtesting import backtest_direction, build_weekly_confirmed_ribbon_direction
from lib.ribbon_signals import _align_weekly_to_daily, _carry_neutral, _resample_to_weekly
from lib.technical_indicators import (
    _compute_wilder_atr,
    compute_cci_hysteresis,
    compute_trend_ribbon,
)
from lib.trend_ribbon_profile import trend_ribbon_regime_kwargs, trend_ribbon_signal_kwargs
from tests.test_focus_basket_benchmark_backtests import (
    _evaluate_approved_policy,
    _score_from_metrics,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SPEC_PATH = _FIXTURES / "focus_basket_final_stateful_challengers.json"
_CANONICAL_SPEC_PATH = _FIXTURES / "focus_basket_benchmarks.json"


@pytest.fixture
def final_stateful_challenger_spec():
    return json.loads(_SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def focus_chart_spec():
    return json.loads(_CANONICAL_SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def focus_ohlcv_full(focus_chart_spec):
    fixtures = {}
    for ticker, meta in focus_chart_spec["per_ticker"].items():
        df = pd.read_csv(Path(meta["fixture_csv"]), index_col=0, parse_dates=True)
        fixtures[ticker] = df[~df.index.duplicated(keep="last")].sort_index()
    return fixtures


def _buy_hold_pct(df: pd.DataFrame, chart_request: dict) -> float:
    start = pd.Timestamp(chart_request["start"])
    end = pd.Timestamp(chart_request["end"])
    visible = df.loc[(df.index >= start) & (df.index <= end)]
    first_open = float(visible["Open"].iloc[0])
    last_close = float(visible["Close"].iloc[-1])
    return round((last_close / first_open - 1) * 100, 2)


def _rolling_reclaim_level(
    df: pd.DataFrame,
    basis: str,
    lookback: int,
    reclaim_pct: float,
) -> pd.Series:
    source = df["High"] if basis == "high" else df["Close"]
    return source.rolling(lookback).max().shift(1) * (1 + reclaim_pct)


def _compute_cci_reclaim_direction(candidate: dict, df: pd.DataFrame) -> pd.Series:
    _, base_direction = compute_cci_hysteresis(
        df,
        period=30,
        entry_threshold=150,
        exit_threshold=-40,
    )
    reclaim_level = _rolling_reclaim_level(
        df,
        candidate["reclaim_basis"],
        candidate["reclaim_lookback"],
        candidate["reclaim_pct"],
    )
    state = 0
    has_exited = False
    output = []
    for i, raw_value in enumerate(base_direction.fillna(0).astype(int)):
        close = float(df["Close"].iloc[i])
        level = reclaim_level.iloc[i]
        if state == 1 and raw_value == -1:
            state = -1
            has_exited = True
        elif state != 1 and raw_value == 1:
            if (not has_exited) or (pd.notna(level) and close >= float(level)):
                state = 1
        output.append(state)
    return pd.Series(output, index=df.index, dtype=int)


def _compute_cci_cooldown_direction(candidate: dict, df: pd.DataFrame) -> pd.Series:
    _, base_direction = compute_cci_hysteresis(
        df,
        period=30,
        entry_threshold=150,
        exit_threshold=-40,
    )
    state = 0
    cooldown_remaining = 0
    output = []
    for raw_value in base_direction.fillna(0).astype(int):
        if state == 1 and raw_value == -1:
            state = -1
            cooldown_remaining = int(candidate["cooldown_bars"])
        elif state != 1 and raw_value == 1 and cooldown_remaining <= 0:
            state = 1
        elif cooldown_remaining > 0:
            cooldown_remaining -= 1
        output.append(state)
    return pd.Series(output, index=df.index, dtype=int)


def _compute_cci_atr_trail_direction(candidate: dict, df: pd.DataFrame) -> pd.Series:
    cci_values, _ = compute_cci_hysteresis(
        df,
        period=30,
        entry_threshold=150,
        exit_threshold=-40,
    )
    atr = _compute_wilder_atr(
        df["High"],
        df["Low"],
        df["Close"],
        candidate["atr_period"],
    )
    state = 0
    trailing_stop = None
    output = []
    for i in range(len(df)):
        close = float(df["Close"].iloc[i])
        cci_value = cci_values.iloc[i]
        atr_value = atr.iloc[i]

        if state != 1:
            if pd.notna(cci_value) and float(cci_value) > 150:
                state = 1
                trailing_stop = close - (
                    float(atr_value) * candidate["atr_multiplier"]
                    if pd.notna(atr_value)
                    else 0.0
                )
        else:
            if pd.notna(atr_value):
                candidate_stop = close - float(atr_value) * candidate["atr_multiplier"]
                trailing_stop = (
                    candidate_stop if trailing_stop is None else max(trailing_stop, candidate_stop)
                )
            if trailing_stop is not None and close < trailing_stop:
                state = -1
                trailing_stop = None

        output.append(state)
    return pd.Series(output, index=df.index, dtype=int)


def _confirmed_ribbon_direction(df: pd.DataFrame) -> pd.Series:
    daily_kwargs = trend_ribbon_signal_kwargs(None, timeframe="daily")
    _center, _upper, _lower, _strength, daily_direction = compute_trend_ribbon(
        df,
        **daily_kwargs,
    )
    weekly_frame = _resample_to_weekly(df)
    weekly_kwargs = trend_ribbon_signal_kwargs(None, timeframe="weekly")
    _wc, _wu, _wl, _ws, weekly_direction = compute_trend_ribbon(
        weekly_frame,
        **weekly_kwargs,
    )
    regime_kwargs = trend_ribbon_regime_kwargs(None)
    return build_weekly_confirmed_ribbon_direction(
        _carry_neutral(daily_direction),
        _align_weekly_to_daily(weekly_direction, df.index),
        reentry_cooldown_bars=regime_kwargs["reentry_cooldown_bars"],
        reentry_cooldown_ratio=regime_kwargs["reentry_cooldown_ratio"],
        weekly_nonbull_confirm_bars=regime_kwargs["weekly_nonbull_confirm_bars"],
        asymmetric_exit=regime_kwargs.get("asymmetric_exit", False),
    )


def _compute_stateful_ribbon_reclaim_direction(candidate: dict, df: pd.DataFrame) -> pd.Series:
    base_direction = _confirmed_ribbon_direction(df)
    reclaim_level = _rolling_reclaim_level(
        df,
        candidate["reclaim_basis"],
        candidate["reclaim_lookback"],
        candidate["reclaim_pct"],
    )
    state = 0
    has_exited = False
    output = []
    for i, raw_value in enumerate(base_direction.fillna(0).astype(int)):
        close = float(df["Close"].iloc[i])
        level = reclaim_level.iloc[i]
        if state == 1 and raw_value != 1:
            state = -1
            has_exited = True
        elif state != 1 and raw_value == 1:
            if (not has_exited) or (pd.notna(level) and close >= float(level)):
                state = 1
        output.append(state)
    return pd.Series(output, index=df.index, dtype=int)


def _direction_for_candidate(candidate: dict, df: pd.DataFrame) -> pd.Series:
    mechanic = candidate["mechanic"]
    if mechanic == "cci_reclaim":
        return _compute_cci_reclaim_direction(candidate, df)
    if mechanic == "cci_hysteresis_cooldown":
        return _compute_cci_cooldown_direction(candidate, df)
    if mechanic == "cci_hysteresis_atr_trail":
        return _compute_cci_atr_trail_direction(candidate, df)
    if mechanic == "stateful_ribbon_reclaim":
        return _compute_stateful_ribbon_reclaim_direction(candidate, df)
    raise AssertionError(f"Unknown mechanic: {mechanic}")


def _evaluate_candidate(
    candidate: dict,
    focus_chart_spec: dict,
    focus_ohlcv_full: dict,
):
    results = []
    start = pd.Timestamp(focus_chart_spec["chart_request"]["start"])
    end = pd.Timestamp(focus_chart_spec["chart_request"]["end"])

    for ticker in focus_chart_spec["tickers"]:
        df = focus_ohlcv_full[ticker]
        visible = df.loc[(df.index >= start) & (df.index <= end)]
        direction = _direction_for_candidate(candidate, df).reindex(df.index).ffill().fillna(0).astype(int)
        prior_slice = direction.loc[df.index < visible.index[0]]
        prior_direction = int(prior_slice.iloc[-1]) if len(prior_slice) else None
        _, summary, _ = backtest_direction(
            visible,
            direction.loc[visible.index],
            start_in_position=(prior_direction == 1),
            prior_direction=prior_direction,
        )
        buy_hold = _buy_hold_pct(df, focus_chart_spec["chart_request"])
        results.append(
            {
                "ticker": ticker,
                "summary": summary,
                "buy_hold_net_profit_pct": buy_hold,
                "score": _score_from_metrics(
                    summary["net_profit_pct"],
                    summary["max_drawdown_pct"],
                    buy_hold,
                ),
            }
        )
    return _evaluate_approved_policy(results, focus_chart_spec)


@pytest.mark.parametrize("candidate_index", [0, 1, 2, 3])
def test_final_stateful_challengers_match_frozen_outcomes(
    focus_chart_spec,
    focus_ohlcv_full,
    final_stateful_challenger_spec,
    candidate_index,
):
    candidate = final_stateful_challenger_spec["candidates"][candidate_index]
    outcome = _evaluate_candidate(
        candidate,
        focus_chart_spec,
        focus_ohlcv_full,
    )

    assert outcome["aggregate_score"] == candidate["aggregate_score"]
    assert outcome["improved_tickers"] == candidate["improved_tickers"]
    assert outcome["buy_hold_gap_violations"] == candidate["buy_hold_gap_violations"]
    assert [item["ticker"] for item in outcome["moderate_drawdown_violations"]] == candidate[
        "moderate_drawdown_violations"
    ]
    assert [item["ticker"] for item in outcome["severe_drawdown_violations"]] == candidate[
        "severe_drawdown_violations"
    ]
    assert outcome["passed"] is candidate["passed"]


def test_cooldown_is_the_best_contract_shaped_final_probe(
    focus_chart_spec,
    focus_ohlcv_full,
    final_stateful_challenger_spec,
):
    by_key = {}
    for candidate in final_stateful_challenger_spec["candidates"]:
        by_key[candidate["candidate_key"]] = _evaluate_candidate(
            candidate,
            focus_chart_spec,
            focus_ohlcv_full,
        )

    assert final_stateful_challenger_spec["recommended_lead"] == "cci_hysteresis_cooldown_v1"
    assert final_stateful_challenger_spec["final_decision"] == "retain_cci_hysteresis"
    assert by_key["cci_hysteresis_cooldown_v1"]["passed"] is False
    assert by_key["cci_hysteresis_cooldown_v1"]["improved_tickers"] == 5
    assert by_key["cci_hysteresis_cooldown_v1"]["buy_hold_gap_violations"] == ["TSLA"]
    assert by_key["cci_hysteresis_cooldown_v1"]["moderate_drawdown_violations"] == []
    assert by_key["cci_hysteresis_cooldown_v1"]["severe_drawdown_violations"] == []
    assert by_key["cci_hysteresis_atr_trail_v1"]["aggregate_score"] > by_key["cci_hysteresis_cooldown_v1"][
        "aggregate_score"
    ]
    assert by_key["cci_hysteresis_atr_trail_v1"]["improved_tickers"] < by_key["cci_hysteresis_cooldown_v1"][
        "improved_tickers"
    ]
    assert len(by_key["cci_hysteresis_atr_trail_v1"]["buy_hold_gap_violations"]) > len(
        by_key["cci_hysteresis_cooldown_v1"]["buy_hold_gap_violations"]
    )
    assert by_key["cci_reclaim_v1"]["aggregate_score"] < by_key["cci_hysteresis_cooldown_v1"]["aggregate_score"]
    assert by_key["stateful_ribbon_reclaim_v1"]["aggregate_score"] < 0
