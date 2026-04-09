"""Deterministic route-level ratchet for calibrated managed-sizing chart variants."""

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
import lib.backtesting as backtesting

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_MANAGED_SPEC = _FIXTURES / "managed_sizing_benchmark_backtests.json"
_FOCUS_SPEC = _FIXTURES / "focus_basket_benchmarks.json"
_POLY_HISTORY = _FIXTURES / "polymarket_probability_history_benchmark.json"


@pytest.fixture
def managed_spec():
    return json.loads(_MANAGED_SPEC.read_text(encoding="utf-8"))


@pytest.fixture
def focus_spec():
    return json.loads(_FOCUS_SPEC.read_text(encoding="utf-8"))


@pytest.fixture
def managed_ohlcv_full(focus_spec):
    fixtures = {}
    for ticker, meta in focus_spec["per_ticker"].items():
        df = pd.read_csv(Path(meta["fixture_csv"]), index_col=0, parse_dates=True)
        fixtures[ticker] = df[~df.index.duplicated(keep="last")].sort_index()
    return fixtures


@pytest.fixture
def mock_managed_download(managed_ohlcv_full):
    def _mock(ticker, **kwargs):
        if ticker not in managed_ohlcv_full:
            raise AssertionError(f"Unexpected ticker request: {ticker}")
        return _slice_df(managed_ohlcv_full[ticker], kwargs.get("start"), kwargs.get("end"))

    return _mock


@pytest.fixture
def managed_polymarket_history():
    records = json.loads(_POLY_HISTORY.read_text(encoding="utf-8"))
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _chart_query(chart_request: dict, ticker: str, params: dict[str, str]) -> str:
    query = {
        "ticker": ticker,
        "interval": chart_request["interval"],
        "start": chart_request["start"],
        "end": chart_request["end"],
        "period": str(chart_request["period"]),
        "multiplier": str(chart_request["multiplier"]),
    }
    query.update(params)
    return "/api/chart?" + "&".join(f"{key}={value}" for key, value in query.items())


def _avg_entry_notional_pct(trades: list[dict], initial_capital: float) -> float:
    if not trades or not initial_capital:
        return 0.0
    values = [
        (float(trade["quantity"]) * float(trade["entry_price"])) / initial_capital * 100
        for trade in trades
    ]
    return round(sum(values) / len(values), 2)


def test_managed_sizing_route_matches_calibrated_benchmarks(
    app, client, managed_spec, mock_managed_download, managed_polymarket_history
):
    assert managed_spec["selected_defaults"]["vol_scale_factor"] == backtesting.DEFAULT_VOL_SCALE_FACTOR
    assert (
        managed_spec["selected_defaults"]["fixed_fraction_risk_fraction"]
        == backtesting.DEFAULT_FIXED_FRACTION_RISK
    )

    chart_request = managed_spec["chart_request"]
    strategy_key = managed_spec["strategy_key"]

    for variant_id, variant in managed_spec["variants"].items():
        for ticker in managed_spec["tickers"]:
            expected = variant["per_ticker"][ticker]
            _cache.clear()
            with patch("routes.chart.cached_download", side_effect=mock_managed_download), patch(
                "routes.chart._resolve_cached_ticker_name", side_effect=lambda raw: raw
            ), patch(
                "lib.polymarket.load_probability_history",
                return_value=managed_polymarket_history,
            ):
                resp = client.get(_chart_query(chart_request, ticker, variant["query_params"]))

            assert resp.status_code == 200, resp.get_data(as_text=True)
            data = resp.get_json()
            strategy = data["strategies"][strategy_key]
            summary = strategy["summary"]

            assert round(float(summary["net_profit_pct"]), 2) == expected["net_profit_pct"], variant_id
            assert round(float(summary["max_drawdown_pct"]), 2) == expected["max_drawdown_pct"], variant_id
            assert round(float(summary["ending_equity"]), 2) == expected["ending_equity"], variant_id
            assert int(summary["total_trades"]) == expected["total_trades"], variant_id
            assert (
                _avg_entry_notional_pct(
                    strategy["trades"], float(summary.get("initial_capital", 0.0))
                )
                == expected["avg_entry_notional_pct"]
            ), variant_id
            assert strategy["backtest_window_policy"] == expected["backtest_window_policy"], variant_id
            assert bool(strategy["window_started_mid_trend"]) is expected["window_started_mid_trend"], variant_id
