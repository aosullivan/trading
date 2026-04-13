"""Deterministic ratchet benchmark for the seven-ticker corpus_trend basket."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

os.environ.setdefault("TRIEDINGVIEW_USER_DATA_DIR", tempfile.mkdtemp())

from lib.cache import _cache
from lib.data_fetching import _slice_df
from lib.settings import INITIAL_CAPITAL

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SPEC_PATH = _FIXTURES / "focus_basket_benchmarks.json"


def _score_from_metrics(net_profit_pct: float, max_drawdown_pct: float, buy_hold_net_profit_pct: float) -> float:
    gap_penalty = max(0.0, buy_hold_net_profit_pct - net_profit_pct)
    return round(net_profit_pct - 0.35 * max_drawdown_pct - gap_penalty, 2)


def _buy_hold_net_profit_pct(payload: dict) -> float:
    curve = payload["buy_hold_equity_curve"]
    return round((curve[-1]["value"] / INITIAL_CAPITAL - 1) * 100, 2)


def _buy_hold_gap_pct(net_profit_pct: float, buy_hold_net_profit_pct: float) -> float:
    return round(net_profit_pct - buy_hold_net_profit_pct, 2)


@pytest.fixture
def focus_chart_spec():
    return json.loads(_SPEC_PATH.read_text(encoding="utf-8"))


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


def _chart_query(chart_request: dict, ticker: str) -> str:
    return (
        f"/api/chart?ticker={ticker}&interval={chart_request['interval']}"
        f"&start={chart_request['start']}&end={chart_request['end']}"
        f"&period={chart_request['period']}&multiplier={chart_request['multiplier']}"
    )


def _evaluate_strategy_on_fixture_basket(
    client,
    focus_chart_spec: dict,
    mock_focus_download,
    strategy_key: str,
):
    results = []
    for ticker in focus_chart_spec["tickers"]:
        _cache.clear()
        with patch("routes.chart.cached_download", side_effect=mock_focus_download):
            resp = client.get(_chart_query(focus_chart_spec["chart_request"], ticker))

        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        assert "error" not in data

        strategy_payload = data["strategies"][strategy_key]
        summary = strategy_payload["summary"]
        buy_hold_net_profit_pct = _buy_hold_net_profit_pct(strategy_payload)
        results.append(
            {
                "ticker": ticker,
                "payload": strategy_payload,
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


def _evaluate_approved_policy(candidate_results: list[dict], focus_chart_spec: dict) -> dict:
    policy = focus_chart_spec["approved_policy"]
    aggregate_score = round(sum(result["score"] for result in candidate_results) / len(candidate_results), 2)
    improved_tickers = 0
    buy_hold_gap_violations = []
    moderate_drawdown_violations = []
    severe_drawdown_violations = []

    for result in candidate_results:
        ticker = result["ticker"]
        summary = result["summary"]
        pinned = focus_chart_spec["per_ticker"][ticker]

        if result["score"] >= pinned["score"]:
            improved_tickers += 1

        pinned_buy_hold_gap_pct = _buy_hold_gap_pct(
            pinned["net_profit_pct"],
            pinned["buy_hold_net_profit_pct"],
        )
        actual_buy_hold_gap_pct = _buy_hold_gap_pct(
            summary["net_profit_pct"],
            result["buy_hold_net_profit_pct"],
        )

        if actual_buy_hold_gap_pct < (
            pinned_buy_hold_gap_pct - policy["buy_hold_gap_regression_limit_pct"]
        ):
            buy_hold_gap_violations.append(ticker)

        allowed_drawdown = round(
            pinned["max_drawdown_pct"] + policy["base_drawdown_regression_limit_pct"],
            2,
        )
        overshoot = round(summary["max_drawdown_pct"] - allowed_drawdown, 2)

        if overshoot <= 0:
            continue
        violation = {"ticker": ticker, "overshoot_pct": overshoot}
        if overshoot <= policy["moderate_overshoot_limit_pct"]:
            moderate_drawdown_violations.append(violation)
        else:
            severe_drawdown_violations.append(violation)

    passed = (
        aggregate_score >= focus_chart_spec["aggregate_score_floor"]
        and improved_tickers >= policy["min_tickers_improved"]
        and not buy_hold_gap_violations
        and len(moderate_drawdown_violations) <= policy["max_moderate_violations"]
        and len(severe_drawdown_violations) <= policy["max_severe_violations"]
    )

    return {
        "passed": passed,
        "aggregate_score": aggregate_score,
        "improved_tickers": improved_tickers,
        "buy_hold_gap_violations": buy_hold_gap_violations,
        "moderate_drawdown_violations": moderate_drawdown_violations,
        "severe_drawdown_violations": severe_drawdown_violations,
    }


def test_focus_basket_corpus_trend_respects_promoted_ratchet_baseline(
    app, client, focus_chart_spec, mock_focus_download
):
    strategy_key = focus_chart_spec["strategy_key"]
    outcome = _evaluate_approved_policy(
        _evaluate_strategy_on_fixture_basket(
            client,
            focus_chart_spec,
            mock_focus_download,
            strategy_key,
        ),
        focus_chart_spec,
    )
    assert outcome["passed"] is True
    assert outcome["buy_hold_gap_violations"] == []
    assert outcome["moderate_drawdown_violations"] == []
    assert outcome["severe_drawdown_violations"] == []


def test_weekly_core_overlay_candidate_improves_scores_but_fails_approved_tiered_drawdown_guard(
    app, client, focus_chart_spec, mock_focus_download
):
    outcome = _evaluate_approved_policy(
        _evaluate_strategy_on_fixture_basket(
            client,
            focus_chart_spec,
            mock_focus_download,
            "weekly_core_overlay_v1",
        ),
        focus_chart_spec,
    )
    assert outcome["aggregate_score"] >= focus_chart_spec["aggregate_score_floor"]
    assert outcome["improved_tickers"] == len(focus_chart_spec["tickers"])
    assert outcome["buy_hold_gap_violations"] == []
    assert [item["ticker"] for item in outcome["moderate_drawdown_violations"]] == [
        "BTC-USD",
        "AAPL",
        "NVDA",
    ]
    assert [item["ticker"] for item in outcome["severe_drawdown_violations"]] == [
        "ETH-USD",
        "TSLA",
        "GOOG",
    ]
    assert outcome["passed"] is False
