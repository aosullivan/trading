#!/usr/bin/env python3
"""Empirically test macro regime theses against forward basket conditions."""

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

from lib.data_fetching import cached_download, _fetch_treasury_yield_history  # noqa: E402
from lib.macro_regime import (  # noqa: E402
    build_close_frame,
    build_rate_feature_frame,
    classify_rate_environment,
    compute_forward_equal_weight_path,
    compute_path_metrics,
    election_cycle_phase,
    month_end_observation_dates,
)
from lib.portfolio_research import RESEARCH_BASKETS  # noqa: E402

DEFAULT_JSON_OUT = (
    ROOT
    / ".planning"
    / "phases"
    / "62-build-empirical-macro-regime-research-harness"
    / "macro-regime-hypotheses.json"
)
DEFAULT_MD_OUT = (
    ROOT
    / ".planning"
    / "phases"
    / "62-build-empirical-macro-regime-research-harness"
    / "macro-regime-hypotheses.md"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2012-01-01")
    parser.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    parser.add_argument("--forward-days", type=int, default=126)
    parser.add_argument("--rate-lookbacks", default="21,63,126")
    parser.add_argument("--baskets", default=",".join(RESEARCH_BASKETS.keys()))
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON_OUT)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_MD_OUT)
    return parser.parse_args()


