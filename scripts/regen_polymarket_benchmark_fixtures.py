#!/usr/bin/env python3
"""Regenerate deterministic fixtures for the BTC Polymarket ratchet benchmark.

Usage:
  python scripts/regen_polymarket_benchmark_fixtures.py
  python scripts/regen_polymarket_benchmark_fixtures.py --check
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
from lib.polymarket import load_probability_history  # noqa: E402
from lib.settings import DAILY_WARMUP_DAYS  # noqa: E402

SPEC = ROOT / "tests" / "fixtures" / "polymarket_benchmark_backtests.json"
OUT_CSV = ROOT / "tests" / "fixtures" / "btc_usd_polymarket_1d_benchmark.csv"
OUT_HISTORY = ROOT / "tests" / "fixtures" / "polymarket_probability_history_benchmark.json"


def _warmup_start(chart_start: str) -> str:
    ts = pd.Timestamp(chart_start).normalize()
    return (ts - timedelta(days=DAILY_WARMUP_DAYS)).strftime("%Y-%m-%d")


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[~df.index.duplicated(keep="last")].sort_index()


def _trim_history_for_window(history_df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    if history_df is None or history_df.empty:
        return pd.DataFrame()
    trimmed = history_df.copy()
    idx = pd.to_datetime(trimmed.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    trimmed.index = idx
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    return trimmed.loc[(trimmed.index >= start_ts) & (trimmed.index <= end_ts)].copy()


def _history_records(history_df: pd.DataFrame) -> list[dict]:
    records: list[dict] = []
    for date, row in history_df.iterrows():
        record = {"date": date.strftime("%Y-%m-%d")}
        for key, value in row.items():
            if isinstance(value, pd.Timestamp):
                record[key] = value.strftime("%Y-%m-%d")
            elif isinstance(value, (list, dict)):
                record[key] = value
            elif pd.isna(value):
                record[key] = None
            else:
                record[key] = value
        records.append(record)
    return records


def _validate_paths(spec: dict, csv_path: Path, history_path: Path) -> list[str]:
    errors: list[str] = []
    fixtures = spec.get("fixtures", {})
    if fixtures.get("ohlcv_csv") != str(csv_path.relative_to(ROOT)):
        errors.append("Spec ohlcv_csv path does not match expected benchmark CSV path")
    if fixtures.get("probability_history_json") != str(history_path.relative_to(ROOT)):
        errors.append("Spec probability_history_json path does not match expected benchmark history path")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=SPEC, help="Benchmark spec JSON path")
    parser.add_argument("--ohlcv-output", type=Path, default=OUT_CSV, help="Output BTC OHLCV CSV path")
    parser.add_argument(
        "--history-output",
        type=Path,
        default=OUT_HISTORY,
        help="Output Polymarket history JSON path",
    )
    parser.add_argument("--check", action="store_true", help="Validate existing fixtures and exit")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    req = spec["chart_request"]
    errors = _validate_paths(spec, args.ohlcv_output, args.history_output)

    if args.check:
        if not args.ohlcv_output.exists():
            errors.append(f"Missing OHLCV fixture: {args.ohlcv_output}")
        if not args.history_output.exists():
            errors.append(f"Missing Polymarket history fixture: {args.history_output}")
        history_window = spec.get("history_window") or {}
        expected_history_start = history_window.get("start", req["start"])
        expected_history_end = history_window.get("end", req["end"])
        if not errors and args.history_output.exists():
            history = json.loads(args.history_output.read_text(encoding="utf-8"))
            if not history:
                errors.append("Polymarket history fixture is empty")
            else:
                dates = [item.get("date") for item in history if item.get("date")]
                if not dates:
                    errors.append("Polymarket history fixture has no dates")
                else:
                    if min(dates) != expected_history_start or max(dates) != expected_history_end:
                        errors.append(
                            "Polymarket history fixture dates do not match the declared history_window"
                        )
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            raise SystemExit(1)
        print("Polymarket benchmark fixtures look consistent.")
        return

    ticker = req["ticker"]
    chart_start = req["start"]
    chart_end = req["end"]
    dl_start = _warmup_start(chart_start)
    dl_end = (pd.Timestamp(chart_end).normalize() + timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"Downloading {ticker} {dl_start} .. {dl_end} (exclusive end) ...")
    ohlcv = _yf_rate_limited_download(
        ticker,
        start=dl_start,
        end=dl_end,
        interval=req["interval"],
        progress=True,
        threads=False,
    )
    ohlcv = _normalize_ohlcv(ohlcv)

    history_df = load_probability_history(auto_seed=True)
    history_df = _trim_history_for_window(history_df, chart_start, chart_end)
    if history_df.empty:
        raise SystemExit("Polymarket history window is empty; cannot build benchmark fixture.")

    args.ohlcv_output.parent.mkdir(parents=True, exist_ok=True)
    args.history_output.parent.mkdir(parents=True, exist_ok=True)
    ohlcv.to_csv(args.ohlcv_output)
    args.history_output.write_text(
        json.dumps(_history_records(history_df), indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(ohlcv)} OHLCV rows to {args.ohlcv_output}")
    print(f"Wrote {len(history_df)} Polymarket history rows to {args.history_output}")


if __name__ == "__main__":
    main()
