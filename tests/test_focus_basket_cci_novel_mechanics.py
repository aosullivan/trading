"""Deterministic v1.13 novel CCI mechanics comparison harness."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from lib.backtesting import backtest_direction
from lib.technical_indicators import compute_cci_hysteresis, compute_cci_trend
from tests.test_focus_basket_benchmark_backtests import (
    _evaluate_approved_policy,
    _score_from_metrics,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SPEC_PATH = _FIXTURES / "focus_basket_cci_novel_mechanics.json"
_CANONICAL_SPEC_PATH = _FIXTURES / "focus_basket_benchmarks.json"


@pytest.fixture
def cci_mechanics_spec():
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


def _direction_for_candidate(df: pd.DataFrame, candidate: dict) -> pd.Series:
    if candidate["mechanic"] == "raw_cci_trend":
        return compute_cci_trend(df)[1]
    if candidate["mechanic"] == "cci_hysteresis":
        return compute_cci_hysteresis(
            df,
            period=candidate["period"],
            entry_threshold=candidate["entry_threshold"],
            exit_threshold=candidate["exit_threshold"],
        )[1]
    raise AssertionError(f"Unknown mechanic: {candidate['mechanic']}")


def _evaluate_candidate(
    candidate: dict,
    focus_chart_spec: dict,
    focus_ohlcv_full: dict,
    cci_mechanics_spec: dict,
):
    results = []
    start = pd.Timestamp(focus_chart_spec["chart_request"]["start"])
    end = pd.Timestamp(focus_chart_spec["chart_request"]["end"])

    for ticker in focus_chart_spec["tickers"]:
        df = focus_ohlcv_full[ticker]
        visible = df.loc[(df.index >= start) & (df.index <= end)]
        direction = _direction_for_candidate(df, candidate).reindex(df.index).ffill().fillna(0).astype(int)
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

    comparison_spec = {
        **focus_chart_spec,
        **cci_mechanics_spec["comparison_baseline"],
    }
    return _evaluate_approved_policy(results, comparison_spec)


@pytest.mark.parametrize("candidate_index", [0, 1, 2, 3, 4])
def test_cci_novel_mechanics_candidates_match_frozen_outcomes(
    focus_chart_spec,
    focus_ohlcv_full,
    cci_mechanics_spec,
    candidate_index,
):
    candidate = cci_mechanics_spec["candidates"][candidate_index]
    outcome = _evaluate_candidate(candidate, focus_chart_spec, focus_ohlcv_full, cci_mechanics_spec)

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


def test_cci_hysteresis_150_40_is_the_best_novel_cci_lead(
    focus_chart_spec,
    focus_ohlcv_full,
    cci_mechanics_spec,
):
    by_key = {}
    for candidate in cci_mechanics_spec["candidates"]:
        by_key[candidate["candidate_key"]] = _evaluate_candidate(
            candidate,
            focus_chart_spec,
            focus_ohlcv_full,
            cci_mechanics_spec,
        )

    assert cci_mechanics_spec["recommended_lead"] == "cci_hysteresis_150_-40_v1"
    assert by_key["cci_hysteresis_150_-40_v1"]["buy_hold_gap_violations"] == []
    assert by_key["cci_hysteresis_150_-40_v1"]["severe_drawdown_violations"] == []
    assert by_key["cci_hysteresis_150_-40_v1"]["improved_tickers"] == 7
    assert len(by_key["cci_hysteresis_150_-40_v1"]["moderate_drawdown_violations"]) == 3
    assert by_key["cci_hysteresis_150_-40_v1"]["passed"] is True
    assert by_key["cci_hysteresis_150_-40_v1"]["aggregate_score"] > by_key["cci_hysteresis_150_-60_v1"][
        "aggregate_score"
    ]
