"""Strategy performance regression gates (deterministic data only).

Thresholds live in tests/fixtures/strategy_regression_thresholds.json.
These tests are meant for CI merge protection, not for live-market guarantees.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from lib.backtesting import backtest_ribbon_regime
from lib.technical_indicators import compute_trend_ribbon

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_THRESHOLDS_PATH = _FIXTURES / "strategy_regression_thresholds.json"


def _load_thresholds():
    data = json.loads(_THRESHOLDS_PATH.read_text(encoding="utf-8"))
    return data["scenarios"]


def _assert_metrics(summary: dict, rules: dict, scenario_id: str):
    for key, bounds in rules.items():
        if key not in summary:
            pytest.fail(f"{scenario_id}: summary missing key {key!r}")
        actual = summary[key]
        if "min" in bounds:
            if actual is None:
                pytest.fail(f"{scenario_id}: {key} is None, expected >= {bounds['min']}")
            assert actual >= bounds["min"], (
                f"{scenario_id}: {key}={actual} below floor {bounds['min']}"
            )
        if "max" in bounds:
            if actual is None:
                pytest.fail(f"{scenario_id}: {key} is None, expected <= {bounds['max']}")
            assert actual <= bounds["max"], (
                f"{scenario_id}: {key}={actual} above ceiling {bounds['max']}"
            )


def _run_ribbon_regime(sample_df: pd.DataFrame) -> dict:
    _, _, _, _, daily = compute_trend_ribbon(sample_df)
    _, _, _, _, weekly = compute_trend_ribbon(sample_df, ema_period=21)
    _trades, summary, _eq = backtest_ribbon_regime(sample_df, daily, weekly)
    return summary


def _run_ribbon_regime_dd_gate(sample_df: pd.DataFrame) -> dict:
    _, _, _, _, daily = compute_trend_ribbon(sample_df)
    _, _, _, _, weekly = compute_trend_ribbon(sample_df, ema_period=21)
    _trades, summary, _eq = backtest_ribbon_regime(
        sample_df,
        daily,
        weekly,
        max_dd_exit_gate=-0.35,
        price_series=sample_df["Close"],
    )
    return summary


_HANDLERS = {
    "ribbon_regime": _run_ribbon_regime,
    "ribbon_regime_dd_gate": _run_ribbon_regime_dd_gate,
}


@pytest.mark.parametrize("scenario", _load_thresholds(), ids=lambda s: s["id"])
def test_strategy_regression_thresholds(scenario, sample_df):
    handler_name = scenario.get("handler")
    if handler_name not in _HANDLERS:
        pytest.fail(f"Unknown handler {handler_name!r} in scenario {scenario['id']!r}")
    summary = _HANDLERS[handler_name](sample_df)
    _assert_metrics(summary, scenario["metrics"], scenario["id"])
