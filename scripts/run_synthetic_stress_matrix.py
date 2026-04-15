#!/usr/bin/env python3
"""Run the canonical v1.20 synthetic stress and upside-retention matrix."""

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
from lib.macro_regime import MacroRegimeConfig, build_macro_regime_frame  # noqa: E402
from lib.portfolio_backtesting import backtest_portfolio, backtest_portfolio_macro_overlay  # noqa: E402
from lib.portfolio_research import (  # noqa: E402
    DEFAULT_MACRO_OVERLAY_CONFIGS,
    DEFAULT_SYNTHETIC_STRESS_ALLOCATOR_POLICIES,
    DEFAULT_SYNTHETIC_STRESS_CONFIG_IDS,
    DEFAULT_SYNTHETIC_STRESS_STRATEGIES,
    DEFAULT_SYNTHETIC_STRESS_UPSIDE_WINDOWS,
    RESEARCH_BASKETS,
    RESEARCH_WINDOWS,
    SYNTHETIC_STRESS_MATRIX_VERSION,
    V18_BEST_PAIR,
    V19_BEST_NEAR_MISS,
    synthetic_stress_matrix_catalog,
)
from lib.ribbon_signals import compute_confirmed_ribbon_direction  # noqa: E402
from lib.settings import DAILY_WARMUP_DAYS  # noqa: E402
from lib.synthetic_stress import (  # noqa: E402
    DEFAULT_SYNTHETIC_STRESS_SCENARIOS,
    SyntheticStressScenario,
    apply_synthetic_stress,
    compute_drawdown_capture_metrics,
    curve_max_drawdown_pct,
    upside_capture_pct,
)
from lib.technical_indicators import compute_cci_hysteresis, compute_corpus_trend_signal  # noqa: E402

DEFAULT_JSON_OUT = (
    ROOT
    / ".planning"
    / "phases"
    / "69-run-synthetic-stress-and-upside-matrix"
    / "synthetic-stress-matrix-results.json"
)
DEFAULT_MD_OUT = (
    ROOT
    / ".planning"
    / "phases"
    / "69-run-synthetic-stress-and-upside-matrix"
    / "synthetic-stress-matrix-results.md"
)
DEFAULT_UPSIDE_JSON_OUT = (
    ROOT
    / ".planning"
    / "phases"
    / "69-run-synthetic-stress-and-upside-matrix"
    / "upside-retention-results.json"
)
DEFAULT_UPSIDE_MD_OUT = (
    ROOT
    / ".planning"
    / "phases"
    / "69-run-synthetic-stress-and-upside-matrix"
    / "upside-retention-results.md"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategies", default=",".join(DEFAULT_SYNTHETIC_STRESS_STRATEGIES))
    parser.add_argument("--allocator-policies", default=",".join(DEFAULT_SYNTHETIC_STRESS_ALLOCATOR_POLICIES))
    parser.add_argument("--configs", default=",".join(DEFAULT_SYNTHETIC_STRESS_CONFIG_IDS))
    parser.add_argument("--baskets", default=",".join(RESEARCH_BASKETS.keys()))
    parser.add_argument("--scenario-base-window", default="bull_recovery_2023_2025")
    parser.add_argument(
        "--scenarios",
        default=",".join(item.id for item in DEFAULT_SYNTHETIC_STRESS_SCENARIOS),
    )
    parser.add_argument("--upside-windows", default=",".join(DEFAULT_SYNTHETIC_STRESS_UPSIDE_WINDOWS))
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON_OUT)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_MD_OUT)
    parser.add_argument("--upside-output-json", type=Path, default=DEFAULT_UPSIDE_JSON_OUT)
    parser.add_argument("--upside-output-md", type=Path, default=DEFAULT_UPSIDE_MD_OUT)
    return parser.parse_args()


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


def _comparison_from_result(result) -> dict:
    strategy_end = float(result.portfolio_equity_curve[-1]["value"]) if result.portfolio_equity_curve else 10000.0
    buy_hold_end = float(result.portfolio_buy_hold_curve[-1]["value"]) if result.portfolio_buy_hold_curve else 10000.0
    initial_capital = float(result.portfolio_summary.get("initial_capital", 10000.0))
    strategy_return_pct = float(result.portfolio_summary.get("net_profit_pct", 0.0))
    buy_hold_return_pct = ((buy_hold_end / initial_capital) - 1.0) * 100.0 if initial_capital else 0.0
    buy_hold_max_drawdown_pct = curve_max_drawdown_pct(result.portfolio_buy_hold_curve)
    return {
        "strategy_ending_equity": round(strategy_end, 2),
        "buy_hold_ending_equity": round(buy_hold_end, 2),
        "strategy_return_pct": round(strategy_return_pct, 2),
        "buy_hold_return_pct": round(buy_hold_return_pct, 2),
        "return_gap_pct": round(strategy_return_pct - buy_hold_return_pct, 2),
        "buy_hold_max_drawdown_pct": buy_hold_max_drawdown_pct,
        "strategy_max_drawdown_pct": float(result.portfolio_summary.get("max_drawdown_pct", 0.0)),
    }


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


