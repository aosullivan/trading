from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.backtesting import backtest_ribbon_accumulation
from lib.data_fetching import cached_download, normalize_ticker
from lib.paths import get_user_data_path
from lib.settings import DAILY_WARMUP_DAYS
from lib.technical_indicators import compute_trend_ribbon
from lib.trend_optimizer import RIBBON_GRID
from lib.trend_ribbon_profile import (
    trend_ribbon_backtest_kwargs,
    trend_ribbon_signal_kwargs,
)


BENCHMARK_WINDOWS = [
    {
        "window_id": "bench_2024-10-01_2025-11-30",
        "start_date": "2024-10-01",
        "end_date": "2025-11-30",
    },
    {
        "window_id": "bench_2025-11-02_2026-04-03",
        "start_date": "2025-11-02",
        "end_date": "2026-04-03",
    },
    {
        "window_id": "bench_2022-02-07_2025-08-31",
        "start_date": "2022-02-07",
        "end_date": "2025-08-31",
    },
]

WALK_FORWARD_WINDOWS = [
    {"window_id": "wf_1y_2022-01-01_2022-12-31", "start_date": "2022-01-01", "end_date": "2022-12-31"},
    {"window_id": "wf_1y_2022-07-01_2023-06-30", "start_date": "2022-07-01", "end_date": "2023-06-30"},
    {"window_id": "wf_1y_2023-07-01_2024-06-30", "start_date": "2023-07-01", "end_date": "2024-06-30"},
    {"window_id": "wf_1y_2024-07-01_2025-06-30", "start_date": "2024-07-01", "end_date": "2025-06-30"},
    {"window_id": "wf_2y_2022-01-01_2023-12-31", "start_date": "2022-01-01", "end_date": "2023-12-31"},
    {"window_id": "wf_2y_2024-01-01_2026-04-03", "start_date": "2024-01-01", "end_date": "2026-04-03"},
]

SIGNAL_GRID = RIBBON_GRID

SIZING_GRID = {
    "daily_add_capital": [1000.0, 3000.0, 5000.0],
    "weekly_add_capital": [0.0, 3000.0, 6000.0, 9000.0],
    "max_capital": [30000.0, 60000.0, 120000.0],
    "daily_sell_fraction": [0.0, 0.02, 0.05, 0.1],
    "weekly_sell_fraction": [0.0, 0.25, 0.5, 0.75],
}


@dataclass(frozen=True)
class WindowSlice:
    window_id: str
    start_date: str
    end_date: str
    view_df: pd.DataFrame


@dataclass(frozen=True)
class SignalState:
    signal_params: dict[str, int | float]
    daily_direction: pd.Series
    weekly_direction: pd.Series


def _carry_neutral_direction(direction: pd.Series) -> pd.Series:
    return direction.replace(0, pd.NA).ffill().fillna(0).astype(int)


def _align_weekly_direction_to_daily(
    weekly_direction: pd.Series,
    daily_index: pd.Index,
) -> pd.Series:
    return weekly_direction.reindex(daily_index).ffill().bfill().fillna(0).astype(int)


def _prior_direction(
    direction: pd.Series,
    full_index: pd.Index,
    view_index: pd.Index,
) -> int | None:
    if len(view_index) == 0:
        return None
    first_visible_loc = full_index.get_indexer([view_index[0]])[0]
    if first_visible_loc <= 0:
        return None
    prior = direction.iloc[first_visible_loc - 1]
    return None if pd.isna(prior) else int(prior)


def _max_drawdown_pct(equity_curve: list[dict[str, float]]) -> float:
    peak = None
    max_drawdown = 0.0
    for point in equity_curve:
        value = float(point["value"])
        peak = value if peak is None else max(peak, value)
        drawdown_pct = ((peak - value) / peak) * 100 if peak else 0.0
        max_drawdown = max(max_drawdown, drawdown_pct)
    return round(max_drawdown, 2)


def _build_signal_profiles() -> list[dict[str, int | float]]:
    keys = list(SIGNAL_GRID)
    profiles = []
    for values in itertools.product(*(SIGNAL_GRID[key] for key in keys)):
        params = dict(zip(keys, values))
        if params["slow_period"] <= params["fast_period"]:
            continue
        if params["expand_threshold"] < params["collapse_threshold"]:
            continue
        profiles.append(params)
    return profiles


def _build_sizing_profiles() -> list[dict[str, float]]:
    keys = list(SIZING_GRID)
    profiles = []
    for values in itertools.product(*(SIZING_GRID[key] for key in keys)):
        params = dict(zip(keys, values))
        min_capital = 10000.0 + params["daily_add_capital"] + params["weekly_add_capital"]
        if params["max_capital"] < min_capital:
            continue
        profiles.append(params)
    return profiles


