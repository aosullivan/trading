"""Deterministic Phase 13 targeted hardening prototypes for the final severe blockers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

os.environ.setdefault("TRIEDINGVIEW_USER_DATA_DIR", tempfile.mkdtemp())

import routes.chart as chart_module
from lib.cache import _cache
from lib.data_fetching import _slice_df
from tests.test_focus_basket_benchmark_backtests import (
    _evaluate_approved_policy,
    _evaluate_strategy_on_fixture_basket,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_FINAL_BLOCKER_SPEC_PATH = _FIXTURES / "focus_basket_final_blocker_prototypes.json"
_CANONICAL_SPEC_PATH = _FIXTURES / "focus_basket_benchmarks.json"


@pytest.fixture
def final_blocker_spec():
    return json.loads(_FINAL_BLOCKER_SPEC_PATH.read_text(encoding="utf-8"))


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


def _prototype_profile_map(base_overrides: dict, overrides: dict) -> dict:
    profile_map = {
        key: dict(value)
        for key, value in chart_module.CORE_OVERLAY_STRATEGY_PROFILES.items()
    }
    for ticker, profile in base_overrides.items():
        profile_map[ticker] = dict(profile)
    for ticker, profile in overrides.items():
        profile_map[ticker] = dict(profile)
    return profile_map


def _evaluate_prototype(
    client,
    focus_chart_spec,
    mock_focus_download,
    strategy_key: str,
    base_profile_overrides: dict,
    profile_overrides: dict,
):
    prototype_profiles = _prototype_profile_map(base_profile_overrides, profile_overrides)
    _cache.clear()
    with patch.object(chart_module, "CORE_OVERLAY_STRATEGY_PROFILES", prototype_profiles):
        return _evaluate_approved_policy(
            _evaluate_strategy_on_fixture_basket(
                client,
                focus_chart_spec,
                mock_focus_download,
                strategy_key,
            ),
            focus_chart_spec,
        )


def test_eth_targeted_follow_up_reduces_eth_severity_while_preserving_full_breadth(
    client, focus_chart_spec, mock_focus_download, final_blocker_spec
):
    prototype = final_blocker_spec["prototypes"][0]
    outcome = _evaluate_prototype(
        client,
        focus_chart_spec,
        mock_focus_download,
        final_blocker_spec["strategy_key"],
        final_blocker_spec["base_profile_overrides"],
        prototype["profile_overrides"],
    )

    assert outcome["aggregate_score"] == 299.57
    assert outcome["improved_tickers"] == 5
    assert outcome["buy_hold_gap_violations"] == ["BTC-USD", "ETH-USD"]
    assert [item["ticker"] for item in outcome["moderate_drawdown_violations"]] == ["AAPL"]
    assert [item["ticker"] for item in outcome["severe_drawdown_violations"]] == [
        "BTC-USD",
        "ETH-USD",
        "TSLA",
    ]
    assert outcome["severe_drawdown_violations"][0]["overshoot_pct"] == 11.14
    assert outcome["passed"] is False


def test_tsla_targeted_follow_up_clears_tsla_severe_blocker_but_creates_buy_hold_gap(
    client, focus_chart_spec, mock_focus_download, final_blocker_spec
):
    prototype = final_blocker_spec["prototypes"][1]
    outcome = _evaluate_prototype(
        client,
        focus_chart_spec,
        mock_focus_download,
        final_blocker_spec["strategy_key"],
        final_blocker_spec["base_profile_overrides"],
        prototype["profile_overrides"],
    )

    assert outcome["aggregate_score"] == 199.7
    assert outcome["improved_tickers"] == 4
    assert outcome["buy_hold_gap_violations"] == ["BTC-USD", "ETH-USD", "TSLA"]
    assert [item["ticker"] for item in outcome["moderate_drawdown_violations"]] == ["AAPL"]
    assert [item["ticker"] for item in outcome["severe_drawdown_violations"]] == [
        "BTC-USD",
        "ETH-USD",
    ]
    assert outcome["passed"] is False


def test_combined_follow_up_reduces_severe_set_to_eth_only_but_is_not_best_carry_forward(
    client, focus_chart_spec, mock_focus_download, final_blocker_spec
):
    prototype = final_blocker_spec["prototypes"][2]
    outcome = _evaluate_prototype(
        client,
        focus_chart_spec,
        mock_focus_download,
        final_blocker_spec["strategy_key"],
        final_blocker_spec["base_profile_overrides"],
        prototype["profile_overrides"],
    )

    assert outcome["aggregate_score"] == 99.76
    assert outcome["improved_tickers"] == 4
    assert outcome["buy_hold_gap_violations"] == ["BTC-USD", "ETH-USD", "TSLA"]
    assert [item["ticker"] for item in outcome["moderate_drawdown_violations"]] == ["AAPL"]
    assert [item["ticker"] for item in outcome["severe_drawdown_violations"]] == [
        "BTC-USD",
        "ETH-USD",
    ]
    assert outcome["passed"] is False
