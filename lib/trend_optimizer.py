from __future__ import annotations

import csv
import gc
import hashlib
import itertools
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from lib.backtesting import backtest_direction
from lib.data_fetching import (
    cached_download,
    normalize_ticker,
    resolve_treasury_price_proxy_ticker,
)
from lib.paths import get_user_data_path
from lib.settings import DAILY_WARMUP_DAYS, WEEKLY_WARMUP_DAYS
from lib.technical_indicators import compute_trend_ribbon


DEFAULT_TICKERS = [
    "BTC-USD",
    "ETH-USD",
    "SPX",
    "VGT",
    "TLT",
    "NVDA",
    "AAPL",
    "TSLA",
    "XLE",
    "MU",
    "MRVL",
    "AMD",
    "AVGO",
    "AMAT",
    "LRCX",
    "TSM",
    "ASML",
    "QCOM",
    "SMH",
]
DEFAULT_INTERVALS = ["1d", "1wk", "1mo"]
DEFAULT_STRATEGY = "ribbon"
DEFAULT_DRAWDOWN_WEIGHT = 0.45
DEFAULT_MAX_ROUND_TRIPS_PER_YEAR = 6.0
DEFAULT_BATCH_SIZE = 128
DEFAULT_PROGRESS_EVERY = 500
DEFAULT_TOP_N = 20
DEFAULT_DB_PATH = get_user_data_path("optimizer", "trend_ribbon.sqlite3")

RIBBON_GRID = {
    "ema_period": [13, 21, 34],
    "atr_period": [10, 14, 20],
    "fast_period": [4, 6, 8],
    "slow_period": [13, 21, 34],
    "smooth_period": [3, 5, 8],
    "collapse_threshold": [0.06, 0.08, 0.10],
    "expand_threshold": [0.12, 0.15, 0.18],
}

WINDOW_SPECS = [
    ("6m", 6, list(range(0, 37, 3)) + [48, 60, 72, 84, 96, 108]),
    ("1y", 12, list(range(0, 49, 6)) + [60, 72, 84, 96, 108]),
    ("2y", 24, list(range(0, 97, 12))),
    ("3y", 36, list(range(0, 85, 12))),
    ("5y", 60, [0, 24, 48, 60]),
    ("8y", 96, [0, 24]),
]

MAX_FIRST_BAR_DELAY_DAYS = {
    "1d": 14,
    "1wk": 14,
    "1mo": 45,
}


@dataclass(frozen=True)
class OptimizerConfig:
    config_id: str
    strategy: str
    params: dict[str, int | float]


@dataclass(frozen=True)
class DateWindow:
    window_id: str
    duration: str
    start_date: str
    end_date: str
    months: int


@dataclass(frozen=True)
class EvaluationTarget:
    ticker: str
    data_ticker: str
    interval: str
    window_id: str
    duration: str
    start_date: str
    end_date: str
    status: str = "pending"
    skip_reason: str = ""


@dataclass
class LoadedFrame:
    full_df: pd.DataFrame
    view_df: pd.DataFrame
    prior_direction_source: pd.DataFrame