def _load_ticker_data(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    ticker_data: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        df = cached_download(ticker, start=start, end=end, interval="1d", progress=False, threads=False)
        if df is None or df.empty:
            continue
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        if df.index.duplicated().any():
            df = df[~df.index.duplicated(keep="last")]
        ticker_data[ticker] = df.sort_index()
    return ticker_data


def _group_summary(df: pd.DataFrame, key: str) -> list[dict]:
    if df.empty:
        return []
    rows: list[dict] = []
    for group_key, group in df.groupby(key, dropna=False):
        group = group.sort_values("date")
        rows.append(
            {
                "bucket": str(group_key),
                "observations": int(len(group.index)),
                "avg_forward_return_pct": round(float(group["forward_return_pct"].mean()), 2),
                "median_forward_return_pct": round(float(group["forward_return_pct"].median()), 2),
                "avg_max_drawdown_pct": round(float(group["max_drawdown_pct"].mean()), 2),
                "positive_rate_pct": round(float((group["forward_return_pct"] > 0).mean() * 100.0), 2),
            }
        )
    rows.sort(key=lambda item: item["bucket"])
    return rows


def _thesis_readout(df: pd.DataFrame, *, rate_col: str, election_col: str) -> dict:
    rate_falling = df[df[rate_col].isin(["cuts_fast", "cuts_priced"])]
    rate_rising = df[df[rate_col].isin(["hikes_or_no_cuts", "hikes_fast"])]
    election_good = df[df[election_col].isin(["pre_election", "election"])]
    election_other = df[df[election_col] == "other"]

    def _delta(left: pd.DataFrame, right: pd.DataFrame, column: str) -> float | None:
        if left.empty or right.empty:
            return None
        return round(float(left[column].mean() - right[column].mean()), 2)

    rate_return_delta = _delta(rate_falling, rate_rising, "forward_return_pct")
    rate_drawdown_delta = _delta(rate_rising, rate_falling, "max_drawdown_pct")
    election_return_delta = _delta(election_good, election_other, "forward_return_pct")
    election_drawdown_delta = _delta(election_other, election_good, "max_drawdown_pct")

    def _verdict(return_delta: float | None, drawdown_delta: float | None) -> str:
        if return_delta is None or drawdown_delta is None:
            return "insufficient_data"
        if return_delta > 0 and drawdown_delta >= 0:
            return "supportive"
        if return_delta < 0 and drawdown_delta < 0:
            return "contradictory"
        return "mixed"

    return {
        "rate_expectation": {
            "return_delta_pct": rate_return_delta,
            "drawdown_delta_pct": rate_drawdown_delta,
            "verdict": _verdict(rate_return_delta, rate_drawdown_delta),
        },
        "election_cycle": {
            "return_delta_pct": election_return_delta,
            "drawdown_delta_pct": election_drawdown_delta,
            "verdict": _verdict(election_return_delta, election_drawdown_delta),
        },
    }


def run_analysis(
    *,
    start: str,
    end: str,
    forward_days: int,
    rate_lookbacks: list[int],
    basket_keys: list[str],
) -> dict:
    treasury_history = _fetch_treasury_yield_history("UST2Y", start=start, end=end)
    observations: list[dict] = []

    for basket_key in basket_keys:
        basket = RESEARCH_BASKETS[basket_key]
        ticker_data = _load_ticker_data(list(basket["tickers"]), start, end)
        close_frame = build_close_frame(ticker_data)
        if close_frame.empty:
            continue
        rate_features = build_rate_feature_frame(
            close_frame.index,
            treasury_history=treasury_history,
            lookbacks=rate_lookbacks,
        )
        for as_of in month_end_observation_dates(close_frame.index):
            path = compute_forward_equal_weight_path(
                close_frame,
                as_of,
                forward_days=forward_days,
                min_tickers=max(3, min(5, len(close_frame.columns))),
            )
            if path is None:
                continue
            metrics = compute_path_metrics(path)
            row = {
                "basket_key": basket_key,
                "basket_label": basket["label"],
                "date": pd.Timestamp(as_of).strftime("%Y-%m-%d"),
                "forward_return_pct": metrics["forward_return_pct"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
                "eligible_tickers": int(close_frame.loc[as_of].dropna().shape[0]),
                "election_cycle_phase": election_cycle_phase(as_of),
            }
            for lookback in rate_lookbacks:
                col = f"ust2y_change_bps_{lookback}"
                change_bps = float(rate_features.loc[as_of, col]) if pd.notna(rate_features.loc[as_of, col]) else None
                row[col] = None if change_bps is None else round(change_bps, 2)
                row[f"rate_bucket_{lookback}"] = classify_rate_environment(change_bps)
            observations.append(row)

    observation_df = pd.DataFrame(observations)
    if observation_df.empty:
        raise RuntimeError("No macro-regime observations were generated")

    rate_summaries = {
        str(lookback): _group_summary(observation_df, f"rate_bucket_{lookback}")
        for lookback in rate_lookbacks
    }
    election_summary = _group_summary(observation_df, "election_cycle_phase")
    basket_summary = [
        {
            "basket_key": basket_key,
            "observations": int(len(group.index)),
            "avg_forward_return_pct": round(float(group["forward_return_pct"].mean()), 2),
            "avg_max_drawdown_pct": round(float(group["max_drawdown_pct"].mean()), 2),
        }
        for basket_key, group in observation_df.groupby("basket_key")
    ]
    readouts = {
        str(lookback): _thesis_readout(
            observation_df,
            rate_col=f"rate_bucket_{lookback}",
            election_col="election_cycle_phase",
        )
        for lookback in rate_lookbacks
    }

    return {
        "start": start,
        "end": end,
        "forward_days": forward_days,
        "rate_lookbacks": rate_lookbacks,
        "basket_keys": basket_keys,
        "observation_count": int(len(observation_df.index)),
        "observations": observation_df.to_dict(orient="records"),
        "summaries": {
            "rate_buckets": rate_summaries,
            "election_cycle": election_summary,
            "basket": basket_summary,
        },
        "readouts": readouts,
    }


def _render_markdown(report: dict) -> str:
    lines = [
        "# Macro Regime Hypothesis Analysis",
        "",
        f"- Date range: `{report['start']}` to `{report['end']}`",
        f"- Forward window: `{report['forward_days']}` calendar days",
        f"- Observations: `{report['observation_count']}` month-end samples",
        f"- Baskets: `{', '.join(report['basket_keys'])}`",
        "",
        "## Thesis Readout",
        "",
    ]
    for lookback in report["rate_lookbacks"]:
        readout = report["readouts"][str(lookback)]
        lines.extend(
            [
                f"### UST2Y Change Lookback `{lookback}`",
                "",
                f"- Rate-cut thesis verdict: `{readout['rate_expectation']['verdict']}`",
                f"- Falling-vs-rising return delta: `{readout['rate_expectation']['return_delta_pct']}`",
                f"- Rising-vs-falling drawdown delta: `{readout['rate_expectation']['drawdown_delta_pct']}`",
                f"- Election thesis verdict: `{readout['election_cycle']['verdict']}`",
                f"- Election-vs-other return delta: `{readout['election_cycle']['return_delta_pct']}`",
                f"- Other-vs-election drawdown delta: `{readout['election_cycle']['drawdown_delta_pct']}`",
                "",
            ]
        )

    lines.extend(["## Rate Buckets", ""])
    for lookback in report["rate_lookbacks"]:
        lines.append(f"### Lookback `{lookback}`")
        lines.append("")
        lines.append("| Bucket | Obs | Avg Fwd Return % | Median Fwd Return % | Avg Max DD % | Positive Rate % |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for row in report["summaries"]["rate_buckets"][str(lookback)]:
            lines.append(
                f"| {row['bucket']} | {row['observations']} | "
                f"{row['avg_forward_return_pct']} | {row['median_forward_return_pct']} | "
                f"{row['avg_max_drawdown_pct']} | {row['positive_rate_pct']} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Election Cycle",
            "",
            "| Phase | Obs | Avg Fwd Return % | Median Fwd Return % | Avg Max DD % | Positive Rate % |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["summaries"]["election_cycle"]:
        lines.append(
            f"| {row['bucket']} | {row['observations']} | {row['avg_forward_return_pct']} | "
            f"{row['median_forward_return_pct']} | {row['avg_max_drawdown_pct']} | {row['positive_rate_pct']} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Basket Summary",
            "",
            "| Basket | Obs | Avg Fwd Return % | Avg Max DD % |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in report["summaries"]["basket"]:
        lines.append(
            f"| {row['basket_key']} | {row['observations']} | {row['avg_forward_return_pct']} | {row['avg_max_drawdown_pct']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    lookbacks = [int(part.strip()) for part in args.rate_lookbacks.split(",") if part.strip()]
    basket_keys = [part.strip() for part in args.baskets.split(",") if part.strip()]
    report = run_analysis(
        start=args.start,
        end=args.end,
        forward_days=args.forward_days,
        rate_lookbacks=lookbacks,
        basket_keys=basket_keys,
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
