"""Deterministic BTC Polymarket ratchet benchmark using frozen fixtures."""

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

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SPEC_PATH = _FIXTURES / "polymarket_benchmark_backtests.json"


@pytest.fixture
def polymarket_chart_spec():
    return json.loads(_SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def polymarket_ohlcv_full(polymarket_chart_spec):
    csv_path = Path(polymarket_chart_spec["fixtures"]["ohlcv_csv"])
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    return df[~df.index.duplicated(keep="last")].sort_index()


@pytest.fixture
def polymarket_history_df(polymarket_chart_spec):
    history_path = Path(polymarket_chart_spec["fixtures"]["probability_history_json"])
    records = json.loads(history_path.read_text(encoding="utf-8"))
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


@pytest.fixture
def mock_polymarket_download(polymarket_ohlcv_full):
    def _mock(ticker, **kwargs):
        if ticker != "BTC-USD":
            raise AssertionError(f"Unexpected ticker request: {ticker}")
        return _slice_df(polymarket_ohlcv_full, kwargs.get("start"), kwargs.get("end"))

    return _mock


def _chart_query(chart_request: dict) -> str:
    return (
        f"/api/chart?ticker={chart_request['ticker']}&interval={chart_request['interval']}"
        f"&start={chart_request['start']}&end={chart_request['end']}"
        f"&period={chart_request['period']}&multiplier={chart_request['multiplier']}"
    )


def test_polymarket_strategy_respects_promoted_ratchet_floor(
    app, client, polymarket_chart_spec, polymarket_history_df, mock_polymarket_download
):
    req = polymarket_chart_spec["chart_request"]
    strategy_key = polymarket_chart_spec["strategy_key"]
    floor = polymarket_chart_spec["promoted_floor"]

    _cache.clear()
    with patch("routes.chart.cached_download", side_effect=mock_polymarket_download), patch(
        "lib.polymarket.load_probability_history", return_value=polymarket_history_df
    ):
        resp = client.get(_chart_query(req))

    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert "error" not in data

    summary = data["strategies"][strategy_key]["summary"]
    assert summary["ending_equity"] >= floor["ending_equity"]
    assert summary["total_pnl"] >= floor["total_pnl"]
    assert summary["net_profit_pct"] >= floor["net_profit_pct"]
    assert summary["total_trades"] >= floor["total_trades"]
    assert summary["max_drawdown_pct"] <= floor["max_drawdown_pct"]
