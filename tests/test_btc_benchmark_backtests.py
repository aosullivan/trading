"""BTC-USD benchmark backtests: strategy must beat HODL and meet pinned PnL floors.

Data is frozen in tests/fixtures/btc_usd_1d_benchmark.csv so CI stays deterministic
(no live Yahoo). Logic matches /api/chart for the same query parameters.
"""

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
_BTC_CSV = _FIXTURES / "btc_usd_1d_benchmark.csv"
_SPEC_PATH = _FIXTURES / "btc_benchmark_backtests.json"


@pytest.fixture
def btc_ohlcv_full():
    df = pd.read_csv(_BTC_CSV, index_col=0, parse_dates=True)
    return df[~df.index.duplicated(keep="last")].sort_index()


@pytest.fixture
def mock_btc_download(btc_ohlcv_full):
    def _mock(ticker, **kwargs):
        return _slice_df(btc_ohlcv_full, kwargs.get("start"), kwargs.get("end"))

    return _mock


@pytest.fixture
def chart_spec():
    return json.loads(_SPEC_PATH.read_text(encoding="utf-8"))


def _hodl_net_profit_pct(payload: dict) -> float:
    bh = payload["buy_hold_equity_curve"]
    return (bh[-1]["value"] / INITIAL_CAPITAL - 1) * 100


def test_btc_benchmark_strategies_beat_hodl_and_meet_pnl_floors(
    app, client, mock_btc_download, chart_spec
):
    req = chart_spec["chart_request"]
    expected_hodl = chart_spec["expected_hodl_net_profit_pct"]
    strategies = chart_spec["strategies"]

    qs = (
        f"/api/chart?ticker={req['ticker']}&interval={req['interval']}"
        f"&start={req['start']}&end={req['end']}"
        f"&period={req['period']}&multiplier={req['multiplier']}"
    )

    _cache.clear()
    with patch("routes.chart.cached_download", side_effect=mock_btc_download):
        resp = client.get(qs)

    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert "error" not in data

    hodl_pct = _hodl_net_profit_pct(data)
    assert abs(round(hodl_pct, 2) - expected_hodl) < 0.05, (
        f"HODL net % drift ({hodl_pct} vs expected {expected_hodl}) — wrong fixture?"
    )

    for name, meta in strategies.items():
        summ = data["strategies"][name]["summary"]
        net = summ["net_profit_pct"]
        floor = meta["min_net_profit_pct"]
        assert net > hodl_pct, (
            f"{name}: net_profit_pct={net} must beat HODL {hodl_pct} "
            f"(see {meta.get('source_url', '')})"
        )
        assert net >= floor, (
            f"{name}: net_profit_pct={net} below pinned floor {floor} "
            f"(performance regression; intentional change requires updating "
            f"btc_benchmark_backtests.json + fixture together)"
        )
