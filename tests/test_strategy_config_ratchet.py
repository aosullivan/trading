"""Deterministic ratchet for current backtest configuration defaults and contract."""

from __future__ import annotations

import html
import json
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

os.environ.setdefault("TRIEDINGVIEW_USER_DATA_DIR", tempfile.mkdtemp())

from lib.cache import _cache
from lib.data_fetching import _slice_df

_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SPEC_PATH = _FIXTURES / "strategy_config_ratchet.json"


@pytest.fixture
def config_ratchet_spec():
    return json.loads(_SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def config_route_ohlcv(config_ratchet_spec):
    csv_path = _ROOT / config_ratchet_spec["route_contract"]["fixtures"]["ohlcv_csv"]
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    return df[~df.index.duplicated(keep="last")].sort_index()


@pytest.fixture
def config_route_polymarket_history(config_ratchet_spec):
    history_path = _ROOT / config_ratchet_spec["route_contract"]["fixtures"]["probability_history_json"]
    records = json.loads(history_path.read_text(encoding="utf-8"))
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


@pytest.fixture
def mock_config_download(config_route_ohlcv):
    def _mock(ticker, **kwargs):
        if ticker != "BTC-USD":
            raise AssertionError(f"Unexpected ticker request: {ticker}")
        return _slice_df(config_route_ohlcv, kwargs.get("start"), kwargs.get("end"))

    return _mock


def _extract_select_options(html_text: str, select_id: str) -> list[tuple[str, str]]:
    match = re.search(
        rf'<select[^>]*id="{re.escape(select_id)}"[^>]*>(.*?)</select>',
        html_text,
        re.S,
    )
    assert match, f"Missing <select id=\"{select_id}\">"
    raw_options = re.findall(r'<option value="([^"]*)">(.*?)</option>', match.group(1), re.S)
    return [(value, html.unescape(label).strip()) for value, label in raw_options]


def _chart_query(chart_request: dict) -> str:
    return (
        f"/api/chart?ticker={chart_request['ticker']}&interval={chart_request['interval']}"
        f"&start={chart_request['start']}&end={chart_request['end']}"
        f"&period={chart_request['period']}&multiplier={chart_request['multiplier']}"
    )


def test_backtest_template_and_js_match_pinned_config_contract(client, config_ratchet_spec):
    resp = client.get("/backtest")
    assert resp.status_code == 200
    page = resp.get_data(as_text=True)

    expected_strategy_options = [
        (option["value"], option["label"]) for option in config_ratchet_spec["strategy_options"]
    ]
    assert _extract_select_options(page, "strategy-select") == expected_strategy_options

    mm = config_ratchet_spec["money_management"]
    assert _extract_select_options(page, "mm-sizing") == [
        (option["value"], option["label"]) for option in mm["sizing"]["options"]
    ]
    assert _extract_select_options(page, "mm-stop") == [
        (option["value"], option["label"]) for option in mm["stop"]["options"]
    ]
    assert _extract_select_options(page, "mm-risk-cap") == [
        (option["value"], option["label"]) for option in mm["risk_cap"]["options"]
    ]
    assert _extract_select_options(page, "mm-compound") == [
        (option["value"], option["label"]) for option in mm["compound"]["options"]
    ]
    if "confirmation" in mm:
        assert _extract_select_options(page, "bt-confirm-mode") == [
            (option["value"], option["label"]) for option in mm["confirmation"]["options"]
        ]
    else:
        assert 'id="bt-confirm-mode"' not in page

    stop_input_match = re.search(
        r'<input[^>]*id="mm-stop-val"[^>]*value="([^"]+)"',
        page,
        re.S,
    )
    assert stop_input_match
    assert stop_input_match.group(1) == mm["stop_input_default_value"]

    backtest_panel_js = (_ROOT / "static/js/backtest_panel.js").read_text(encoding="utf-8")
    backtest_report_js = (_ROOT / "static/js/backtest_report.js").read_text(encoding="utf-8")

    default_strategy = config_ratchet_spec["backtest_defaults"]["default_strategy"]
    assert f"const BT_DEFAULT_STRATEGY='{default_strategy}';" in backtest_panel_js
    assert "p.get('strategy')||BT_DEFAULT_STRATEGY" in backtest_report_js
    assert "activeBacktestStrat=BT_DEFAULT_STRATEGY;" in backtest_report_js
    assert "applyMMParams({" in backtest_report_js
    assert "sizing:p.get('mm_sizing')||''" in backtest_report_js
    assert "stop:p.get('mm_stop')||''" in backtest_report_js
    assert "stopVal:p.get('mm_stop_val')||''" in backtest_report_js
    assert "riskCap:p.get('mm_risk_cap')||''" in backtest_report_js
    assert "compound:p.get('mm_compound')||'trade'" in backtest_report_js
    assert "confirmMode:p.get('confirm_mode')||''" in backtest_report_js
    assert "if(mm?.sizing)p.set('mm_sizing',mm.sizing);" in backtest_report_js
    assert "p.set('mm_stop',mm.stop);" in backtest_report_js
    assert "p.set('mm_stop_val',mm.stopVal);" in backtest_report_js
    assert "if(mm?.riskCap)p.set('mm_risk_cap',mm.riskCap);" in backtest_report_js
    assert "if(mm?.compound&&mm.compound!=='trade')p.set('mm_compound',mm.compound);" in backtest_report_js
    assert "if(mm.confirmMode)p.set('confirm_mode',mm.confirmMode);" in backtest_panel_js
    assert "if(mm?.confirmMode)p.set('confirm_mode',mm.confirmMode);" in backtest_report_js


def test_chart_route_matches_pinned_strategy_inventory(
    app,
    client,
    config_ratchet_spec,
    config_route_polymarket_history,
    mock_config_download,
):
    req = config_ratchet_spec["route_contract"]["chart_request"]
    expected_keys = config_ratchet_spec["route_contract"]["strategy_keys"]
    expected_local_buy_hold = set(
        config_ratchet_spec["route_contract"]["strategy_keys_with_local_buy_hold"]
    )

    _cache.clear()
    with patch("routes.chart.cached_download", side_effect=mock_config_download), patch(
        "lib.polymarket.load_probability_history", return_value=config_route_polymarket_history
    ):
        resp = client.get(_chart_query(req))

    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert "error" not in data
    assert "buy_hold_equity_curve" in data
    assert sorted(data["strategies"].keys()) == sorted(expected_keys)

    for key in expected_keys:
        payload = data["strategies"][key]
        assert "trades" in payload, f"{key} missing trades"
        assert "summary" in payload, f"{key} missing summary"
        assert "equity_curve" in payload, f"{key} missing equity_curve"
        if key in expected_local_buy_hold:
            assert "buy_hold_equity_curve" in payload, f"{key} missing local buy_hold_equity_curve"