def ribbon_config_id(params: dict[str, int | float], strategy: str = DEFAULT_STRATEGY) -> str:
    payload = json.dumps(
        {"strategy": strategy, "params": params},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_ribbon_configs() -> list[OptimizerConfig]:
    keys = list(RIBBON_GRID)
    configs = []
    for values in itertools.product(*(RIBBON_GRID[key] for key in keys)):
        params = dict(zip(keys, values))
        if params["slow_period"] <= params["fast_period"]:
            continue
        if params["expand_threshold"] < params["collapse_threshold"]:
            continue
        config_id = ribbon_config_id(params)
        configs.append(
            OptimizerConfig(
                config_id=config_id,
                strategy=DEFAULT_STRATEGY,
                params=params,
            )
        )
    return configs


def build_date_windows(as_of: date | str | None = None) -> list[DateWindow]:
    end_anchor = pd.Timestamp(as_of or date.today()).normalize()
    windows = []
    for duration, months, end_offsets_months in WINDOW_SPECS:
        for offset in end_offsets_months:
            end_date = end_anchor - pd.DateOffset(months=offset)
            start_date = end_date - pd.DateOffset(months=months)
            windows.append(
                DateWindow(
                    window_id=(
                        f"{duration}_{start_date.date().isoformat()}_"
                        f"{end_date.date().isoformat()}"
                    ),
                    duration=duration,
                    start_date=start_date.date().isoformat(),
                    end_date=end_date.date().isoformat(),
                    months=months,
                )
            )
    return windows


def _source_interval(interval: str) -> str:
    return "1wk" if interval == "1mo" else interval


def _warmup_start(start_date: str, interval: str) -> str:
    warmup_days = WEEKLY_WARMUP_DAYS if interval in {"1wk", "1mo"} else DAILY_WARMUP_DAYS
    start_ts = pd.Timestamp(start_date).normalize()
    return (start_ts - pd.Timedelta(days=warmup_days)).date().isoformat()


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    resampled = (
        df.sort_index()
        .resample(rule)
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
    return resampled.dropna(subset=["Open", "High", "Low", "Close"])


def _derive_interval_frame(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if interval == "1mo":
        return _resample_ohlcv(df, "ME")
    return df


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    normalized = df.copy()
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = normalized.columns.get_level_values(0)
    normalized = normalized[~normalized.index.duplicated(keep="last")].sort_index()
    return normalized


def _slice_visible_frame(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    start_ts = pd.Timestamp(start_date).normalize()
    end_ts = pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    return df.loc[(df.index >= start_ts) & (df.index <= end_ts)].copy()


def load_market_frame(target: EvaluationTarget) -> tuple[LoadedFrame | None, str]:
    try:
        source_df = cached_download(
            target.data_ticker,
            start=_warmup_start(target.start_date, target.interval),
            end=target.end_date,
            interval=_source_interval(target.interval),
            progress=False,
        )
    except Exception as exc:
        return None, f"load_error:{exc}"

    source_df = _normalize_frame(source_df)
    full_df = _derive_interval_frame(source_df, target.interval)
    full_df = _normalize_frame(full_df)
    view_df = _slice_visible_frame(full_df, target.start_date, target.end_date)

    if view_df.empty:
        return None, "skipped_insufficient_history"

    first_allowed = (
        pd.Timestamp(target.start_date).normalize()
        + pd.Timedelta(days=MAX_FIRST_BAR_DELAY_DAYS[target.interval])
    )
    if pd.Timestamp(view_df.index[0]) > first_allowed:
        return None, "skipped_insufficient_history"

    return LoadedFrame(full_df=full_df, view_df=view_df, prior_direction_source=full_df), ""


def build_evaluation_targets(
    tickers: list[str] | None = None,
    intervals: list[str] | None = None,
    windows: list[DateWindow] | None = None,
    frame_loader: Callable[[EvaluationTarget], tuple[LoadedFrame | None, str]] = load_market_frame,
) -> list[EvaluationTarget]:
    tickers = tickers or DEFAULT_TICKERS
    intervals = intervals or DEFAULT_INTERVALS
    windows = windows or build_date_windows()
    targets = []
    for ticker in tickers:
        data_ticker = normalize_ticker(resolve_treasury_price_proxy_ticker(ticker))
        for interval in intervals:
            for window in windows:
                target = EvaluationTarget(
                    ticker=ticker,
                    data_ticker=data_ticker,
                    interval=interval,
                    window_id=window.window_id,
                    duration=window.duration,
                    start_date=window.start_date,
                    end_date=window.end_date,
                )
                _loaded, skip_reason = frame_loader(target)
                if skip_reason:
                    target = EvaluationTarget(
                        ticker=target.ticker,
                        data_ticker=target.data_ticker,
                        interval=target.interval,
                        window_id=target.window_id,
                        duration=target.duration,
                        start_date=target.start_date,
                        end_date=target.end_date,
                        status="skipped",
                        skip_reason=skip_reason,
                    )
                targets.append(target)
    return targets


def write_manifest_files(
    output_dir: str | Path,
    configs: list[OptimizerConfig],
    windows: list[DateWindow],
    targets: list[EvaluationTarget],
) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    config_path = output_path / "ribbon_configs.csv"
    with config_path.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["config_id", "strategy", *list(RIBBON_GRID)],
        )
        writer.writeheader()
        for config in configs:
            writer.writerow(
                {
                    "config_id": config.config_id,
                    "strategy": config.strategy,
                    **config.params,
                }
            )

    window_path = output_path / "date_windows.csv"
    with window_path.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["window_id", "duration", "months", "start_date", "end_date"],
        )
        writer.writeheader()
        for window in windows:
            writer.writerow(
                {
                    "window_id": window.window_id,
                    "duration": window.duration,
                    "months": window.months,
                    "start_date": window.start_date,
                    "end_date": window.end_date,
                }
            )

    target_path = output_path / "evaluation_targets.csv"
    with target_path.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "ticker",
                "data_ticker",
                "interval",
                "window_id",
                "duration",
                "start_date",
                "end_date",
                "status",
                "skip_reason",
            ],
        )
        writer.writeheader()
        for target in targets:
            writer.writerow(
                {
                    "ticker": target.ticker,
                    "data_ticker": target.data_ticker,
                    "interval": target.interval,
                    "window_id": target.window_id,
                    "duration": target.duration,
                    "start_date": target.start_date,
                    "end_date": target.end_date,
                    "status": target.status,
                    "skip_reason": target.skip_reason,
                }
            )

    summary_path = output_path / "manifest_summary.json"
    summary = {
        "strategy": DEFAULT_STRATEGY,
        "config_count": len(configs),
        "window_count": len(windows),
        "target_count": len(targets),
        "runnable_target_count": sum(1 for target in targets if target.status == "pending"),
        "skipped_target_count": sum(1 for target in targets if target.status != "pending"),
        "planned_evaluation_count": len(configs)
        * sum(1 for target in targets if target.status == "pending"),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))

    return {
        "configs": str(config_path),
        "windows": str(window_path),
        "targets": str(target_path),
        "summary": str(summary_path),
    }


