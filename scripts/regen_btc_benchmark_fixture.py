#!/usr/bin/env python3
"""Regenerate tests/fixtures/btc_usd_1d_benchmark.csv from Yahoo Finance.

Uses the same warmup rule as /api/chart (DAILY_WARMUP_DAYS before chart "start").
After regenerating, update tests/fixtures/btc_benchmark_backtests.json PnL floors
(run pytest tests/test_btc_benchmark_backtests.py and adjust mins, or read metrics
from a one-off client call).

Usage (from repo root):
  python scripts/regen_btc_benchmark_fixture.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.data_fetching import _yf_rate_limited_download  # noqa: E402
from lib.settings import DAILY_WARMUP_DAYS  # noqa: E402

SPEC = ROOT / "tests" / "fixtures" / "btc_benchmark_backtests.json"
OUT_CSV = ROOT / "tests" / "fixtures" / "btc_usd_1d_benchmark.csv"


def _warmup_start(chart_start: str) -> str:
    ts = pd.Timestamp(chart_start).normalize()
    return (ts - timedelta(days=DAILY_WARMUP_DAYS)).strftime("%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec",
        type=Path,
        default=SPEC,
        help="JSON with chart_request.start / chart_request.end / ticker",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=OUT_CSV,
        help="Output CSV path",
    )
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    req = spec["chart_request"]
    ticker = req["ticker"]
    chart_start = req["start"]
    chart_end = req["end"]

    dl_start = _warmup_start(chart_start)
    dl_end = pd.Timestamp(chart_end).normalize() + timedelta(days=1)
    dl_end_s = dl_end.strftime("%Y-%m-%d")

    print(f"Downloading {ticker} {dl_start} .. {dl_end_s} (exclusive end) …")
    df = _yf_rate_limited_download(
        ticker,
        start=dl_start,
        end=dl_end_s,
        interval="1d",
        progress=True,
        threads=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[~df.index.duplicated(keep="last")].sort_index()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output)
    print(f"Wrote {len(df)} rows to {args.output}")
    print("Next: update tests/fixtures/btc_benchmark_backtests.json floors if metrics moved.")


if __name__ == "__main__":
    main()
