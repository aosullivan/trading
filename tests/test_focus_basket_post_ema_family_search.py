"""Deterministic v1.11 post-EMA family comparison harness."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from lib.data_fetching import _slice_df
from tests.test_focus_basket_benchmark_backtests import (
    _chart_query,
    _evaluate_approved_policy,
    _score_from_metrics,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SPEC_PATH = _FIXTURES / "focus_basket_post_ema_family_search.json"
_CANONICAL_SPEC_PATH = _FIXTURES / "focus_basket_benchmarks.json"


@pytest.fixture
def post_ema_family_spec():
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


def _evaluate_candidate(
    client,
    focus_chart_spec: dict,
    focus_ohlcv_full: dict,
    mock_focus_download,
    candidate: dict,
):
    results = []
    for ticker in focus_chart_spec["tickers"]:
        query = _chart_query(focus_chart_spec["chart_request"], ticker)
        for key, value in candidate.get("query_params", {}).items():
            query += f"&{key}={value}"
        with patch("routes.chart.cached_download", side_effect=mock_focus_download):
            resp = client.get(query)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        payload = resp.get_json()["strategies"][candidate["strategy_key"]]
        summary = payload["summary"]
        buy_hold = _buy_hold_pct(focus_ohlcv_full[ticker], focus_chart_spec["chart_request"])
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
    return results


@pytest.mark.parametrize("candidate_index", [0, 1, 2, 3, 4, 5])
def test_v11_candidates_match_frozen_focus_basket_outcomes(
    app,
    client,
    focus_chart_spec,
    focus_ohlcv_full,
    mock_focus_download,
    post_ema_family_spec,
    candidate_index,
):
    candidate = post_ema_family_spec["candidates"][candidate_index]
    outcome = _evaluate_approved_policy(
        _evaluate_candidate(
            client,
            focus_chart_spec,
            focus_ohlcv_full,
            mock_focus_download,
            candidate,
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


def test_cci_trend_is_the_best_post_ema_family_lead(
    app,
    client,
    focus_chart_spec,
    focus_ohlcv_full,
    mock_focus_download,
    post_ema_family_spec,
):
    by_key = {}
    for candidate in post_ema_family_spec["candidates"]:
        by_key[candidate["candidate_key"]] = _evaluate_approved_policy(
            _evaluate_candidate(
                client,
                focus_chart_spec,
                focus_ohlcv_full,
                mock_focus_download,
                candidate,
            ),
            focus_chart_spec,
        )

    assert post_ema_family_spec["recommended_family_lead"] == "cci_trend"
    assert post_ema_family_spec["recommended_hardening_probe"] == "cci_trend__layered_50_50"
    assert by_key["cci_trend"]["aggregate_score"] > by_key["supertrend"]["aggregate_score"]
    assert by_key["cci_trend"]["aggregate_score"] > by_key["orb_breakout"]["aggregate_score"]
    assert len(by_key["cci_trend__layered_50_50"]["severe_drawdown_violations"]) == 2
    assert by_key["cci_trend__layered_50_50"]["buy_hold_gap_violations"] == [
        "BTC-USD",
        "ETH-USD",
        "COIN",
        "TSLA",
        "AAPL",
    ]
    assert by_key["cci_trend"]["improved_tickers"] == 5