def _carry_neutral_direction(direction: pd.Series) -> pd.Series:
    return direction.replace(0, pd.NA).ffill().fillna(0).astype(int)


def _prior_direction(direction: pd.Series, full_index: pd.Index, view_index: pd.Index) -> int | None:
    if len(view_index) == 0:
        return None
    first_visible_loc = full_index.get_indexer([view_index[0]])[0]
    if first_visible_loc <= 0:
        return None
    prior = direction.iloc[first_visible_loc - 1]
    return None if pd.isna(prior) else int(prior)


def _window_years(start_date: str, end_date: str) -> float:
    start_ts = pd.Timestamp(start_date).normalize()
    end_ts = pd.Timestamp(end_date).normalize()
    return max((end_ts - start_ts).days / 365.25, 1 / 365.25)


def evaluate_ribbon_config(
    config: OptimizerConfig,
    target: EvaluationTarget,
    loaded_frame: LoadedFrame,
    drawdown_weight: float = DEFAULT_DRAWDOWN_WEIGHT,
) -> dict[str, object]:
    _center, _upper, _lower, _strength, direction = compute_trend_ribbon(
        loaded_frame.full_df,
        **config.params,
    )
    direction = _carry_neutral_direction(direction)
    prior_dir = _prior_direction(
        direction,
        loaded_frame.prior_direction_source.index,
        loaded_frame.view_df.index,
    )
    _trades, summary, _equity = backtest_direction(
        loaded_frame.view_df,
        direction.loc[loaded_frame.view_df.index],
        start_in_position=prior_dir == 1,
        prior_direction=prior_dir,
    )
    trades_per_year = summary["total_trades"] / _window_years(
        target.start_date,
        target.end_date,
    )
    score = summary["net_profit_pct"] - drawdown_weight * summary["max_drawdown_pct"]
    return {
        "run_id": "",
        "config_id": config.config_id,
        "ticker": target.ticker,
        "data_ticker": target.data_ticker,
        "interval": target.interval,
        "window_id": target.window_id,
        "duration": target.duration,
        "start_date": target.start_date,
        "end_date": target.end_date,
        "status": "completed",
        "skip_reason": "",
        "score": round(score, 6),
        "net_profit_pct": float(summary["net_profit_pct"]),
        "max_drawdown_pct": float(summary["max_drawdown_pct"]),
        "total_trades": int(summary["total_trades"]),
        "trades_per_year": round(float(trades_per_year), 6),
        "error": "",
        "completed_at": _utc_now(),
    }