def _load_daily_frame(ticker: str, windows: list[dict[str, str]]) -> pd.DataFrame:
    start_date = min(window["start_date"] for window in windows)
    warmup_start = (
        pd.Timestamp(start_date).normalize() - pd.Timedelta(days=DAILY_WARMUP_DAYS)
    ).date().isoformat()
    end_date = max(window["end_date"] for window in windows)
    df = cached_download(
        normalize_ticker(ticker),
        start=warmup_start,
        end=end_date,
        interval="1d",
        progress=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[~df.index.duplicated(keep="last")].sort_index()


def _build_weekly_frame(daily_df: pd.DataFrame) -> pd.DataFrame:
    weekly_df = (
        daily_df.sort_index()
        .resample("W-FRI")
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
    )
    return weekly_df.dropna(subset=["Open", "High", "Low", "Close"])


def _build_window_slices(
    daily_df: pd.DataFrame,
    windows: list[dict[str, str]],
) -> dict[str, WindowSlice]:
    slices = {}
    for window in windows:
        start_ts = pd.Timestamp(window["start_date"]).normalize()
        end_ts = pd.Timestamp(window["end_date"]).normalize()
        view_df = daily_df.loc[(daily_df.index >= start_ts) & (daily_df.index <= end_ts)].copy()
        slices[window["window_id"]] = WindowSlice(
            window_id=window["window_id"],
            start_date=window["start_date"],
            end_date=window["end_date"],
            view_df=view_df,
        )
    return slices


def _compute_signal_state(
    daily_df: pd.DataFrame,
    weekly_df: pd.DataFrame,
    signal_params: dict[str, int | float],
) -> SignalState:
    _center, _upper, _lower, _strength, daily_direction = compute_trend_ribbon(
        daily_df,
        **signal_params,
    )
    _w_center, _w_upper, _w_lower, _w_strength, weekly_direction = compute_trend_ribbon(
        weekly_df,
        **signal_params,
    )
    return SignalState(
        signal_params=dict(signal_params),
        daily_direction=_carry_neutral_direction(daily_direction),
        weekly_direction=_align_weekly_direction_to_daily(
            _carry_neutral_direction(weekly_direction),
            daily_df.index,
        ),
    )


def _evaluate_window(
    daily_df: pd.DataFrame,
    window_slice: WindowSlice,
    signal_state: SignalState,
    sizing_params: dict[str, float],
) -> dict[str, float | str]:
    prior_daily_direction = _prior_direction(
        signal_state.daily_direction,
        daily_df.index,
        window_slice.view_df.index,
    )
    prior_weekly_direction = _prior_direction(
        signal_state.weekly_direction,
        daily_df.index,
        window_slice.view_df.index,
    )
    _trades, summary, _equity_curve, hold_equity_curve = backtest_ribbon_accumulation(
        window_slice.view_df,
        signal_state.daily_direction.loc[window_slice.view_df.index],
        signal_state.weekly_direction.loc[window_slice.view_df.index],
        prior_daily_direction=prior_daily_direction,
        prior_weekly_direction=prior_weekly_direction,
        **sizing_params,
    )
    hodl_ending_equity = (
        float(hold_equity_curve[-1]["value"]) if hold_equity_curve else float(summary["initial_capital"])
    )
    ending_equity_ratio = (
        float(summary["ending_equity"]) / hodl_ending_equity if hodl_ending_equity else 0.0
    )
    return {
        "window_id": window_slice.window_id,
        "start_date": window_slice.start_date,
        "end_date": window_slice.end_date,
        "strategy_ending_equity": float(summary["ending_equity"]),
        "hodl_ending_equity": round(hodl_ending_equity, 2),
        "ending_equity_ratio": round(ending_equity_ratio, 6),
        "strategy_max_drawdown_pct": float(summary["max_drawdown_pct"]),
        "hodl_max_drawdown_pct": _max_drawdown_pct(hold_equity_curve),
        "total_trades": int(summary["total_trades"]),
        "open_trades": int(summary["open_trades"]),
    }


def _benchmark_margins(metrics_by_window: dict[str, dict[str, float | str]]) -> dict[str, float]:
    bench_1 = metrics_by_window["bench_2024-10-01_2025-11-30"]
    bench_2 = metrics_by_window["bench_2025-11-02_2026-04-03"]
    bench_3 = metrics_by_window["bench_2022-02-07_2025-08-31"]
    return {
        "bench_2024_ratio_gt_1": float(bench_1["ending_equity_ratio"]) - 1.0,
        "bench_2025_ratio_ge_0.98": float(bench_2["ending_equity_ratio"]) - 0.98,
        "bench_2025_dd_le_42": (42.0 - float(bench_2["strategy_max_drawdown_pct"])) / 100.0,
        "bench_2022_ratio_gt_1": float(bench_3["ending_equity_ratio"]) - 1.0,
        "bench_2022_dd_lt_hodl": (
            float(bench_3["hodl_max_drawdown_pct"]) - float(bench_3["strategy_max_drawdown_pct"])
        )
        / 100.0,
    }


def _validation_score(metrics_by_window: dict[str, dict[str, float | str]]) -> float:
    walk_forward_metrics = [
        metrics
        for window_id, metrics in metrics_by_window.items()
        if window_id.startswith("wf_")
    ]
    if not walk_forward_metrics:
        return 0.0
    ratio_edge = sum(
        float(metrics["ending_equity_ratio"]) - 1.0 for metrics in walk_forward_metrics
    ) / len(walk_forward_metrics)
    drawdown_edge = sum(
        (
            float(metrics["hodl_max_drawdown_pct"])
            - float(metrics["strategy_max_drawdown_pct"])
        )
        / 100.0
        for metrics in walk_forward_metrics
    ) / len(walk_forward_metrics)
    return round(ratio_edge + 0.5 * drawdown_edge, 8)


def _passes_benchmark_rules(metrics_by_window: dict[str, dict[str, float | str]]) -> bool:
    bench_1 = metrics_by_window["bench_2024-10-01_2025-11-30"]
    bench_2 = metrics_by_window["bench_2025-11-02_2026-04-03"]
    bench_3 = metrics_by_window["bench_2022-02-07_2025-08-31"]
    return (
        float(bench_1["ending_equity_ratio"]) > 1.0
        and float(bench_2["strategy_max_drawdown_pct"]) <= 42.0
        and float(bench_2["ending_equity_ratio"]) >= 0.98
        and float(bench_3["ending_equity_ratio"]) > 1.0
        and float(bench_3["strategy_max_drawdown_pct"])
        < float(bench_3["hodl_max_drawdown_pct"])
    )


def _evaluate_profile(
    daily_df: pd.DataFrame,
    window_slices: dict[str, WindowSlice],
    signal_state: SignalState,
    sizing_params: dict[str, float],
) -> dict[str, object]:
    metrics_by_window = {
        window_id: _evaluate_window(daily_df, window_slice, signal_state, sizing_params)
        for window_id, window_slice in window_slices.items()
    }
    margins = _benchmark_margins(metrics_by_window)
    min_benchmark_margin = min(margins.values())
    return {
        "signal": dict(signal_state.signal_params),
        "sizing": dict(sizing_params),
        "metrics_by_window": metrics_by_window,
        "benchmark_margins": {
            key: round(value, 8) for key, value in margins.items()
        },
        "min_benchmark_margin": round(min_benchmark_margin, 8),
        "validation_score": _validation_score(metrics_by_window),
        "passes_benchmarks": _passes_benchmark_rules(metrics_by_window),
    }


def _rank_profiles(profile_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        profile_rows,
        key=lambda row: (
            bool(row["passes_benchmarks"]),
            float(row["min_benchmark_margin"]),
            float(row["validation_score"]),
            float(
                row["metrics_by_window"]["bench_2022-02-07_2025-08-31"][
                    "ending_equity_ratio"
                ]
            ),
        ),
        reverse=True,
    )


def _summarize_pass_rows(rows: list[dict[str, object]], limit: int = 20) -> list[dict[str, object]]:
    return [
        {
            "signal": row["signal"],
            "sizing": row["sizing"],
            "min_benchmark_margin": row["min_benchmark_margin"],
            "validation_score": row["validation_score"],
            "benchmark_margins": row["benchmark_margins"],
            "benchmarks": {
                window_id: row["metrics_by_window"][window_id]
                for window_id in [window["window_id"] for window in BENCHMARK_WINDOWS]
            },
        }
        for row in rows[:limit]
    ]


def _next_structural_change(best_row: dict[str, object]) -> str:
    margins = best_row["benchmark_margins"]
    worst_margin_name = min(margins, key=margins.get)
    if worst_margin_name == "bench_2022_ratio_gt_1":
        return (
            "Add a core-sleeve de-risk/re-entry rule. The tested space only sells the "
            "tactical sleeve on bearish flips, so long-window underperformance versus "
            "HODL remains after max-drawdown is already lower than HODL."
        )
    if worst_margin_name == "bench_2025_dd_le_42":
        return (
            "Add a drawdown-aware exposure brake, such as progressively trimming the "
            "core sleeve on sustained weekly bearish states or an ATR stop on total "
            "position value."
        )
    return (
        "Expand the signal state machine, for example by requiring a stronger weekly "
        "confirmation before scale-ins and a separate neutral-to-bull re-entry trigger "
        "after deep collapses."
    )


def run_search(
    ticker: str,
    *,
    signal_shortlist_size: int,
    progress_every: int,
) -> dict[str, object]:
    all_windows = BENCHMARK_WINDOWS + WALK_FORWARD_WINDOWS
    daily_df = _load_daily_frame(ticker, all_windows)
    weekly_df = _build_weekly_frame(daily_df)
    window_slices = _build_window_slices(daily_df, all_windows)
    signal_profiles = _build_signal_profiles()
    sizing_profiles = _build_sizing_profiles()
    baseline_sizing = trend_ribbon_backtest_kwargs(ticker)
    baseline_signal = trend_ribbon_signal_kwargs(ticker)

    stage_1_rows = []
    for idx, signal_params in enumerate(signal_profiles, start=1):
        signal_state = _compute_signal_state(daily_df, weekly_df, signal_params)
        stage_1_rows.append(
            _evaluate_profile(
                daily_df,
                window_slices,
                signal_state,
                baseline_sizing,
            )
        )
        if progress_every > 0 and idx % progress_every == 0:
            best = _rank_profiles(stage_1_rows)[0]
            print(
                "stage=signal "
                f"evaluated={idx}/{len(signal_profiles)} "
                f"best_margin={best['min_benchmark_margin']:.6f} "
                f"best_validation={best['validation_score']:.6f} "
                f"signal={best['signal']}",
                flush=True,
            )

    ranked_signals = _rank_profiles(stage_1_rows)
    shortlisted_signals = ranked_signals[:signal_shortlist_size]

    stage_2_rows = []
    evaluated_profiles = 0
    for signal_row in shortlisted_signals:
        signal_state = _compute_signal_state(
            daily_df,
            weekly_df,
            signal_row["signal"],
        )
        for sizing_params in sizing_profiles:
            stage_2_rows.append(
                _evaluate_profile(
                    daily_df,
                    window_slices,
                    signal_state,
                    sizing_params,
                )
            )
            evaluated_profiles += 1
            if progress_every > 0 and evaluated_profiles % progress_every == 0:
                best = _rank_profiles(stage_2_rows)[0]
                print(
                    "stage=sizing "
                    f"evaluated={evaluated_profiles}/"
                    f"{len(shortlisted_signals) * len(sizing_profiles)} "
                    f"best_margin={best['min_benchmark_margin']:.6f} "
                    f"best_validation={best['validation_score']:.6f} "
                    f"signal={best['signal']} sizing={best['sizing']}",
                    flush=True,
                )

    ranked_profiles = _rank_profiles(stage_2_rows)
    passing_profiles = [row for row in ranked_profiles if row["passes_benchmarks"]]
    best_row = ranked_profiles[0] if ranked_profiles else ranked_signals[0]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "ticker": ticker,
        "interval": "1d",
        "data_coverage": {
            "daily_start_date": str(daily_df.index.min().date()) if not daily_df.empty else None,
            "daily_end_date": str(daily_df.index.max().date()) if not daily_df.empty else None,
            "daily_rows": int(len(daily_df)),
        },
        "benchmark_windows": BENCHMARK_WINDOWS,
        "walk_forward_windows": WALK_FORWARD_WINDOWS,
        "search_space": {
            "signal_grid": SIGNAL_GRID,
            "sizing_grid": SIZING_GRID,
            "signal_profile_count": len(signal_profiles),
            "sizing_profile_count": len(sizing_profiles),
            "signal_shortlist_size": signal_shortlist_size,
            "stage_1_profile_evals": len(signal_profiles),
            "stage_2_profile_evals": len(stage_2_rows),
        },
        "deployed_baseline_profile": {
            "signal": baseline_signal,
            "sizing": baseline_sizing,
        },
        "passing_profile_count": len(passing_profiles),
        "top_passing_profiles": _summarize_pass_rows(passing_profiles, limit=20),
        "top_tested_profiles": _summarize_pass_rows(ranked_profiles, limit=20),
        "best_profile": _summarize_pass_rows([best_row], limit=1)[0],
        "next_structural_change": None
        if passing_profiles
        else _next_structural_change(best_row),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a staged Trend-Driven benchmark search on BTC-USD daily windows.",
    )
    parser.add_argument("--ticker", default="BTC-USD")
    parser.add_argument(
        "--signal-shortlist-size",
        type=int,
        default=16,
        help="How many stage-1 signal profiles to carry into the sizing search.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=250,
        help="Print a progress line every N evaluations per stage; set 0 to silence.",
    )
    parser.add_argument(
        "--output-path",
        default=get_user_data_path(
            "optimizer",
            "trend_ribbon_benchmark_search.json",
        ),
    )
    return parser


def main():
    args = build_parser().parse_args()
    result = run_search(
        args.ticker,
        signal_shortlist_size=args.signal_shortlist_size,
        progress_every=args.progress_every,
    )
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