def _candidate_label(strategy: str, allocator_policy: str, config_id: str | None) -> str:
    if config_id:
        return f"{strategy} + {allocator_policy} + {config_id}"
    return f"{strategy} + {allocator_policy}"


def _aggregate_stress_results(results: list[dict]) -> list[dict]:
    if not results:
        return []
    frame = pd.DataFrame(results)
    rows: list[dict] = []
    for candidate, group in frame.groupby("candidate_label"):
        lag_series = group["protection_lag_bars"].dropna()
        rows.append(
            {
                "candidate_label": candidate,
                "runs": int(len(group.index)),
                "wins_vs_buy_hold": int((group["return_gap_pct"] > 0).sum()),
                "median_return_gap_pct": round(float(group["return_gap_pct"].median()), 2),
                "median_drawdown_saved_pct": round(float(group["drawdown_saved_pct"].median()), 2),
                "median_downside_capture_pct": round(float(group["downside_capture_pct"].median()), 2),
                "median_protected_share_of_modeled_drawdown_pct": round(
                    float(group["protected_share_of_modeled_drawdown_pct"].median()), 2
                ),
                "median_protection_lag_bars": round(float(lag_series.median()), 2) if not lag_series.empty else None,
                "avg_passive_core_pct": round(float(group["avg_passive_core_pct"].mean()), 2),
            }
        )
    rows.sort(
        key=lambda item: (
            item["median_drawdown_saved_pct"],
            -999 if item["median_protection_lag_bars"] is None else -item["median_protection_lag_bars"],
            item["median_return_gap_pct"],
        ),
        reverse=True,
    )
    return rows


def _aggregate_upside_results(results: list[dict]) -> list[dict]:
    if not results:
        return []
    frame = pd.DataFrame(results)
    rows: list[dict] = []
    for candidate, group in frame.groupby("candidate_label"):
        rows.append(
            {
                "candidate_label": candidate,
                "runs": int(len(group.index)),
                "wins_vs_buy_hold": int((group["return_gap_pct"] > 0).sum()),
                "median_return_gap_pct": round(float(group["return_gap_pct"].median()), 2),
                "median_upside_capture_pct": round(float(group["upside_capture_pct"].dropna().median()), 2),
                "avg_passive_core_pct": round(float(group["avg_passive_core_pct"].mean()), 2),
            }
        )
    rows.sort(
        key=lambda item: (item["median_upside_capture_pct"], item["median_return_gap_pct"]),
        reverse=True,
    )
    return rows


def _render_table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "_No rows_"
    header = "| " + " | ".join(label for label, _ in columns) + " |"
    divider = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(key, "")) for _, key in columns) + " |")
    return "\n".join([header, divider, *body])


def _write_outputs(payload: dict, json_path: Path, md_path: Path, *, title: str, body: str) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")


