#!/usr/bin/env python3
"""Analyze focus-basket money-management variants against frozen fixtures."""

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

SPEC_PATH = ROOT / "tests" / "fixtures" / "focus_basket_benchmarks.json"
DEFAULT_JSON_OUT = (
    ROOT
    / ".planning"
    / "phases"
    / "03-build-ratchet-benchmark-and-diagnostics"
    / "focus-basket-diagnostics.json"
)
DEFAULT_MD_OUT = (
    ROOT
    / ".planning"
    / "phases"
    / "03-build-ratchet-benchmark-and-diagnostics"
    / "focus-basket-diagnostics.md"
)

VARIANT_MATRIX = [
    {"id": "baseline_none", "params": {}},
    {"id": "vol_trade", "params": {"mm_sizing": "vol"}},
    {"id": "vol_monthly", "params": {"mm_sizing": "vol", "mm_compound": "monthly"}},
    {"id": "vol_capped", "params": {"mm_sizing": "vol", "mm_risk_cap": "0.005"}},
    {"id": "fixed_fraction_trade", "params": {"mm_sizing": "fixed_fraction"}},
    {
        "id": "fixed_fraction_monthly",
        "params": {"mm_sizing": "fixed_fraction", "mm_compound": "monthly"},
    },
    {
        "id": "fixed_fraction_atr_stop",
        "params": {
            "mm_sizing": "fixed_fraction",
            "mm_stop": "atr",
            "mm_stop_val": "3",
        },
    },
]


