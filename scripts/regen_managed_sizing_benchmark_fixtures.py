#!/usr/bin/env python3
"""Regenerate deterministic managed-sizing route benchmarks from frozen focus-basket fixtures."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from statistics import mean
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TRIEDINGVIEW_USER_DATA_DIR", tempfile.mkdtemp())

from app import app as flask_app  # noqa: E402
from lib.cache import _cache  # noqa: E402
from lib.data_fetching import _slice_df  # noqa: E402
from lib.settings import INITIAL_CAPITAL  # noqa: E402
import lib.backtesting as backtesting  # noqa: E402

FOCUS_SPEC = ROOT / "tests" / "fixtures" / "focus_basket_benchmarks.json"
OUTPUT = ROOT / "tests" / "fixtures" / "managed_sizing_benchmark_backtests.json"
POLY_HISTORY = ROOT / "tests" / "fixtures" / "polymarket_probability_history_benchmark.json"

VARIANTS = [
    {"id": "vol_trade", "params": {"mm_sizing": "vol"}},
    {"id": "fixed_fraction_trade", "params": {"mm_sizing": "fixed_fraction"}},
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_focus_fixtures(spec: dict) -> dict[str, pd.DataFrame]:
    fixtures: dict[str, pd.DataFrame] = {}
    for ticker, meta in spec["per_ticker"].items():
        fixture_path = ROOT / meta["fixture_csv"]
        df = pd.read_csv(fixture_path, index_col=0, parse_dates=True)
        fixtures[ticker] = df[~df.index.duplicated(keep="last")].sort_index()
    return fixtures


def _load_polymarket_history() -> pd.DataFrame:
    records = json.loads(POLY_HISTORY.read_text(encoding="utf-8"))
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _mock_download_factory(fixtures: dict[str, pd.DataFrame]):
    def _mock_download(ticker, **kwargs):
        if ticker not in fixtures:
            raise AssertionError(f"Unexpected ticker request: {ticker}")
        return _slice_df(fixtures[ticker], kwargs.get("start"), kwargs.get("end"))

    return _mock_download


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


def _buy_hold_net_profit_pct(curve: list[dict]) -> float:
    return round((curve[-1]["value"] / INITIAL_CAPITAL - 1) * 100, 2)


def _score_from_metrics(net_profit_pct: float, max_drawdown_pct: float, buy_hold_net_profit_pct: float) -> float:
    gap_penalty = max(0.0, buy_hold_net_profit_pct - net_profit_pct)
    return round(net_profit_pct - 0.35 * max_drawdown_pct - gap_penalty, 2)


def _avg_entry_notional_pct(trades: list[dict], initial_capital: float) -> float:
    if not trades or not initial_capital:
        return 0.0
    return round(
        mean(
            (float(trade["quantity"]) * float(trade["entry_price"])) / initial_capital * 100
            for trade in trades
        ),
        2,
    )


def _aggregate_metrics(per_ticker: dict[str, dict]) -> dict:
    return {
        "aggregate_score": round(mean(m["score"] for m in per_ticker.values()), 2),
        "avg_net_profit_pct": round(mean(m["net_profit_pct"] for m in per_ticker.values()), 2),
        "avg_max_drawdown_pct": round(mean(m["max_drawdown_pct"] for m in per_ticker.values()), 2),
        "avg_buy_hold_gap_pct": round(mean(m["buy_hold_gap_pct"] for m in per_ticker.values()), 2),
        "avg_total_trades": round(mean(m["total_trades"] for m in per_ticker.values()), 2),
        "avg_entry_notional_pct": round(mean(m["avg_entry_notional_pct"] for m in per_ticker.values()), 2),
    }


def _build_payload() -> dict:
    focus_spec = _load_json(FOCUS_SPEC)
    fixtures = _load_focus_fixtures(focus_spec)
    polymarket_history = _load_polymarket_history()
    mock_download = _mock_download_factory(fixtures)
    strategy_key = focus_spec["strategy_key"]

    variants: dict[str, dict] = {}
    with flask_app.test_client() as client:
        flask_app.config["TESTING"] = True
        with patch("routes.chart.cached_download", side_effect=mock_download), patch(
            "routes.chart._resolve_cached_ticker_name",
            side_effect=lambda ticker: ticker,
        ), patch(
            "lib.polymarket.load_probability_history",
            return_value=polymarket_history,
        ):
            for variant in VARIANTS:
                per_ticker: dict[str, dict] = {}
                for ticker in focus_spec["tickers"]:
                    _cache.clear()
                    resp = client.get(
                        _chart_query(focus_spec["chart_request"], ticker, variant["params"])
                    )
                    data = resp.get_json()
                    if resp.status_code != 200:
                        raise RuntimeError(
                            f"{variant['id']} failed for {ticker}: {resp.status_code} {data}"
                        )
                    payload = data["strategies"][strategy_key]
                    summary = payload["summary"]
                    trades = payload["trades"]
                    initial_capital = float(summary.get("initial_capital", INITIAL_CAPITAL))
                    buy_hold_net_profit_pct = _buy_hold_net_profit_pct(
                        payload["buy_hold_equity_curve"]
                    )
                    net_profit_pct = round(float(summary["net_profit_pct"]), 2)
                    max_drawdown_pct = round(float(summary["max_drawdown_pct"]), 2)
                    per_ticker[ticker] = {
                        "net_profit_pct": net_profit_pct,
                        "max_drawdown_pct": max_drawdown_pct,
                        "buy_hold_net_profit_pct": buy_hold_net_profit_pct,
                        "buy_hold_gap_pct": round(net_profit_pct - buy_hold_net_profit_pct, 2),
                        "score": _score_from_metrics(
                            net_profit_pct, max_drawdown_pct, buy_hold_net_profit_pct
                        ),
                        "total_trades": int(summary["total_trades"]),
                        "avg_entry_notional_pct": _avg_entry_notional_pct(
                            trades, initial_capital
                        ),
                        "ending_equity": round(float(summary["ending_equity"]), 2),
                        "backtest_window_policy": payload["backtest_window_policy"],
                        "window_started_mid_trend": bool(payload["window_started_mid_trend"]),
                    }
                variants[variant["id"]] = {
                    "query_params": variant["params"],
                    "aggregate_metrics": _aggregate_metrics(per_ticker),
                    "per_ticker": per_ticker,
                }

    return {
        "_comment": (
            "Pinned managed-sizing route benchmarks for calibrated chart defaults. "
            "Regenerate intentionally with this script when sizing constants move."
        ),
        "tickers": focus_spec["tickers"],
        "chart_request": focus_spec["chart_request"],
        "strategy_key": strategy_key,
        "selected_defaults": {
            "vol_scale_factor": backtesting.DEFAULT_VOL_SCALE_FACTOR,
            "fixed_fraction_risk_fraction": backtesting.DEFAULT_FIXED_FRACTION_RISK,
        },
        "variants": variants,
    }


def _validate_payload(payload: dict) -> list[str]:
    errors: list[str] = []
    if payload.get("selected_defaults", {}).get("vol_scale_factor") != backtesting.DEFAULT_VOL_SCALE_FACTOR:
        errors.append("vol_scale_factor in fixture does not match current calibrated default")
    if (
        payload.get("selected_defaults", {}).get("fixed_fraction_risk_fraction")
        != backtesting.DEFAULT_FIXED_FRACTION_RISK
    ):
        errors.append("fixed_fraction_risk_fraction in fixture does not match current calibrated default")
    if set(payload.get("variants", {})) != {variant["id"] for variant in VARIANTS}:
        errors.append("variant set does not match expected managed-sizing benchmark variants")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT, help="Output benchmark JSON path")
    parser.add_argument("--check", action="store_true", help="Validate existing fixture metadata and exit")
    args = parser.parse_args()

    if args.check:
        if not args.output.exists():
            raise SystemExit(f"Missing managed sizing benchmark fixture: {args.output}")
        errors = _validate_payload(_load_json(args.output))
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            raise SystemExit(1)
        print("Managed sizing benchmark fixture metadata looks consistent.")
        return

    payload = _build_payload()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote managed sizing benchmarks to {args.output}")


if __name__ == "__main__":
    main()
