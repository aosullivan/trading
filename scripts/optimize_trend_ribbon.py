import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.paths import get_user_data_path
from lib.trend_optimizer import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_DRAWDOWN_WEIGHT,
    DEFAULT_INTERVALS,
    DEFAULT_MAX_ROUND_TRIPS_PER_YEAR,
    DEFAULT_PROGRESS_EVERY,
    DEFAULT_TICKERS,
    DEFAULT_TOP_N,
    build_date_windows,
    build_evaluation_targets,
    build_ribbon_configs,
    export_rankings,
    run_optimizer,
    write_manifest_files,
)


def _csv_arg(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _print_manifest_summary(summary_path: str):
    summary = json.loads(Path(summary_path).read_text())
    print(json.dumps(summary, indent=2, sort_keys=True))


def _manifest_command(args):
    configs = build_ribbon_configs()
    windows = build_date_windows(as_of=args.as_of)
    targets = build_evaluation_targets(
        tickers=args.tickers,
        intervals=args.intervals,
        windows=windows,
    )
    output_paths = write_manifest_files(
        output_dir=args.output_dir,
        configs=configs,
        windows=windows,
        targets=targets,
    )
    print("Manifest written:")
    for name, path in output_paths.items():
        print(f"  {name}: {path}")
    _print_manifest_summary(output_paths["summary"])


def _run_command(args):
    result = run_optimizer(
        run_id=args.run_id,
        as_of=args.as_of,
        db_path=args.db_path,
        tickers=args.tickers,
        intervals=args.intervals,
        drawdown_weight=args.drawdown_weight,
        max_round_trips_per_year=args.max_round_trips_per_year,
        batch_size=args.batch_size,
        workers=args.workers,
        progress_every=args.progress_every,
        top_n=args.top_n,
        limit_targets=args.limit_targets,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def _export_command(args):
    output_path = export_rankings(
        run_id=args.run_id,
        db_path=args.db_path,
        output_path=args.output_path,
        max_round_trips_per_year=args.max_round_trips_per_year,
        top_n=args.top_n,
    )
    print(f"Exported rankings to {output_path}")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Build and run a resumable Trend-Driven optimizer harness.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser(
        "manifest",
        help="Write CSV/JSON manifests for configs, date windows, and ticker/window targets.",
    )
    manifest.add_argument("--as-of", default=None)
    manifest.add_argument("--tickers", type=_csv_arg, default=DEFAULT_TICKERS)
    manifest.add_argument("--intervals", type=_csv_arg, default=DEFAULT_INTERVALS)
    manifest.add_argument(
        "--output-dir",
        default=get_user_data_path("optimizer", "manifests", "trend_ribbon"),
    )
    manifest.set_defaults(func=_manifest_command)

    run = subparsers.add_parser(
        "run",
        help="Execute or resume a Trend-Driven optimization run.",
    )
    run.add_argument("--run-id", required=True)
    run.add_argument("--as-of", default=None)
    run.add_argument("--tickers", type=_csv_arg, default=DEFAULT_TICKERS)
    run.add_argument("--intervals", type=_csv_arg, default=DEFAULT_INTERVALS)
    run.add_argument(
        "--db-path",
        default=get_user_data_path("optimizer", "trend_ribbon.sqlite3"),
    )
    run.add_argument("--drawdown-weight", type=float, default=DEFAULT_DRAWDOWN_WEIGHT)
    run.add_argument(
        "--max-round-trips-per-year",
        type=float,
        default=DEFAULT_MAX_ROUND_TRIPS_PER_YEAR,
    )
    run.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    run.add_argument("--workers", type=int, default=1)
    run.add_argument("--progress-every", type=int, default=DEFAULT_PROGRESS_EVERY)
    run.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    run.add_argument(
        "--limit-targets",
        type=int,
        default=None,
        help="Optional cap for smoke-test runs over the first N ticker/interval/windows.",
    )
    run.set_defaults(func=_run_command)

    export = subparsers.add_parser(
        "export",
        help="Export top-ranked configs from a completed or in-progress run.",
    )
    export.add_argument("--run-id", required=True)
    export.add_argument(
        "--db-path",
        default=get_user_data_path("optimizer", "trend_ribbon.sqlite3"),
    )
    export.add_argument(
        "--output-path",
        default=get_user_data_path("optimizer", "trend_ribbon_rankings.csv"),
    )
    export.add_argument(
        "--max-round-trips-per-year",
        type=float,
        default=DEFAULT_MAX_ROUND_TRIPS_PER_YEAR,
    )
    export.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    export.set_defaults(func=_export_command)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