def _load_spec(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_fixtures(spec: dict) -> dict[str, pd.DataFrame]:
    fixtures = {}
    for ticker, meta in spec["per_ticker"].items():
        fixture_path = ROOT / meta["fixture_csv"]
        df = pd.read_csv(fixture_path, index_col=0, parse_dates=True)
        fixtures[ticker] = df[~df.index.duplicated(keep="last")].sort_index()
    return fixtures


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
    notionals = [
        (float(trade["quantity"]) * float(trade["entry_price"])) / initial_capital * 100
        for trade in trades
    ]
    return round(mean(notionals), 2)


def _aggregate_metrics(per_ticker: dict[str, dict]) -> dict:
    return {
        "aggregate_score": round(mean(m["score"] for m in per_ticker.values()), 2),
        "avg_net_profit_pct": round(mean(m["net_profit_pct"] for m in per_ticker.values()), 2),
        "avg_max_drawdown_pct": round(mean(m["max_drawdown_pct"] for m in per_ticker.values()), 2),
        "avg_buy_hold_gap_pct": round(mean(m["buy_hold_gap_pct"] for m in per_ticker.values()), 2),
        "avg_total_trades": round(mean(m["total_trades"] for m in per_ticker.values()), 2),
        "avg_entry_notional_pct": round(mean(m["avg_entry_notional_pct"] for m in per_ticker.values()), 2),
    }


def _compare_variant(variant_metrics: dict, baseline_metrics: dict) -> dict:
    aggregate = variant_metrics["aggregate_metrics"]
    baseline = baseline_metrics["aggregate_metrics"]
    return {
        "aggregate_score_delta": round(
            aggregate["aggregate_score"] - baseline["aggregate_score"], 2
        ),
        "average_drawdown_delta": round(
            aggregate["avg_max_drawdown_pct"] - baseline["avg_max_drawdown_pct"], 2
        ),
        "average_trade_count_delta": round(
            aggregate["avg_total_trades"] - baseline["avg_total_trades"], 2
        ),
        "average_entry_notional_delta": round(
            aggregate["avg_entry_notional_pct"] - baseline["avg_entry_notional_pct"], 2
        ),
    }


def run_analysis(spec_path: Path = SPEC_PATH) -> dict:
    spec = _load_spec(spec_path)
    fixtures = _load_fixtures(spec)
    mock_download = _mock_download_factory(fixtures)
    strategy_key = spec["strategy_key"]

    variants = {}
    with flask_app.test_client() as client:
        flask_app.config["TESTING"] = True
        with patch("routes.chart.cached_download", side_effect=mock_download), patch(
            "routes.chart._resolve_cached_ticker_name",
            side_effect=lambda ticker: ticker,
        ):
            for variant in VARIANT_MATRIX:
                per_ticker = {}
                for ticker in spec["tickers"]:
                    resp = client.get(_chart_query(spec["chart_request"], ticker, variant["params"]))
                    data = resp.get_json()
                    if resp.status_code != 200:
                        raise RuntimeError(
                            f"{variant['id']} failed for {ticker}: {resp.status_code} {data}"
                        )
                    strategy_payload = data["strategies"][strategy_key]
                    summary = strategy_payload["summary"]
                    trades = strategy_payload["trades"]
                    initial_capital = float(summary.get("initial_capital", INITIAL_CAPITAL))
                    buy_hold_net_profit_pct = _buy_hold_net_profit_pct(
                        strategy_payload["buy_hold_equity_curve"]
                    )
                    net_profit_pct = round(float(summary["net_profit_pct"]), 2)
                    max_drawdown_pct = round(float(summary["max_drawdown_pct"]), 2)
                    per_ticker[ticker] = {
                        "net_profit_pct": net_profit_pct,
                        "max_drawdown_pct": max_drawdown_pct,
                        "buy_hold_net_profit_pct": buy_hold_net_profit_pct,
                        "buy_hold_gap_pct": round(net_profit_pct - buy_hold_net_profit_pct, 2),
                        "score": _score_from_metrics(
                            net_profit_pct,
                            max_drawdown_pct,
                            buy_hold_net_profit_pct,
                        ),
                        "total_trades": len(trades),
                        "avg_entry_notional_pct": _avg_entry_notional_pct(
                            trades,
                            initial_capital,
                        ),
                    }

                variants[variant["id"]] = {
                    "query_params": variant["params"],
                    "per_ticker": per_ticker,
                    "aggregate_metrics": _aggregate_metrics(per_ticker),
                }

    baseline_metrics = variants["baseline_none"]
    aggregate_rankings = sorted(
        [
            {
                "variant_id": variant_id,
                **payload["aggregate_metrics"],
            }
            for variant_id, payload in variants.items()
        ],
        key=lambda item: item["aggregate_score"],
        reverse=True,
    )

    worst_variant = aggregate_rankings[-1]
    worst_variant_id = worst_variant["variant_id"]
    worst_variant_payload = variants[worst_variant_id]
    worst_buy_hold_gap_worsened = sum(
        1
        for ticker in spec["tickers"]
        if worst_variant_payload["per_ticker"][ticker]["buy_hold_gap_pct"]
        < baseline_metrics["per_ticker"][ticker]["buy_hold_gap_pct"]
    )

    highest_nonbaseline_trade_variant = max(
        (item for item in aggregate_rankings if item["variant_id"] != "baseline_none"),
        key=lambda item: item["avg_total_trades"],
    )

    underperformance_findings = {
        "baseline_variant": "baseline_none",
        "vol_sizing": {
            variant_id: _compare_variant(variants[variant_id], baseline_metrics)
            for variant_id in ("vol_trade", "vol_monthly", "vol_capped")
        },
        "fixed_fraction": {
            variant_id: _compare_variant(variants[variant_id], baseline_metrics)
            for variant_id in (
                "fixed_fraction_trade",
                "fixed_fraction_monthly",
                "fixed_fraction_atr_stop",
            )
        },
        "other_churn_knobs": {
            "worst_variant_by_aggregate_score": worst_variant_id,
            "worst_variant_buy_hold_gap_worsened_ticker_count": worst_buy_hold_gap_worsened,
            "highest_nonbaseline_trade_count_variant": highest_nonbaseline_trade_variant[
                "variant_id"
            ],
            "highest_nonbaseline_trade_count": round(
                highest_nonbaseline_trade_variant["avg_total_trades"], 2
            ),
        },
    }

    phase4_implications = [
        "Favor layered entries/exits so the strategy can stay invested through strong trends while reducing abrupt all-in timing risk.",
        "Preserve capital deployment on strong trends instead of shrinking exposure just because realized volatility rises on the basket winners.",
        "Avoid tiny risk-budget sizing that collapses exposure on high-volatility winners and widens the buy-and-hold gap.",
    ]

    return {
        "variants": variants,
        "aggregate_rankings": aggregate_rankings,
        "underperformance_findings": underperformance_findings,
        "phase4_implications": phase4_implications,
    }


def render_markdown(results: dict) -> str:
    baseline = results["variants"]["baseline_none"]["aggregate_metrics"]
    vol_ids = ("vol_trade", "vol_monthly", "vol_capped")
    fixed_ids = (
        "fixed_fraction_trade",
        "fixed_fraction_monthly",
        "fixed_fraction_atr_stop",
    )
    worst_variant = results["underperformance_findings"]["other_churn_knobs"][
        "worst_variant_by_aggregate_score"
    ]
    worsened_count = results["underperformance_findings"]["other_churn_knobs"][
        "worst_variant_buy_hold_gap_worsened_ticker_count"
    ]
    highest_trade_variant = results["underperformance_findings"]["other_churn_knobs"][
        "highest_nonbaseline_trade_count_variant"
    ]
    highest_trade_count = results["underperformance_findings"]["other_churn_knobs"][
        "highest_nonbaseline_trade_count"
    ]

    lines = [
        "# Focus Basket Diagnostics",
        "",
        "## Basket Scorecard",
        "",
        "| Variant | Aggregate Score | Avg Net Profit % | Avg Max Drawdown % | Avg Buy-Hold Gap % | Avg Trades | Avg Entry Notional % |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in results["aggregate_rankings"]:
        lines.append(
            "| {variant_id} | {aggregate_score:.2f} | {avg_net_profit_pct:.2f} | "
            "{avg_max_drawdown_pct:.2f} | {avg_buy_hold_gap_pct:.2f} | "
            "{avg_total_trades:.2f} | {avg_entry_notional_pct:.2f} |".format(**item)
        )

    lines.extend(
        [
            "",
            "## Why Vol Sizing Underperformed",
            "",
            f"Baseline `baseline_none` aggregate score: `{baseline['aggregate_score']:.2f}`.",
            "",
        ]
    )
    for variant_id in vol_ids:
        delta = results["underperformance_findings"]["vol_sizing"][variant_id]
        lines.append(
            f"- `{variant_id}` score delta `{delta['aggregate_score_delta']:+.2f}`, "
            f"drawdown delta `{delta['average_drawdown_delta']:+.2f}`, "
            f"trade-count delta `{delta['average_trade_count_delta']:+.2f}`, "
            f"entry-notional delta `{delta['average_entry_notional_delta']:+.2f}` versus `baseline_none`."
        )

    lines.extend(
        [
            "",
            "## Why Fixed Fraction Underperformed",
            "",
        ]
    )
    for variant_id in fixed_ids:
        delta = results["underperformance_findings"]["fixed_fraction"][variant_id]
        lines.append(
            f"- `{variant_id}` score delta `{delta['aggregate_score_delta']:+.2f}`, "
            f"drawdown delta `{delta['average_drawdown_delta']:+.2f}`, "
            f"trade-count delta `{delta['average_trade_count_delta']:+.2f}`, "
            f"entry-notional delta `{delta['average_entry_notional_delta']:+.2f}` versus `baseline_none`."
        )

    lines.extend(
        [
            "",
            "## Other Knobs That Increased Churn",
            "",
            f"- Worst variant by aggregate_score: `{worst_variant}`.",
            f"- `{worst_variant}` worsened `buy_hold_gap_pct` on `{worsened_count}` of `7` tickers.",
            f"- Highest non-baseline average trade count came from `{highest_trade_variant}` at `{highest_trade_count:.2f}` trades per ticker, which shows the alternative knobs did not meaningfully reduce churn while still shrinking exposure.",
            "",
            "## Implications For Phase 4",
            "",
        ]
    )
    for implication in results["phase4_implications"]:
        lines.append(f"- {implication}")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=SPEC_PATH, help="Focus-basket spec JSON")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_JSON_OUT,
        help="Where to write the diagnostics JSON artifact",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=DEFAULT_MD_OUT,
        help="Where to write the diagnostics Markdown report",
    )
    args = parser.parse_args()

    results = run_analysis(args.spec)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(render_markdown(results), encoding="utf-8")

    if not args.output_json and not args.output_md:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
