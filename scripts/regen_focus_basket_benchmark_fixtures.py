#!/usr/bin/env python3
"""Regenerate frozen focus-basket benchmark fixtures from Yahoo Finance.

The fixture set mirrors the /api/chart warmup rule for the shared Phase 3
benchmark request window. Use --check in CI or local verification to make sure
the committed CSV set still matches the JSON spec.
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

from lib.cache import _yf_rate_limited_download  # noqa: E402
from lib.settings import DAILY_WARMUP_DAYS  # noqa: E402

SPEC_PATH = ROOT / "tests" / "fixtures" / "focus_basket_benchmarks.json"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "focus_basket"


def _warmup_start(chart_start: str) -> str:
    start_ts = pd.Timestamp(chart_start).normalize()
    return (start_ts - timedelta(days=DAILY_WARMUP_DAYS)).strftime("%Y-%m-%d")


def _fixture_filename(ticker: str) -> str:
    return f"{ticker.lower().replace('-', '_')}_1d_benchmark.csv"


def _expected_fixture_paths(spec: dict, output_dir: Path) -> dict[str, Path]:
    tickers = spec.get("tickers", [])
    return {ticker: output_dir / _fixture_filename(ticker) for ticker in tickers}


def _load_spec(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_spec_and_files(spec: dict, output_dir: Path) -> list[str]:
    errors = []
    tickers = spec.get("tickers", [])
    per_ticker = spec.get("per_ticker", {})
    expected_paths = _expected_fixture_paths(spec, output_dir)

    if list(per_ticker.keys()) != tickers:
        errors.append("per_ticker keys must match tickers array order exactly")

    expected_names = {_fixture_filename(ticker) for ticker in tickers}
    existing_names = {path.name for path in output_dir.glob("*_1d_benchmark.csv")}
    missing_names = sorted(expected_names - existing_names)
    unexpected_names = sorted(existing_names - expected_names)

    for ticker, path in expected_paths.items():
        if not path.exists():
            errors.append(f"missing fixture for {ticker}: {path}")

    if missing_names:
        errors.append("missing expected CSV files: " + ", ".join(missing_names))
    if unexpected_names:
        errors.append("unexpected CSV files present: " + ", ".join(unexpected_names))

    for ticker in tickers:
        meta = per_ticker.get(ticker, {})
        expected_rel = str(Path("tests") / "fixtures" / "focus_basket" / _fixture_filename(ticker))
        if meta.get("fixture_csv") != expected_rel:
            errors.append(f"{ticker} fixture_csv must be {expected_rel}")

    return errors


def _download_fixture(ticker: str, chart_request: dict, out_path: Path) -> None:
    chart_start = chart_request["start"]
    chart_end = chart_request["end"]
    download_start = _warmup_start(chart_start)
    download_end = (pd.Timestamp(chart_end).normalize() + timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"Downloading {ticker} {download_start} .. {download_end} (exclusive end)")
    df = _yf_rate_limited_download(
        ticker,
        start=download_start,
        end=download_end,
        interval=chart_request["interval"],
        progress=True,
        threads=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[~df.index.duplicated(keep="last")].sort_index()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path)
    print(f"Wrote {len(df)} rows to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=SPEC_PATH, help="Path to benchmark spec JSON")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=FIXTURE_DIR,
        help="Directory for frozen focus-basket CSV fixtures",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the spec/fixture contract without downloading data",
    )
    args = parser.parse_args()

    spec = _load_spec(args.spec)
    expected_paths = _expected_fixture_paths(spec, args.output_dir)

    if args.check:
        errors = _validate_spec_and_files(spec, args.output_dir)
        if errors:
            for err in errors:
                print(err, file=sys.stderr)
            raise SystemExit(1)
        print(
            "Focus-basket fixtures verified for: "
            + ", ".join(spec["tickers"])
        )
        return

    for ticker, out_path in expected_paths.items():
        _download_fixture(ticker, spec["chart_request"], out_path)

    errors = _validate_spec_and_files(spec, args.output_dir)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        raise SystemExit(1)

    print("Next: run pytest tests/test_focus_basket_benchmark_backtests.py and update pinned metrics if baseline moved.")


if __name__ == "__main__":
    main()
