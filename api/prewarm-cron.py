"""Hourly cron: precompute strategy backtests for the watchlist and write to Blob.

Replaces the local `ChartPrewarmer` daemon's strategy-payload work. For each
ticker in `watchlist.json` (shipped via vercel.json includeFiles) the function
fetches OHLCV once per interval, then computes each strategy's direction +
backtest and writes one JSON payload to the Blob store per
(ticker, interval, strategy) tuple. Path convention matches the local cache
key so a future `chart.py` read-shim can fall through to Blob transparently.

Scoped to direction-engine strategies that compute purely from OHLCV. Skips
strategies that need extra data sources (polymarket, trend_sr_macro_v1,
weekly_core_overlay_v1) or non-DIRECTION engines (ribbon, corpus_trend).
Expand `PREWARM_STRATEGIES` once the wire is proven.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

import pandas as pd  # noqa: E402
import vercel_blob  # noqa: E402
import yfinance as yf  # noqa: E402

from lib.backtesting import backtest_direction_vectorized  # noqa: E402
from lib.strategies import get_strategy, register_all  # noqa: E402
from lib.strategies._types import StrategyContext  # noqa: E402

register_all()

PREWARM_STRATEGIES: tuple[str, ...] = (
    "supertrend_i",
    "ema_9_26",
    "ema_crossover",
)
PREWARM_INTERVALS: tuple[str, ...] = ("1d", "1wk")
PREWARM_START: str = "2015-01-01"
MAX_WORKERS: int = 4
# Hobby plan caps function duration at 60s. With 4 workers, ~30 tickers fits.
# Pro + Fluid Compute can take 800s — bump or remove when upgrading.
DEFAULT_LIMIT: int = 30


def _load_watchlist() -> list[str]:
    path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "watchlist.json")
    )
    with open(path) as f:
        tickers = json.load(f)
    return [str(t).upper().strip() for t in tickers if t and str(t).strip()]


def _fetch_ohlcv(ticker: str, interval: str) -> pd.DataFrame:
    df = yf.download(
        ticker,
        start=PREWARM_START,
        interval=interval,
        progress=False,
        threads=False,
        auto_adjust=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _data_signature(df: pd.DataFrame) -> str:
    last_idx = pd.Timestamp(df.index[-1])
    last_close = float(df["Close"].iloc[-1])
    return f"{len(df)}.{int(last_idx.timestamp())}.{last_close:.4f}"


def _blob_path(ticker: str, interval: str, strategy: str, token: str) -> str:
    return f"strategy/{ticker}_{interval}_{strategy}_{token}.json"


def _write_payload(ticker, interval, strategy_key, df, token):
    strategy = get_strategy(strategy_key)
    result = strategy.compute(StrategyContext(df=df, ticker=ticker))
    trades, summary, equity_curve = backtest_direction_vectorized(
        df, result.direction, start_in_position=False, prior_direction=None
    )
    payload = {
        "meta": {
            "ticker": ticker,
            "interval": interval,
            "strategy": strategy_key,
            "source_token": token,
            "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rows": len(df),
        },
        "summary": summary,
        "trades": trades,
        "equity_curve": equity_curve,
    }
    pathname = _blob_path(ticker, interval, strategy_key, token)
    vercel_blob.put(
        pathname,
        json.dumps(payload).encode("utf-8"),
        {
            "contentType": "application/json",
            "addRandomSuffix": "false",
            "allowOverwrite": "true",
            "cacheControlMaxAge": "3600",
        },
    )
    return pathname


def _process_ticker(ticker: str) -> dict:
    written: list[str] = []
    failed: list[dict] = []
    for interval in PREWARM_INTERVALS:
        try:
            df = _fetch_ohlcv(ticker, interval)
        except Exception as exc:
            failed.append({"interval": interval, "stage": "fetch", "error": str(exc)[:200]})
            continue
        if df.empty:
            failed.append({"interval": interval, "stage": "fetch", "error": "empty_frame"})
            continue
        token = _data_signature(df)
        for strategy_key in PREWARM_STRATEGIES:
            try:
                pathname = _write_payload(ticker, interval, strategy_key, df, token)
                written.append(pathname)
            except Exception as exc:
                failed.append({
                    "interval": interval,
                    "strategy": strategy_key,
                    "error": str(exc)[:200],
                })
    return {"ticker": ticker, "written": written, "failed": failed}


def _run_prewarm(limit: int | None = None) -> dict:
    started_at = time.perf_counter()
    tickers = _load_watchlist()
    effective_limit = limit if (limit is not None and limit > 0) else DEFAULT_LIMIT
    tickers = tickers[:effective_limit]
    total_written = 0
    total_failed = 0
    error_samples: list[dict] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_process_ticker, t): t for t in tickers}
        for fut in as_completed(futures):
            result = fut.result()
            total_written += len(result["written"])
            total_failed += len(result["failed"])
            if result["failed"] and len(error_samples) < 10:
                error_samples.append({
                    "ticker": result["ticker"],
                    "failures": result["failed"][:3],
                })

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    return {
        "ok": True,
        "tickers": len(tickers),
        "strategies": list(PREWARM_STRATEGIES),
        "intervals": list(PREWARM_INTERVALS),
        "payloads_written": total_written,
        "payloads_failed": total_failed,
        "error_samples": error_samples,
        "elapsed_ms": elapsed_ms,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        cron_secret = os.environ.get("CRON_SECRET")
        auth = self.headers.get("authorization", "")
        if cron_secret and auth != f"Bearer {cron_secret}":
            self._respond(401, {"error": "Unauthorized — invalid CRON_SECRET"})
            return

        try:
            query = parse_qs(urlparse(self.path).query)
            limit_raw = query.get("limit", [None])[0]
            limit = int(limit_raw) if limit_raw else None
            result = _run_prewarm(limit=limit)
            self._respond(200, result)
        except Exception as exc:
            self._respond(500, {
                "error": str(exc),
                "type": type(exc).__name__,
                "trace": traceback.format_exc(limit=8),
            })

    def _respond(self, status: int, body: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body, default=str).encode("utf-8"))
