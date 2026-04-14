"""Deterministic v1.5 alternative-architecture comparison harness."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import pytest

from lib.data_fetching import _slice_df
from tests.test_focus_basket_benchmark_backtests import _chart_query, _score_from_metrics
from tests.test_focus_basket_benchmark_backtests import (
    _evaluate_approved_policy,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SPEC_PATH = _FIXTURES / "focus_basket_alternative_architectures.json"
_CANONICAL_SPEC_PATH = _FIXTURES / "focus_basket_benchmarks.json"


@pytest.fixture
def alternative_architecture_spec():
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


@pytest.fixture
def mock_focus_download(focus_ohlcv_full):
    def _mock(ticker, **kwargs):
        if ticker not in focus_ohlcv_full:
            raise AssertionError(f"Unexpected ticker request: {ticker}")
        return _slice_df(focus_ohlcv_full[ticker], kwargs.get("start"), kwargs.get("end"))

    return _mock


def _buy_hold_pct(df: pd.DataFrame, chart_request: dict) -> float:
    start = pd.Timestamp(chart_request["start"])
    end = pd.Timestamp(chart_request["end"])
    visible = df.loc[(df.index >= start) & (df.index <= end)]
    first_open = float(visible["Open"].iloc[0])
    last_close = float(visible["Close"].iloc[-1])
    return round((last_close / first_open - 1) * 100, 2)


def _evaluate_route_supported_strategy_on_fixture_basket(
    client,
    focus_chart_spec: dict,
    focus_ohlcv_full: dict,
    mock_focus_download,
    strategy_key: str,
):
    results = []
    for ticker in focus_chart_spec["tickers"]:
        with patch("routes.chart.cached_download", side_effect=mock_focus_download):
            resp = client.get(_chart_query(focus_chart_spec["chart_request"], ticker))
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        payload = data["strategies"][strategy_key]
        summary = payload["summary"]
        buy_hold_net_profit_pct = _buy_hold_pct(
            focus_ohlcv_full[ticker],
            focus_chart_spec["chart_request"],
        )
        results.append(
            {
                "ticker": ticker,
                "summary": summary,
                "buy_hold_net_profit_pct": buy_hold_net_profit_pct,
                "score": _score_from_metrics(
                    summary["net_profit_pct"],
                    summary["max_drawdown_pct"],
                    buy_hold_net_profit_pct,
                ),
            }
        )
    return results


@pytest.mark.parametrize(
    "candidate_index",
    [0, 1, 2, 3],
)
def test_alternative_architecture_candidates_match_frozen_focus_basket_outcomes(
    app,
    client,
    focus_chart_spec,
    focus_ohlcv_full,
    mock_focus_download,
    alternative_architecture_spec,
    candidate_index,
):
    candidate = alternative_architecture_spec["candidates"][candidate_index]
    outcome = _evaluate_approved_policy(
        _evaluate_route_supported_strategy_on_fixture_basket(
            client,
            focus_chart_spec,
            focus_ohlcv_full,
            mock_focus_download,
            candidate["strategy_key"],
        ),
        focus_chart_spec,
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
    assert outcome["passed"] is False


def test_bb_breakout_is_the_recommended_lead_alternative_family_candidate(
    app,
    client,
    focus_chart_spec,
    focus_ohlcv_full,
    mock_focus_download,
    alternative_architecture_spec,
):
    lead_key = alternative_architecture_spec["recommended_lead"]
    by_key = {}
    for candidate in alternative_architecture_spec["candidates"]:
        by_key[candidate["strategy_key"]] = _evaluate_approved_policy(
            _evaluate_route_supported_strategy_on_fixture_basket(
                client,
                focus_chart_spec,
                focus_ohlcv_full,
                mock_focus_download,
                candidate["strategy_key"],
            ),
            focus_chart_spec,
        )

    assert lead_key == "bb_breakout"
    assert len(by_key["bb_breakout"]["severe_drawdown_violations"]) == 2
    assert len(by_key["keltner"]["severe_drawdown_violations"]) == 2
    assert len(by_key["macd"]["severe_drawdown_violations"]) == 4
    assert by_key["bb_breakout"]["aggregate_score"] > by_key["keltner"]["aggregate_score"]
    assert by_key["macd"]["aggregate_score"] > by_key["bb_breakout"]["aggregate_score"]