def run_matrix(
    *,
    strategies: list[str],
    allocator_policies: list[str],
    config_ids: list[str],
    basket_keys: list[str],
    scenario_base_window_key: str,
    scenario_ids: list[str],
    upside_window_keys: list[str],
) -> tuple[dict, dict]:
    catalog = synthetic_stress_matrix_catalog(
        strategies=strategies,
        allocator_policies=allocator_policies,
        config_ids=config_ids,
        scenario_ids=scenario_ids,
        upside_windows=upside_window_keys,
    )
    config_lookup = {item["id"]: item for item in DEFAULT_MACRO_OVERLAY_CONFIGS}
    scenario_lookup = {item.id: item for item in DEFAULT_SYNTHETIC_STRESS_SCENARIOS}
    treasury = _fetch_treasury_yield_history("UST2Y", start="2011-01-01")
    base_window = RESEARCH_WINDOWS[scenario_base_window_key]

    stress_rows: list[dict] = []
    upside_rows: list[dict] = []

    for basket_key in basket_keys:
        tickers = list(RESEARCH_BASKETS[basket_key]["tickers"])
        base_data = _load_visible_data(tickers, base_window["start"], base_window["end"])
        if not base_data:
            continue
        base_directions = {
            strategy: _load_strategy_directions(strategy, base_data)
            for strategy in sorted(set([*strategies, V18_BEST_PAIR["strategy"]]))
        }
        # Historical upside baselines on untouched data.
        for window_key in upside_window_keys:
            window = RESEARCH_WINDOWS[window_key]
            upside_data = _load_visible_data(tickers, window["start"], window["end"])
            if not upside_data:
                continue
            upside_direction_cache = {
                strategy: _load_strategy_directions(strategy, upside_data)
                for strategy in sorted(set([*strategies, V18_BEST_PAIR["strategy"]]))
            }
            tactical_baseline = backtest_portfolio(
                upside_data,
                upside_direction_cache[V18_BEST_PAIR["strategy"]],
                allocator_policy=V18_BEST_PAIR["allocator_policy"],
            )
            tactical_baseline_comp = _comparison_from_result(tactical_baseline)
            upside_rows.append(
                {
                    "basket_key": basket_key,
                    "window_key": window_key,
                    "candidate_label": "v18 tactical baseline",
                    "strategy": V18_BEST_PAIR["strategy"],
                    "allocator_policy": V18_BEST_PAIR["allocator_policy"],
                    "config_id": None,
                    "avg_passive_core_pct": 0.0,
                    **tactical_baseline_comp,
                    "upside_capture_pct": upside_capture_pct(
                        tactical_baseline_comp["strategy_return_pct"],
                        tactical_baseline_comp["buy_hold_return_pct"],
                    ),
                }
            )
            for strategy in strategies:
                directions = upside_direction_cache[strategy]
                if not directions:
                    continue
                for allocator_policy in allocator_policies:
                    for config_id in config_ids:
                        config_spec = config_lookup[config_id]
                        macro_config = MacroRegimeConfig.from_dict(config_spec["macro_config"])
                        result = backtest_portfolio_macro_overlay(
                            upside_data,
                            directions,
                            allocator_policy=allocator_policy,
                            macro_config=macro_config,
                            treasury_history=treasury,
                        )
                        comparison = _comparison_from_result(result)
                        upside_rows.append(
                            {
                                "basket_key": basket_key,
                                "window_key": window_key,
                                "candidate_label": _candidate_label(strategy, allocator_policy, config_id),
                                "strategy": strategy,
                                "allocator_policy": allocator_policy,
                                "config_id": config_id,
                                "avg_passive_core_pct": result.portfolio_diagnostics.get("avg_passive_core_pct", 0.0),
                                **comparison,
                                "upside_capture_pct": upside_capture_pct(
                                    comparison["strategy_return_pct"],
                                    comparison["buy_hold_return_pct"],
                                ),
                            }
                        )

        # Modeled synthetic stress scenarios.
        for scenario_id in scenario_ids:
            scenario = scenario_lookup[scenario_id]
            stressed_data, factor = apply_synthetic_stress(base_data, scenario)
            stressed_direction_cache = {
                strategy: _load_strategy_directions(strategy, stressed_data)
                for strategy in sorted(set([*strategies, V18_BEST_PAIR["strategy"]]))
            }
            tactical_baseline = backtest_portfolio(
                stressed_data,
                stressed_direction_cache[V18_BEST_PAIR["strategy"]],
                allocator_policy=V18_BEST_PAIR["allocator_policy"],
            )
            tactical_comp = _comparison_from_result(tactical_baseline)
            tactical_metrics = compute_drawdown_capture_metrics(
                strategy_max_drawdown_pct=tactical_comp["strategy_max_drawdown_pct"],
                buy_hold_max_drawdown_pct=tactical_comp["buy_hold_max_drawdown_pct"],
                factor=factor,
                regime_frame=None,
            )
            stress_rows.append(
                {
                    "basket_key": basket_key,
                    "scenario_id": scenario_id,
                    "candidate_label": "v18 tactical baseline",
                    "strategy": V18_BEST_PAIR["strategy"],
                    "allocator_policy": V18_BEST_PAIR["allocator_policy"],
                    "config_id": None,
                    "avg_passive_core_pct": 0.0,
                    **tactical_comp,
                    **tactical_metrics,
                }
            )
            for strategy in strategies:
                directions = stressed_direction_cache[strategy]
                if not directions:
                    continue
                for allocator_policy in allocator_policies:
                    for config_id in config_ids:
                        config_spec = config_lookup[config_id]
                        macro_config = MacroRegimeConfig.from_dict(config_spec["macro_config"])
                        result = backtest_portfolio_macro_overlay(
                            stressed_data,
                            directions,
                            allocator_policy=allocator_policy,
                            macro_config=macro_config,
                            treasury_history=treasury,
                        )
                        comparison = _comparison_from_result(result)
                        regime_frame = build_macro_regime_frame(
                            pd.to_datetime([point["time"] for point in result.portfolio_equity_curve], unit="s"),
                            directions,
                            ticker_data=stressed_data,
                            treasury_history=treasury,
                            config=macro_config,
                        )
                        metrics = compute_drawdown_capture_metrics(
                            strategy_max_drawdown_pct=comparison["strategy_max_drawdown_pct"],
                            buy_hold_max_drawdown_pct=comparison["buy_hold_max_drawdown_pct"],
                            factor=factor,
                            regime_frame=regime_frame,
                        )
                        stress_rows.append(
                            {
                                "basket_key": basket_key,
                                "scenario_id": scenario_id,
                                "candidate_label": _candidate_label(strategy, allocator_policy, config_id),
                                "strategy": strategy,
                                "allocator_policy": allocator_policy,
                                "config_id": config_id,
                                "avg_passive_core_pct": result.portfolio_diagnostics.get("avg_passive_core_pct", 0.0),
                                **comparison,
                                **metrics,
                            }
                        )

    stress_aggregate = _aggregate_stress_results(stress_rows)
    upside_aggregate = _aggregate_upside_results(upside_rows)

    stress_payload = {
        "version": SYNTHETIC_STRESS_MATRIX_VERSION,
        "baseline": V19_BEST_NEAR_MISS,
        "scenario_base_window": {
            "key": scenario_base_window_key,
            **base_window,
        },
        "matrix": catalog,
        "stress_results": stress_rows,
        "aggregate": stress_aggregate,
    }
    upside_payload = {
        "version": SYNTHETIC_STRESS_MATRIX_VERSION,
        "baseline": V19_BEST_NEAR_MISS,
        "matrix": catalog,
        "upside_results": upside_rows,
        "aggregate": upside_aggregate,
    }
    return stress_payload, upside_payload