def _connect(db_path: str | Path) -> sqlite3.Connection:
    Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _init_db(conn: sqlite3.Connection):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS optimizer_runs (
            run_id TEXT PRIMARY KEY,
            strategy TEXT NOT NULL,
            as_of TEXT NOT NULL,
            drawdown_weight REAL NOT NULL,
            max_round_trips_per_year REAL NOT NULL,
            tickers_json TEXT NOT NULL,
            intervals_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS optimizer_configs (
            run_id TEXT NOT NULL,
            config_id TEXT NOT NULL,
            strategy TEXT NOT NULL,
            params_json TEXT NOT NULL,
            PRIMARY KEY (run_id, config_id),
            FOREIGN KEY (run_id) REFERENCES optimizer_runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS optimizer_windows (
            run_id TEXT NOT NULL,
            window_id TEXT NOT NULL,
            duration TEXT NOT NULL,
            months INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            PRIMARY KEY (run_id, window_id),
            FOREIGN KEY (run_id) REFERENCES optimizer_runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS optimizer_evaluations (
            run_id TEXT NOT NULL,
            config_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            data_ticker TEXT NOT NULL,
            interval TEXT NOT NULL,
            window_id TEXT NOT NULL,
            duration TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            status TEXT NOT NULL,
            skip_reason TEXT NOT NULL DEFAULT '',
            score REAL,
            net_profit_pct REAL,
            max_drawdown_pct REAL,
            total_trades INTEGER,
            trades_per_year REAL,
            error TEXT NOT NULL DEFAULT '',
            completed_at TEXT NOT NULL,
            PRIMARY KEY (run_id, config_id, ticker, interval, window_id),
            FOREIGN KEY (run_id, config_id) REFERENCES optimizer_configs(run_id, config_id)
        );

        CREATE INDEX IF NOT EXISTS idx_optimizer_eval_rank
        ON optimizer_evaluations(run_id, config_id, status);
        """
    )
    conn.commit()


def _persist_manifest(
    conn: sqlite3.Connection,
    run_id: str,
    strategy: str,
    as_of: str,
    drawdown_weight: float,
    max_round_trips_per_year: float,
    tickers: list[str],
    intervals: list[str],
    configs: list[OptimizerConfig],
    windows: list[DateWindow],
):
    now = _utc_now()
    existing = conn.execute(
        "SELECT * FROM optimizer_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if existing:
        expected = {
            "strategy": strategy,
            "as_of": as_of,
            "tickers_json": json.dumps(tickers),
            "intervals_json": json.dumps(intervals),
        }
        for key, expected_value in expected.items():
            if existing[key] != expected_value:
                raise ValueError(
                    f"run_id={run_id} already exists with a different {key}; "
                    f"use a new run id or the same manifest inputs"
                )
        conn.execute(
            "UPDATE optimizer_runs SET drawdown_weight = ?, "
            "max_round_trips_per_year = ?, updated_at = ? WHERE run_id = ?",
            (drawdown_weight, max_round_trips_per_year, now, run_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO optimizer_runs (
                run_id, strategy, as_of, drawdown_weight,
                max_round_trips_per_year, tickers_json,
                intervals_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                strategy,
                as_of,
                drawdown_weight,
                max_round_trips_per_year,
                json.dumps(tickers),
                json.dumps(intervals),
                now,
                now,
            ),
        )

    conn.executemany(
        """
        INSERT OR IGNORE INTO optimizer_configs
        (run_id, config_id, strategy, params_json)
        VALUES (?, ?, ?, ?)
        """,
        [
            (
                run_id,
                config.config_id,
                config.strategy,
                json.dumps(config.params, sort_keys=True),
            )
            for config in configs
        ],
    )
    conn.executemany(
        """
        INSERT OR IGNORE INTO optimizer_windows
        (run_id, window_id, duration, months, start_date, end_date)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                run_id,
                window.window_id,
                window.duration,
                window.months,
                window.start_date,
                window.end_date,
            )
            for window in windows
        ],
    )
    conn.commit()


