#!/usr/bin/env python3
"""Run the canonical v1.19 macro-aware overlay matrix."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TRIEDINGVIEW_USER_DATA_DIR", tempfile.mkdtemp())

from lib.data_fetching import _fetch_treasury_yield_history, cached_download  # noqa: E402
from lib.macro_regime import MacroRegimeConfig  # noqa: E402
from lib.portfolio_backtesting import backtest_portfolio, backtest_portfolio_macro_overlay  # noqa: E402
from lib.portfolio_research import (  # noqa: E402
    DEFAULT_MACRO_OVERLAY_ALLOCATOR_POLICIES,
    DEFAULT_MACRO_OVERLAY_CONFIGS,
    DEFAULT_MACRO_OVERLAY_STRATEGIES,
    RESEARCH_BASKETS,
    RESEARCH_WINDOWS,
    V18_BEST_PAIR,
    macro_overlay_matrix_catalog,
)
from lib.ribbon_signals import compute_confirmed_ribbon_direction  # noqa: E402
from lib.settings import DAILY_WARMUP_DAYS  # noqa: E402
from lib.technical_indicators import compute_cci_hysteresis, compute_corpus_trend_signal  # noqa: E402

DEFAULT_JSON_OUT = (
    ROOT
    / ".planning"
    / "phases"
    / "64-run-macro-aware-overlay-matrix"
    / "macro-overlay-matrix-results.json"
)
DEFAULT_MD_OUT = (
    ROOT
    / ".planning"
    / "phases"
    / "64-run-macro-aware-overlay-matrix"
    / "macro-overlay-matrix-results.md"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategies", default=",".join(DEFAULT_MACRO_OVERLAY_STRATEGIES))
    parser.add_argument("--allocator-policies", default=",".join(DEFAULT_MACRO_OVERLAY_ALLOCATOR_POLICIES))
    parser.add_argument("--configs", default=",".join(item["id"] for item in DEFAULT_MACRO_OVERLAY_CONFIGS))
    parser.add_argument("--baskets", default=",".join(RESEARCH_BASKETS.keys()))
    parser.add_argument("--windows", default=",".join(RESEARCH_WINDOWS.keys()))
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON_OUT)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_MD_OUT)
    return parser.parse_args()


def _compute_strategy_direction(strategy: str, ticker: str, df: pd.DataFrame) -> pd.Series:
    if strategy == "ribbon":
        return compute_confirmed_ribbon_direction(ticker, df)
    if strategy == "corpus_trend":
        _entry_upper, _exit_lower, _atr, _stop_line, direction = compute_corpus_trend_signal(df)
        return direction
    if strategy == "cci_hysteresis":
        _cci, direction = compute_cci_hysteresis(df)
        return direction
    raise ValueError(f"Unsupported strategy '{strategy}'")


def _curve_max_drawdown_pct(curve: list[dict]) -> float:
    peak = None
    max_drawdown = 0.0
    for point in curve:
        value = float(point["value"])
        if peak is None or value > peak:
            peak = value
        if not peak:
            continue
        drawdown = ((peak - value) / peak) * 100.0
        max_drawdown = max(max_drawdown, drawdown)
    return round(max_drawdown, 2)


def _comparison_from_result(result) -> dict:
    strategy_end = float(result.portfolio_equity_curve[-1]["value"]) if result.portfolio_equity_curve else 10000.0
    buy_hold_end = float(result.portfolio_buy_hold_curve[-1]["value"]) if result.portfolio_buy_hold_curve else 10000.0
    initial_capital = float(result.portfolio_summary.get("initial_capital", 10000.0))
    strategy_return_pct = float(result.portfolio_summary.get("net_profit_pct", 0.0))
    buy_hold_return_pct = ((buy_hold_end / initial_capital) - 1.0) * 100.0 if initial_capital else 0.0
    return {
        "strategy_ending_equity": round(strategy_end, 2),
        "buy_hold_ending_equity": round(buy_hold_end, 2),
        "strategy_return_pct": round(strategy_return_pct, 2),
        "buy_hold_return_pct": round(buy_hold_return_pct, 2),
        "return_gap_pct": round(strategy_return_pct - buy_hold_return_pct, 2),
        "buy_hold_max_drawdown_pct": _curve_max_drawdown_pct(result.portfolio_buy_hold_curve),
        "strategy_max_drawdown_pct": float(result.portfolio_summary.get("max_drawdown_pct", 0.0)),
    }


def _warmup_start(start: str) -> str:
    dt = pd.Timestamp(start)
    return (dt - pd.Timedelta(days=DAILY_WARMUP_DAYS)).strftime("%Y-%m-%d")


def _load_visible_data(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    warmup = _warmup_start(start)
    visible: dict[str, pd.DataFrame] = {}
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) + pd.Timedelta(days=1)
    for ticker in tickers:
        df = cached_download(ticker, start=warmup, end=end, interval="1d", progress=False, threads=False)
        if df is None or df.empty:
            continue
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        if df.index.duplicated().any():
            df = df[~df.index.duplicated(keep="last")]
        df = df.sort_index()
        visible_df = df.loc[(df.index >= start_ts) & (df.index < end_ts)]
        if not visible_df.empty:
            visible[ticker] = visible_df
    return visible


def _load_strategy_directions(
    strategy: str,
    ticker_data: dict[str, pd.DataFrame],
) -> dict[str, pd.Series]:
    directions: dict[str, pd.Series] = {}
    for ticker, df in ticker_data.items():
        try:
            directions[ticker] = _compute_strategy_direction(strategy, ticker, df)
        except Exception:
            continue
    return directions


def _aggregate_results(results: list[dict]) -> list[dict]:
    if not results:
        return []
    frame = pd.DataFrame(results)
    rows: list[dict] = []
    for (strategy, allocator, config_id), group in frame.groupby(["strategy", "allocator_policy", "macro_config_id"]):
        rows.append(
            {
                "strategy": strategy,
                "allocator_policy": allocator,
                "macro_config_id": config_id,
                "runs": int(len(group.index)),
                "wins_vs_buy_hold": int((group["return_gap_pct"] > 0).sum()),
                "wins_vs_v18_best": int((group["vs_v18_return_gap_pct"] > 0).sum()),
                "median_return_gap_pct": round(float(group["return_gap_pct"].median()), 2),
                "median_drawdown_gap_pct": round(float(group["drawdown_gap_pct"].median()), 2),
                "median_vs_v18_return_gap_pct": round(float(group["vs_v18_return_gap_pct"].median()), 2),
                "median_upside_capture_pct": round(float(group["upside_capture_pct"].median()), 2),
                "avg_passive_core_pct": round(float(group["avg_passive_core_pct"].mean()), 2),
            }
        )
    rows.sort(key=lambda item: (item["median_return_gap_pct"], item["median_drawdown_gap_pct"]), reverse=True)
    return rows


def run_matrix(
    *,
    strategies: list[str],
    allocator_policies: list[str],
    config_ids: list[str],
    basket_keys: list[str],
    window_keys: list[str],
) -> dict:
    catalog = macro_overlay_matrix_catalog(
        strategies=strategies,
        allocator_policies=allocator_policies,
        config_ids=config_ids,
    )
    treasury_history = _fetch_treasury_yield_history("UST2Y", start="2011-01-01")
    config_lookup = {item["id"]: item for item in DEFAULT_MACRO_OVERLAY_CONFIGS}
    results: list[dict] = []
    for basket_key in basket_keys:
        tickers = list(RESEARCH_BASKETS[basket_key]["tickers"])
        for window_key in window_keys:
            window = RESEARCH_WINDOWS[window_key]
            visible_data = _load_visible_data(tickers, window["start"], window["end"])
            if not visible_data:
                continue
            direction_cache = {
                strategy: _load_strategy_directions(strategy, visible_data)
                for strategy in set([*strategies, V18_BEST_PAIR["strategy"]])
            }
            v18_baseline_result = backtest_portfolio(
                visible_data,
                direction_cache[V18_BEST_PAIR["strategy"]],
                allocator_policy=V18_BEST_PAIR["allocator_policy"],
            )
            v18_baseline = _comparison_from_result(v18_baseline_result)
            for strategy in strategies:
                directions = direction_cache[strategy]
                if not directions:
                    continue
                for allocator_policy in allocator_policies:
                    for config_id in config_ids:
                        config_spec = config_lookup[config_id]
                        macro_config = MacroRegimeConfig.from_dict(config_spec["macro_config"])
                        result = backtest_portfolio_macro_overlay(
                            visible_data,
                            directions,
                            allocator_policy=allocator_policy,
                            macro_config=macro_config,
                            treasury_history=treasury_history,
                        )
                        comparison = _comparison_from_result(result)
                        upside_capture = None
                        if comparison["buy_hold_return_pct"] > 0:
                            upside_capture = round(
                                (comparison["strategy_return_pct"] / comparison["buy_hold_return_pct"]) * 100.0,
                                2,
                            )
                        results.append(
                            {
                                "basket_key": basket_key,
                                "window_key": window_key,
                                "strategy": strategy,
                                "allocator_policy": allocator_policy,
                                "macro_config_id": config_id,
                                "macro_config_label": config_spec["label"],
                                "strategy_return_pct": comparison["strategy_return_pct"],
                                "buy_hold_return_pct": comparison["buy_hold_return_pct"],
                                "return_gap_pct": comparison["return_gap_pct"],
                                "drawdown_gap_pct": round(
                                    comparison["buy_hold_max_drawdown_pct"] - comparison["strategy_max_drawdown_pct"],
                                    2,
                                ),
                                "upside_capture_pct": upside_capture,
                                "avg_passive_core_pct": result.portfolio_diagnostics["avg_passive_core_pct"],
                                "risk_on_bars": result.portfolio_diagnostics["risk_on_bars"],
                                "risk_off_bars": result.portfolio_diagnostics["risk_off_bars"],
                                "vs_v18_return_gap_pct": round(
                                    comparison["strategy_return_pct"] - v18_baseline["strategy_return_pct"],
                                    2,
                                ),
                                "vs_v18_drawdown_gap_pct": round(
                                    v18_baseline["strategy_max_drawdown_pct"] - comparison["strategy_max_drawdown_pct"],
                                    2,
                                ),
                            }
                        )
    aggregate = _aggregate_results(results)
    return {
        "version": catalog["version"],
        "baseline": V18_BEST_PAIR,
        "matrix": {
            "strategies": strategies,
            "allocator_policies": allocator_policies,
            "config_ids": config_ids,
            "baskets": basket_keys,
            "windows": window_keys,
            "run_count": len(results),
        },
        "results": results,
        "aggregate": aggregate,
    }


def _render_markdown(report: dict) -> str:
    lines = [
        "# Macro Overlay Matrix Results",
        "",
        f"- Version: `{report['version']}`",
        f"- Runs: `{report['matrix']['run_count']}`",
        f"- Baseline pair: `{report['baseline']['strategy']} + {report['baseline']['allocator_policy']}`",
        "",
        "## Aggregate Results",
        "",
        "| Strategy | Allocator | Config | Runs | Wins vs B&H | Wins vs v1.18 | Median Return Gap % | Median Drawdown Gap % | Median vs v1.18 Return Gap % | Median Upside Capture % | Avg Passive Core % |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["aggregate"]:
        lines.append(
            f"| {row['strategy']} | {row['allocator_policy']} | {row['macro_config_id']} | {row['runs']} | "
            f"{row['wins_vs_buy_hold']} | {row['wins_vs_v18_best']} | {row['median_return_gap_pct']} | "
            f"{row['median_drawdown_gap_pct']} | {row['median_vs_v18_return_gap_pct']} | "
            f"{row['median_upside_capture_pct']} | {row['avg_passive_core_pct']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    report = run_matrix(
        strategies=[part.strip() for part in args.strategies.split(",") if part.strip()],
        allocator_policies=[part.strip() for part in args.allocator_policies.split(",") if part.strip()],
        config_ids=[part.strip() for part in args.configs.split(",") if part.strip()],
        basket_keys=[part.strip() for part in args.baskets.split(",") if part.strip()],
        window_keys=[part.strip() for part in args.windows.split(",") if part.strip()],
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.output_md.write_text(_render_markdown(report), encoding="utf-8")
    print(f"Wrote {args.output_json}")
    print(f"Wrote {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
