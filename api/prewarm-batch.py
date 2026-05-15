"""Vercel function spike: fetch one ticker, run supertrend_i, write JSON to Blob.

End-to-end verification of the offload pattern:
  1. Fetch OHLCV via yfinance (proves yfinance works in a Vercel function).
  2. Run the same `lib/` code the local app uses (proves the bundled lib/ imports).
  3. Write the strategy payload to Vercel Blob (proves the storage round-trip).

Call as:
  GET /api/prewarm-batch?ticker=AAPL&interval=1d&start=2015-01-01
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Make the repo-root `lib/` importable. Vercel ships it via `includeFiles` in
# vercel.json so this resolves to /var/task/lib at runtime.
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

import pandas as pd  # noqa: E402
import vercel_blob  # noqa: E402
import yfinance as yf  # noqa: E402

from lib.backtesting import backtest_direction_vectorized  # noqa: E402
from lib.technical_indicators import (  # noqa: E402
    SUPERTREND_MULTIPLIER,
    SUPERTREND_PERIOD,
    compute_supertrend_i,
)


def _fetch_ohlcv(ticker: str, interval: str, start: str) -> pd.DataFrame:
    df = yf.download(
        ticker,
        start=start,
        interval=interval,
        progress=False,
        threads=False,
        auto_adjust=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        raise ValueError(f"yfinance returned empty frame for {ticker} {interval}")
    return df


def _data_signature(df: pd.DataFrame) -> str:
    last_idx = pd.Timestamp(df.index[-1])
    last_close = float(df["Close"].iloc[-1])
    return f"{len(df)}.{int(last_idx.timestamp())}.{last_close:.4f}"


def _blob_path(ticker: str, interval: str, strategy: str, token: str) -> str:
    return f"strategy/{ticker}_{interval}_{strategy}_{token}.json"


def _run_spike(ticker: str, interval: str, start: str) -> dict:
    timings: dict[str, int] = {}
    t0 = time.perf_counter()

    df = _fetch_ohlcv(ticker, interval, start)
    timings["fetch_ms"] = int((time.perf_counter() - t0) * 1000)

    t1 = time.perf_counter()
    _supertrend, direction = compute_supertrend_i(
        df, period=SUPERTREND_PERIOD, multiplier=SUPERTREND_MULTIPLIER
    )
    trades, summary, equity_curve = backtest_direction_vectorized(
        df, direction, start_in_position=False, prior_direction=None
    )
    timings["compute_ms"] = int((time.perf_counter() - t1) * 1000)

    token = _data_signature(df)
    payload = {
        "meta": {
            "ticker": ticker,
            "interval": interval,
            "strategy": "supertrend_i",
            "source_token": token,
            "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rows": len(df),
        },
        "summary": summary,
        "trades": trades,
        "equity_curve": equity_curve,
    }

    t2 = time.perf_counter()
    pathname = _blob_path(ticker, interval, "supertrend_i", token)
    body = json.dumps(payload).encode("utf-8")
    blob_result = vercel_blob.put(
        pathname,
        body,
        {
            "access": "private",
            "contentType": "application/json",
            "addRandomSuffix": "false",
            "allowOverwrite": "true",
            "cacheControlMaxAge": "3600",
        },
    )
    timings["blob_write_ms"] = int((time.perf_counter() - t2) * 1000)
    timings["total_ms"] = int((time.perf_counter() - t0) * 1000)

    return {
        "ok": True,
        "ticker": ticker,
        "interval": interval,
        "strategy": "supertrend_i",
        "source_token": token,
        "rows": len(df),
        "trade_count": len(trades),
        "summary_keys": sorted(summary.keys()),
        "summary_total_pnl": summary.get("total_pnl"),
        "summary_win_rate": summary.get("win_rate"),
        "blob_url": blob_result.get("url"),
        "blob_pathname": blob_result.get("pathname"),
        "timings_ms": timings,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            query = parse_qs(urlparse(self.path).query)
            ticker = (query.get("ticker", ["AAPL"])[0] or "AAPL").upper().strip()
            interval = query.get("interval", ["1d"])[0] or "1d"
            start = query.get("start", ["2015-01-01"])[0] or "2015-01-01"

            if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
                self._respond(500, {
                    "error": "BLOB_READ_WRITE_TOKEN env var is not set",
                    "hint": "Create a Vercel Blob store and link it to this project.",
                })
                return

            result = _run_spike(ticker, interval, start)
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
