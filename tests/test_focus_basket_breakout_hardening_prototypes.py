"""Deterministic v1.6 breakout-family hardening prototypes."""

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
_SPEC_PATH = _FIXTURES / "focus_basket_breakout_hardening_prototypes.json"
_CANONICAL_SPEC_PATH = _FIXTURES / "focus_basket_benchmarks.json"


@pytest.fixture
def breakout_hardening_spec():
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


def _evaluate_mixed_candidate(
    client,
    focus_chart_spec: dict,
    focus_ohlcv_full: dict,
    mock_focus_download,
    ticker_strategy_map: dict[str, str],
):
    results = []
    for ticker in focus_chart_spec["tickers"]:
        with patch("routes.chart.cached_download", side_effect=mock_focus_download):
            resp = client.get(_chart_query(focus_chart_spec["chart_request"], ticker))
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        strategy_key = ticker_strategy_map[ticker]
        payload = data["strategies"][strategy_key]
        summary = payload["summary"]
        bh = _buy_hold_pct(focus_ohlcv_full[ticker], focus_chart_spec["chart_request"])
        results.append(
            {
                "ticker": ticker,
                "summary": summary,
                "buy_hold_net_profit_pct": bh,
                "score": _score_from_metrics(
                    summary["net_profit_pct"],
                    summary["max_drawdown_pct"],
                    bh,
                ),
            }
        )
    return results


@pytest.mark.parametrize("candidate_index", [0, 1, 2, 3])
def test_breakout_family_hardening_candidates_match_frozen_outcomes(
    app,
    client,
    focus_chart_spec,
    focus_ohlcv_full,
    mock_focus_download,
    breakout_hardening_spec,
    candidate_index,
):
    candidate = breakout_hardening_spec["candidates"][candidate_index]
    outcome = _evaluate_approved_policy(
        _evaluate_mixed_candidate(
            client,
            focus_chart_spec,
            focus_ohlcv_full,
            mock_focus_download,
            candidate["ticker_strategy_map"],
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


def test_coin_goog_keltner_is_the_best_breakout_family_carry_forward_candidate(
    app,
    client,
    focus_chart_spec,
    focus_ohlcv_full,
    mock_focus_download,
    breakout_hardening_spec,
):
    by_key = {}
    for candidate in breakout_hardening_spec["candidates"]:
        by_key[candidate["candidate_key"]] = _evaluate_approved_policy(
            _evaluate_mixed_candidate(
                client,
                focus_chart_spec,
                focus_ohlcv_full,
                mock_focus_download,
                candidate["ticker_strategy_map"],
            ),
            focus_chart_spec,
        )

    assert breakout_hardening_spec["recommended_lead"] == "coin_goog_keltner_v1"
    assert len(by_key["coin_goog_keltner_v1"]["severe_drawdown_violations"]) == 2
    assert len(by_key["bb_breakout_control"]["severe_drawdown_violations"]) == 3
    assert by_key["coin_goog_keltner_v1"]["aggregate_score"] > 300
    assert by_key["coin_goog_keltner_v1"]["aggregate_score"] > by_key["eth_keltner_v1"]["aggregate_score"]