def _existing_config_ids_for_target(
    conn: sqlite3.Connection,
    run_id: str,
    target: EvaluationTarget,
) -> set[str]:
    rows = conn.execute(
        """
        SELECT config_id FROM optimizer_evaluations
        WHERE run_id = ?
          AND ticker = ?
          AND interval = ?
          AND window_id = ?
          AND status IN ('completed', 'skipped')
        """,
        (run_id, target.ticker, target.interval, target.window_id),
    ).fetchall()
    return {row["config_id"] for row in rows}


def _insert_rows(conn: sqlite3.Connection, run_id: str, rows: list[dict[str, object]]):
    if not rows:
        return
    conn.executemany(
        """
        INSERT OR REPLACE INTO optimizer_evaluations (
            run_id, config_id, ticker, data_ticker, interval,
            window_id, duration, start_date, end_date,
            status, skip_reason, score, net_profit_pct,
            max_drawdown_pct, total_trades, trades_per_year,
            error, completed_at
        ) VALUES (
            :run_id, :config_id, :ticker, :data_ticker, :interval,
            :window_id, :duration, :start_date, :end_date,
            :status, :skip_reason, :score, :net_profit_pct,
            :max_drawdown_pct, :total_trades, :trades_per_year,
            :error, :completed_at
        )
        """,
        [{**row, "run_id": run_id} for row in rows],
    )
    conn.execute(
        "UPDATE optimizer_runs SET updated_at = ? WHERE run_id = ?",
        (_utc_now(), run_id),
    )
    conn.commit()


