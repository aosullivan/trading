"""Deterministic Phase 10 hardening prototypes for weekly_core_overlay_v1."""

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
_HARDENING_SPEC_PATH = _FIXTURES / "focus_basket_hardening_prototypes.json"
_CANONICAL_SPEC_PATH = _FIXTURES / "focus_basket_benchmarks.json"


@pytest.fixture
def hardening_spec():
    return json.loads(_HARDENING_SPEC_PATH.read_text(encoding="utf-8"))


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


def _prototype_profile_map(overrides: dict) -> dict:
    profile_map = {
        key: dict(value)
        for key, value in chart_module.CORE_OVERLAY_STRATEGY_PROFILES.items()
    }
    for ticker, profile in overrides.items():
        profile_map[ticker] = dict(profile)
    return profile_map


def _evaluate_prototype(
    app,
    client,
    focus_chart_spec,
    mock_focus_download,
    strategy_key: str,
    profile_overrides: dict,
):
    prototype_profiles = _prototype_profile_map(profile_overrides)
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


def test_equity_overlay_keltner_prototype_reduces_severe_blockers_without_changing_contract(
    app, client, focus_chart_spec, mock_focus_download, hardening_spec
):
    baseline = _evaluate_approved_policy(
        _evaluate_strategy_on_fixture_basket(
            client,
            focus_chart_spec,
            mock_focus_download,
            hardening_spec["strategy_key"],
        ),
        focus_chart_spec,
    )
    prototype = hardening_spec["prototypes"][0]
    outcome = _evaluate_prototype(
        app,
        client,
        focus_chart_spec,
        mock_focus_download,
        hardening_spec["strategy_key"],
        prototype["profile_overrides"],
    )

    assert outcome["aggregate_score"] >= focus_chart_spec["aggregate_score_floor"]
    assert outcome["improved_tickers"] == len(focus_chart_spec["tickers"])
    assert outcome["buy_hold_gap_violations"] == []
    assert len(outcome["severe_drawdown_violations"]) < len(
        baseline["severe_drawdown_violations"]
    )
    assert [item["ticker"] for item in outcome["moderate_drawdown_violations"]] == [
        "BTC-USD",
        "AAPL",
        "NVDA",
    ]
    assert [item["ticker"] for item in outcome["severe_drawdown_violations"]] == [
        "ETH-USD",
        "TSLA",
    ]
    assert outcome["passed"] is False


def test_combined_equity_and_crypto_hardening_improves_score_but_does_not_fix_severe_blockers(
    app, client, focus_chart_spec, mock_focus_download, hardening_spec
):
    baseline = _evaluate_approved_policy(
        _evaluate_strategy_on_fixture_basket(
            client,
            focus_chart_spec,
            mock_focus_download,
            hardening_spec["strategy_key"],
        ),
        focus_chart_spec,
    )
    prototype = hardening_spec["prototypes"][1]
    outcome = _evaluate_prototype(
        app,
        client,
        focus_chart_spec,
        mock_focus_download,
        hardening_spec["strategy_key"],
        prototype["profile_overrides"],
    )

    assert outcome["aggregate_score"] >= baseline["aggregate_score"]
    assert outcome["improved_tickers"] == len(focus_chart_spec["tickers"])
    assert outcome["buy_hold_gap_violations"] == []
    assert len(outcome["severe_drawdown_violations"]) == len(
        baseline["severe_drawdown_violations"]
    )
    assert [item["ticker"] for item in outcome["moderate_drawdown_violations"]] == [
        "AAPL",
        "NVDA",
    ]
    assert [item["ticker"] for item in outcome["severe_drawdown_violations"]] == [
        "BTC-USD",
        "ETH-USD",
        "TSLA",
    ]
    assert outcome["passed"] is False
