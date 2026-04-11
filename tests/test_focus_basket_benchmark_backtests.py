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


def test_focus_basket_corpus_trend_respects_promoted_ratchet_baseline(
    app, client, focus_chart_spec, mock_focus_download
):
    tickers = focus_chart_spec["tickers"]
    strategy_key = focus_chart_spec["strategy_key"]
    max_drawdown_regression = focus_chart_spec["max_drawdown_regression_limit_pct"]
    buy_hold_gap_regression = focus_chart_spec["buy_hold_gap_regression_limit_pct"]
    min_tickers_improved = focus_chart_spec["min_tickers_improved"]

    aggregate_scores = []
    improved_tickers = 0
    regressed_scores = 0

    for result in _evaluate_strategy_on_fixture_basket(
        client,
        focus_chart_spec,
        mock_focus_download,
        strategy_key,
    ):
        ticker = result["ticker"]
        strategy_payload = result["payload"]
        summary = result["summary"]
        pinned = focus_chart_spec["per_ticker"][ticker]
        buy_hold_net_profit_pct = result["buy_hold_net_profit_pct"]
        score = result["score"]
        aggregate_scores.append(score)

        pinned_buy_hold_gap_pct = round(
            pinned["net_profit_pct"] - pinned["buy_hold_net_profit_pct"],
            2,
        )
        actual_buy_hold_gap_pct = round(
            summary["net_profit_pct"] - buy_hold_net_profit_pct,
            2,
        )

        assert abs(buy_hold_net_profit_pct - pinned["buy_hold_net_profit_pct"]) < 0.05
        assert summary["max_drawdown_pct"] <= (
            pinned["max_drawdown_pct"] + max_drawdown_regression
        ), f"{ticker} drawdown regressed beyond allowed limit"
        assert actual_buy_hold_gap_pct >= (
            pinned_buy_hold_gap_pct - buy_hold_gap_regression
        ), f"{ticker} buy-hold gap regressed beyond allowed limit"

        if score >= pinned["score"]:
            improved_tickers += 1
        else:
            regressed_scores += 1

    aggregate_score = round(sum(aggregate_scores) / len(aggregate_scores), 2)
    assert aggregate_score >= focus_chart_spec["aggregate_score_floor"]
    assert improved_tickers >= min_tickers_improved
    assert regressed_scores <= len(tickers) - min_tickers_improved


def test_weekly_core_overlay_candidate_improves_scores_but_fails_drawdown_promotion_guard(
    app, client, focus_chart_spec, mock_focus_download
):
    candidate_results = _evaluate_strategy_on_fixture_basket(
        client,
        focus_chart_spec,
        mock_focus_download,
        "weekly_core_overlay_v1",
    )
    max_drawdown_regression = focus_chart_spec["max_drawdown_regression_limit_pct"]
    buy_hold_gap_regression = focus_chart_spec["buy_hold_gap_regression_limit_pct"]

    aggregate_score = round(sum(r["score"] for r in candidate_results) / len(candidate_results), 2)
    improved_tickers = 0
    drawdown_violations = []
    buy_hold_gap_violations = []

    for result in candidate_results:
        ticker = result["ticker"]
        summary = result["summary"]
        pinned = focus_chart_spec["per_ticker"][ticker]
        if result["score"] >= pinned["score"]:
            improved_tickers += 1

        pinned_buy_hold_gap_pct = round(
            pinned["net_profit_pct"] - pinned["buy_hold_net_profit_pct"],
            2,
        )
        actual_buy_hold_gap_pct = round(
            summary["net_profit_pct"] - result["buy_hold_net_profit_pct"],
            2,
        )

        if summary["max_drawdown_pct"] > (
            pinned["max_drawdown_pct"] + max_drawdown_regression
        ):
            drawdown_violations.append(ticker)
        if actual_buy_hold_gap_pct < (
            pinned_buy_hold_gap_pct - buy_hold_gap_regression
        ):
            buy_hold_gap_violations.append(ticker)

    assert aggregate_score >= focus_chart_spec["aggregate_score_floor"]
    assert improved_tickers == len(focus_chart_spec["tickers"])
    assert drawdown_violations == ["BTC-USD", "ETH-USD", "TSLA", "AAPL", "NVDA", "GOOG"]
    assert buy_hold_gap_violations == []