def _rank_rows(
    conn: sqlite3.Connection,
    run_id: str,
    max_round_trips_per_year: float,
    top_n: int = DEFAULT_TOP_N,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            e.config_id AS config_id,
            c.params_json AS params_json,
            COUNT(*) AS completed_evals,
            AVG(e.score) AS avg_score,
            AVG(e.net_profit_pct) AS avg_net_profit_pct,
            AVG(e.max_drawdown_pct) AS avg_max_drawdown_pct,
            AVG(e.trades_per_year) AS avg_trades_per_year
        FROM optimizer_evaluations e
        JOIN optimizer_configs c
          ON c.run_id = e.run_id AND c.config_id = e.config_id
        WHERE e.run_id = ?
          AND e.status = 'completed'
        GROUP BY e.config_id, c.params_json
        HAVING avg_trades_per_year <= ?
        ORDER BY
            avg_score DESC,
            avg_net_profit_pct DESC,
            avg_max_drawdown_pct ASC,
            e.config_id ASC
        LIMIT ?
        """,
        (run_id, max_round_trips_per_year, top_n),
    ).fetchall()
    return [
        {
            "config_id": row["config_id"],
            "params": json.loads(row["params_json"]),
            "completed_evals": row["completed_evals"],
            "avg_score": round(row["avg_score"], 6),
            "avg_net_profit_pct": round(row["avg_net_profit_pct"], 6),
            "avg_max_drawdown_pct": round(row["avg_max_drawdown_pct"], 6),
            "avg_trades_per_year": round(row["avg_trades_per_year"], 6),
        }
        for row in rows
    ]


def _count_completed_eval_rows(conn: sqlite3.Connection, run_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM optimizer_evaluations WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row["n"] if row else 0)


def _evaluate_configs_for_target(
    configs: list[OptimizerConfig],
    target: EvaluationTarget,
    loaded_frame: LoadedFrame,
    drawdown_weight: float,
    workers: int,
) -> list[dict[str, object]]:
    if workers <= 1:
        return [
            evaluate_ribbon_config(
                config=config,
                target=target,
                loaded_frame=loaded_frame,
                drawdown_weight=drawdown_weight,
            )
            for config in configs
        ]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                evaluate_ribbon_config,
                config,
                target,
                loaded_frame,
                drawdown_weight,
            )
            for config in configs
        ]
        return [future.result() for future in futures]


def run_optimizer(
    run_id: str,
    *,
    as_of: date | str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
    tickers: list[str] | None = None,
    intervals: list[str] | None = None,
    configs: list[OptimizerConfig] | None = None,
    windows: list[DateWindow] | None = None,
    drawdown_weight: float = DEFAULT_DRAWDOWN_WEIGHT,
    max_round_trips_per_year: float = DEFAULT_MAX_ROUND_TRIPS_PER_YEAR,
    batch_size: int = DEFAULT_BATCH_SIZE,
    workers: int = 1,
    progress_every: int = DEFAULT_PROGRESS_EVERY,
    frame_loader: Callable[[EvaluationTarget], tuple[LoadedFrame | None, str]] = load_market_frame,
    limit_targets: int | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, object]:
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    if workers < 1:
        raise ValueError("workers must be >= 1")

    tickers = tickers or DEFAULT_TICKERS
    intervals = intervals or DEFAULT_INTERVALS
    configs = configs or build_ribbon_configs()
    windows = windows or build_date_windows(as_of=as_of)
    as_of_str = str(pd.Timestamp(as_of or date.today()).date())

    conn = _connect(db_path)
    try:
        _init_db(conn)
        _persist_manifest(
            conn,
            run_id=run_id,
            strategy=DEFAULT_STRATEGY,
            as_of=as_of_str,
            drawdown_weight=drawdown_weight,
            max_round_trips_per_year=max_round_trips_per_year,
            tickers=tickers,
            intervals=intervals,
            configs=configs,
            windows=windows,
        )

        targets = [
            EvaluationTarget(
                ticker=ticker,
                data_ticker=normalize_ticker(resolve_treasury_price_proxy_ticker(ticker)),
                interval=interval,
                window_id=window.window_id,
                duration=window.duration,
                start_date=window.start_date,
                end_date=window.end_date,
            )
            for ticker in tickers
            for interval in intervals
            for window in windows
        ]
        if limit_targets is not None:
            targets = targets[:limit_targets]

        total_possible = len(configs) * len(targets)
        processed_rows = _count_completed_eval_rows(conn, run_id)
        print(
            f"run_id={run_id} db={db_path} configs={len(configs)} "
            f"targets={len(targets)} possible_evals={total_possible} "
            f"already_recorded={processed_rows}"
        )

        for target in targets:
            done_ids = _existing_config_ids_for_target(conn, run_id, target)
            pending_configs = [
                config for config in configs if config.config_id not in done_ids
            ]
            if not pending_configs:
                continue

            loaded_frame, skip_reason = frame_loader(target)
            if skip_reason or loaded_frame is None:
                now = _utc_now()
                rows = [
                    {
                        "config_id": config.config_id,
                        "ticker": target.ticker,
                        "data_ticker": target.data_ticker,
                        "interval": target.interval,
                        "window_id": target.window_id,
                        "duration": target.duration,
                        "start_date": target.start_date,
                        "end_date": target.end_date,
                        "status": "skipped",
                        "skip_reason": skip_reason or "skipped_insufficient_history",
                        "score": None,
                        "net_profit_pct": None,
                        "max_drawdown_pct": None,
                        "total_trades": None,
                        "trades_per_year": None,
                        "error": "",
                        "completed_at": now,
                    }
                    for config in pending_configs
                ]
                for start_idx in range(0, len(rows), batch_size):
                    batch = rows[start_idx : start_idx + batch_size]
                    _insert_rows(conn, run_id, batch)
                    processed_rows += len(batch)
                continue

            for start_idx in range(0, len(pending_configs), batch_size):
                batch_configs = pending_configs[start_idx : start_idx + batch_size]
                try:
                    rows = _evaluate_configs_for_target(
                        configs=batch_configs,
                        target=target,
                        loaded_frame=loaded_frame,
                        drawdown_weight=drawdown_weight,
                        workers=workers,
                    )
                except Exception as exc:
                    now = _utc_now()
                    rows = [
                        {
                            "config_id": config.config_id,
                            "ticker": target.ticker,
                            "data_ticker": target.data_ticker,
                            "interval": target.interval,
                            "window_id": target.window_id,
                            "duration": target.duration,
                            "start_date": target.start_date,
                            "end_date": target.end_date,
                            "status": "error",
                            "skip_reason": "",
                            "score": None,
                            "net_profit_pct": None,
                            "max_drawdown_pct": None,
                            "total_trades": None,
                            "trades_per_year": None,
                            "error": str(exc),
                            "completed_at": now,
                        }
                        for config in batch_configs
                    ]

                _insert_rows(conn, run_id, rows)
                processed_rows += len(rows)

                if progress_every > 0 and processed_rows % progress_every == 0:
                    ranked = _rank_rows(
                        conn,
                        run_id=run_id,
                        max_round_trips_per_year=max_round_trips_per_year,
                        top_n=min(top_n, 5),
                    )
                    print(
                        f"progress recorded={processed_rows}/{total_possible} "
                        f"latest_target={target.ticker}:{target.interval}:{target.window_id}"
                    )
                    for rank, row in enumerate(ranked, start=1):
                        print(
                            f"  #{rank} {row['config_id']} "
                            f"score={row['avg_score']:.4f} "
                            f"net={row['avg_net_profit_pct']:.2f} "
                            f"dd={row['avg_max_drawdown_pct']:.2f} "
                            f"trades_per_year={row['avg_trades_per_year']:.2f} "
                            f"params={row['params']}"
                        )

            del loaded_frame
            gc.collect()

        ranked = _rank_rows(
            conn,
            run_id=run_id,
            max_round_trips_per_year=max_round_trips_per_year,
            top_n=top_n,
        )
        return {
            "run_id": run_id,
            "db_path": str(db_path),
            "configs": len(configs),
            "targets": len(targets),
            "recorded_evaluations": _count_completed_eval_rows(conn, run_id),
            "top_configs": ranked,
        }
    finally:
        conn.close()


def export_rankings(
    run_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    output_path: str | Path,
    max_round_trips_per_year: float = DEFAULT_MAX_ROUND_TRIPS_PER_YEAR,
    top_n: int = DEFAULT_TOP_N,
) -> str:
    conn = _connect(db_path)
    try:
        _init_db(conn)
        rows = _rank_rows(
            conn,
            run_id=run_id,
            max_round_trips_per_year=max_round_trips_per_year,
            top_n=top_n,
        )
    finally:
        conn.close()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "config_id",
                "completed_evals",
                "avg_score",
                "avg_net_profit_pct",
                "avg_max_drawdown_pct",
                "avg_trades_per_year",
                *list(RIBBON_GRID),
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "config_id": row["config_id"],
                    "completed_evals": row["completed_evals"],
                    "avg_score": row["avg_score"],
                    "avg_net_profit_pct": row["avg_net_profit_pct"],
                    "avg_max_drawdown_pct": row["avg_max_drawdown_pct"],
                    "avg_trades_per_year": row["avg_trades_per_year"],
                    **row["params"],
                }
            )
    return str(output)
