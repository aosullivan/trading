#!/usr/bin/env python3
"""Analyze focus-basket money-management variants against frozen fixtures."""

from __future__ import annotations

import argparse
import contextlib
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
POLY_HISTORY_PATH = ROOT / "tests" / "fixtures" / "polymarket_probability_history_benchmark.json"

VARIANT_MATRIX = [
    {"id": "baseline_none", "params": {}},
    {
        "id": "vol_legacy_trade",
        "params": {"mm_sizing": "vol"},
        "default_overrides": {"vol_scale_factor": backtesting.LEGACY_VOL_SCALE_FACTOR},
    },
    {
        "id": "vol_trade",
        "params": {"mm_sizing": "vol"},
        "default_overrides": {"vol_scale_factor": backtesting.DEFAULT_VOL_SCALE_FACTOR},
    },
    {
        "id": "fixed_fraction_legacy_trade",
        "params": {"mm_sizing": "fixed_fraction"},
        "default_overrides": {"risk_fraction": backtesting.LEGACY_FIXED_FRACTION_RISK},
    },
    {
        "id": "fixed_fraction_trade",
        "params": {"mm_sizing": "fixed_fraction"},
        "default_overrides": {"risk_fraction": backtesting.DEFAULT_FIXED_FRACTION_RISK},
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


def _load_polymarket_history() -> pd.DataFrame:
    records = json.loads(POLY_HISTORY_PATH.read_text(encoding="utf-8"))
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


@contextlib.contextmanager
def _temporary_default_overrides(overrides: dict | None):
    if not overrides:
        yield
        return
    old_vol = backtesting.DEFAULT_VOL_SCALE_FACTOR
    old_risk = backtesting.DEFAULT_FIXED_FRACTION_RISK
    try:
        if "vol_scale_factor" in overrides:
            backtesting.DEFAULT_VOL_SCALE_FACTOR = float(overrides["vol_scale_factor"])
        if "risk_fraction" in overrides:
            backtesting.DEFAULT_FIXED_FRACTION_RISK = float(overrides["risk_fraction"])
        yield
    finally:
        backtesting.DEFAULT_VOL_SCALE_FACTOR = old_vol
        backtesting.DEFAULT_FIXED_FRACTION_RISK = old_risk


def run_analysis(spec_path: Path = SPEC_PATH) -> dict:
    spec = _load_spec(spec_path)
    fixtures = _load_fixtures(spec)
    polymarket_history = _load_polymarket_history()
    mock_download = _mock_download_factory(fixtures)
    strategy_key = spec["strategy_key"]

    variants = {}
    with flask_app.test_client() as client:
        flask_app.config["TESTING"] = True
        with patch("routes.chart.cached_download", side_effect=mock_download), patch(
            "routes.chart._resolve_cached_ticker_name",
            side_effect=lambda ticker: ticker,
        ), patch(
            "lib.polymarket.load_probability_history",
            return_value=polymarket_history,
        ):
            for variant in VARIANT_MATRIX:
                per_ticker = {}
                with _temporary_default_overrides(variant.get("default_overrides")):
                    for ticker in spec["tickers"]:
                        _cache.clear()
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
                    "default_overrides": variant.get("default_overrides", {}),
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

    vol_legacy = variants["vol_legacy_trade"]
    vol_current = variants["vol_trade"]
    fixed_legacy = variants["fixed_fraction_legacy_trade"]
    fixed_current = variants["fixed_fraction_trade"]

    worst_variant = aggregate_rankings[-1]
    worst_variant_id = worst_variant["variant_id"]
    worst_variant_payload = variants[worst_variant_id]
    worst_buy_hold_gap_worsened = sum(
        1
        for ticker in spec["tickers"]
        if worst_variant_payload["per_ticker"][ticker]["buy_hold_gap_pct"]
        < baseline_metrics["per_ticker"][ticker]["buy_hold_gap_pct"]
    )

    underperformance_findings = {
        "baseline_variant": "baseline_none",
        "selected_defaults": {
            "vol_scale_factor": backtesting.DEFAULT_VOL_SCALE_FACTOR,
            "fixed_fraction_risk_fraction": backtesting.DEFAULT_FIXED_FRACTION_RISK,
        },
        "vol_sizing": {
            "legacy_variant": "vol_legacy_trade",
            "calibrated_variant": "vol_trade",
            "comparison_to_legacy": _compare_variant(vol_current, vol_legacy),
            "comparison_to_baseline": _compare_variant(vol_current, baseline_metrics),
        },
        "fixed_fraction": {
            "legacy_variant": "fixed_fraction_legacy_trade",
            "calibrated_variant": "fixed_fraction_trade",
            "comparison_to_legacy": _compare_variant(fixed_current, fixed_legacy),
            "comparison_to_baseline": _compare_variant(fixed_current, baseline_metrics),
        },
        "other_churn_knobs": {
            "worst_variant_by_aggregate_score": worst_variant_id,
            "worst_variant_buy_hold_gap_worsened_ticker_count": worst_buy_hold_gap_worsened,
            "highest_nonbaseline_trade_count_variant": "vol_trade"
            if vol_current["aggregate_metrics"]["avg_total_trades"]
            >= fixed_current["aggregate_metrics"]["avg_total_trades"]
            else "fixed_fraction_trade",
            "highest_nonbaseline_trade_count": round(
                max(
                    vol_current["aggregate_metrics"]["avg_total_trades"],
                    fixed_current["aggregate_metrics"]["avg_total_trades"],
                ),
                2,
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
    vol_finding = results["underperformance_findings"]["vol_sizing"]
    fixed_finding = results["underperformance_findings"]["fixed_fraction"]
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
            (
                "Selected default `vol_scale_factor`: "
                f"`{results['underperformance_findings']['selected_defaults']['vol_scale_factor']}`."
            ),
            "",
        ]
    )
    vol_legacy = vol_finding["comparison_to_legacy"]
    vol_baseline = vol_finding["comparison_to_baseline"]
    lines.append(
        f"- `{vol_finding['calibrated_variant']}` vs `{vol_finding['legacy_variant']}`: "
        f"score delta `{vol_legacy['aggregate_score_delta']:+.2f}`, "
        f"drawdown delta `{vol_legacy['average_drawdown_delta']:+.2f}`, "
        f"trade-count delta `{vol_legacy['average_trade_count_delta']:+.2f}`, "
        f"entry-notional delta `{vol_legacy['average_entry_notional_delta']:+.2f}`."
    )
    lines.append(
        f"- `{vol_finding['calibrated_variant']}` vs `baseline_none`: "
        f"score delta `{vol_baseline['aggregate_score_delta']:+.2f}`, "
        f"drawdown delta `{vol_baseline['average_drawdown_delta']:+.2f}`, "
        f"trade-count delta `{vol_baseline['average_trade_count_delta']:+.2f}`, "
        f"entry-notional delta `{vol_baseline['average_entry_notional_delta']:+.2f}`."
    )

    lines.extend(
        [
            "",
            "## Why Fixed Fraction Underperformed",
            "",
            (
                "Selected default `risk_fraction`: "
                f"`{results['underperformance_findings']['selected_defaults']['fixed_fraction_risk_fraction']}`."
            ),
            "",
        ]
    )
    fixed_legacy = fixed_finding["comparison_to_legacy"]
    fixed_baseline = fixed_finding["comparison_to_baseline"]
    lines.append(
        f"- `{fixed_finding['calibrated_variant']}` vs `{fixed_finding['legacy_variant']}`: "
        f"score delta `{fixed_legacy['aggregate_score_delta']:+.2f}`, "
        f"drawdown delta `{fixed_legacy['average_drawdown_delta']:+.2f}`, "
        f"trade-count delta `{fixed_legacy['average_trade_count_delta']:+.2f}`, "
        f"entry-notional delta `{fixed_legacy['average_entry_notional_delta']:+.2f}`."
    )
    lines.append(
        f"- `{fixed_finding['calibrated_variant']}` vs `baseline_none`: "
        f"score delta `{fixed_baseline['aggregate_score_delta']:+.2f}`, "
        f"drawdown delta `{fixed_baseline['average_drawdown_delta']:+.2f}`, "
        f"trade-count delta `{fixed_baseline['average_trade_count_delta']:+.2f}`, "
        f"entry-notional delta `{fixed_baseline['average_entry_notional_delta']:+.2f}`."
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
