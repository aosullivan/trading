"""Blob read-shim for chart strategy payloads.

When `TRIEDINGVIEW_BLOB_BASE_URL` is set, the chart route will try to fetch a
precomputed (trades, summary, equity_curve) tuple from Vercel Blob before
running the strategy's local backtest. This is the consumer side of the
Vercel cron at `api/prewarm-cron.py`; both sides agree on the Blob pathname
via `blob_strategy_path()`.

To enable locally:
  export TRIEDINGVIEW_BLOB_BASE_URL=https://<store_hash>.public.blob.vercel-storage.com

Unset (the default) → the helpers no-op; chart compute path is unchanged.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_BASE_URL = os.environ.get("TRIEDINGVIEW_BLOB_BASE_URL", "").rstrip("/")
_READ_TIMEOUT_SECONDS = float(os.environ.get("TRIEDINGVIEW_BLOB_READ_TIMEOUT", "2.0"))


def blob_token_from_signature(source_token: str) -> str:
    """Make a frame signature URL-safe for use in a Blob pathname.

    `_source_data_token()` returns strings like `sig:N:fts:lts:O:H:L:C:V` with
    colons that don't play nicely in URLs. Replace with dots; both writer
    (Vercel cron) and reader (this module) must agree on this transformation.
    """
    return (source_token or "").replace(":", ".").replace("/", "_")


def blob_strategy_path(ticker: str, interval: str, strategy_key: str, source_token: str) -> str:
    token = blob_token_from_signature(source_token)
    return f"strategy/{ticker}_{interval}_{strategy_key}_{token}.json"


def _build_url(pathname: str) -> str | None:
    if not _BASE_URL:
        return None
    return f"{_BASE_URL}/{pathname.lstrip('/')}"


def try_read_strategy_backtest(
    ticker: str,
    interval: str,
    strategy_key: str,
    source_token: str,
) -> tuple[list, dict, list] | None:
    """Fetch a precomputed backtest payload from Blob, or None on miss/error.

    Returns the `(trades, summary, equity_curve)` tuple the strategy backtest
    engines produce, so the caller can stub it into the existing chart code
    path without reshaping anything.
    """
    url = _build_url(
        blob_strategy_path(ticker, interval, strategy_key, source_token)
    )
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=_READ_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                return None
            payload: dict[str, Any] = json.loads(resp.read())
    except Exception:
        return None
    trades = payload.get("trades")
    summary = payload.get("summary")
    equity_curve = payload.get("equity_curve")
    if not isinstance(trades, list) or not isinstance(summary, dict) or not isinstance(equity_curve, list):
        return None
    return trades, summary, equity_curve