def main() -> int:
    args = _parse_args()
    stress_payload, upside_payload = run_matrix(
        strategies=[part.strip() for part in args.strategies.split(",") if part.strip()],
        allocator_policies=[part.strip() for part in args.allocator_policies.split(",") if part.strip()],
        config_ids=[part.strip() for part in args.configs.split(",") if part.strip()],
        basket_keys=[part.strip() for part in args.baskets.split(",") if part.strip()],
        scenario_base_window_key=str(args.scenario_base_window).strip(),
        scenario_ids=[part.strip() for part in args.scenarios.split(",") if part.strip()],
        upside_window_keys=[part.strip() for part in args.upside_windows.split(",") if part.strip()],
    )
    stress_table = _render_table(
        stress_payload["aggregate"],
        [
            ("Candidate", "candidate_label"),
            ("Runs", "runs"),
            ("Wins vs BH", "wins_vs_buy_hold"),
            ("Median Gap %", "median_return_gap_pct"),
            ("Median DD Saved %", "median_drawdown_saved_pct"),
            ("Median Downside Capture %", "median_downside_capture_pct"),
            ("Median Protected %", "median_protected_share_of_modeled_drawdown_pct"),
            ("Median Lag", "median_protection_lag_bars"),
            ("Avg Core %", "avg_passive_core_pct"),
        ],
    )
    upside_table = _render_table(
        upside_payload["aggregate"],
        [
            ("Candidate", "candidate_label"),
            ("Runs", "runs"),
            ("Wins vs BH", "wins_vs_buy_hold"),
            ("Median Gap %", "median_return_gap_pct"),
            ("Median Upside Capture %", "median_upside_capture_pct"),
            ("Avg Core %", "avg_passive_core_pct"),
        ],
    )
    _write_outputs(
        stress_payload,
        args.output_json,
        args.output_md,
        title="Synthetic Stress Matrix Results",
        body=(
            f"- Base window: `{stress_payload['scenario_base_window']['key']}`\n"
            f"- Baseline: `{V19_BEST_NEAR_MISS['strategy']} + {V19_BEST_NEAR_MISS['allocator_policy']} + "
            f"{V19_BEST_NEAR_MISS['config_id']}`\n\n"
            "## Aggregate\n\n"
            f"{stress_table}"
        ),
    )
    _write_outputs(
        upside_payload,
        args.upside_output_json,
        args.upside_output_md,
        title="Upside Retention Results",
        body=(
            f"- Baseline: `{V19_BEST_NEAR_MISS['strategy']} + {V19_BEST_NEAR_MISS['allocator_policy']} + "
            f"{V19_BEST_NEAR_MISS['config_id']}`\n\n"
            "## Aggregate\n\n"
            f"{upside_table}"
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
