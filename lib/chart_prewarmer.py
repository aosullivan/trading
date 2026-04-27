"""Background daemon that pre-populates the chart payload cache.

The chart compute path is expensive (~10-15s for a fresh ticker) because of
the indicator bundle + ~20 strategy backtests. The caching layer in
routes/chart.py makes warm requests < 300ms, but that only helps AFTER a
ticker has been requested at least once per restart.

This module runs a background daemon thread that, on startup and every hour
thereafter, walks the user's watchlist and invokes the same fast chart paths
the browser uses: `candles_only=1` for each prewarm interval, plus
`strategy_only=1&include_shared=1` payloads for the configured strategies.
The route writes its own disk cache as a side effect, so after one full pass
every watchlist ticker click can paint candles immediately and fill the
selected overlays/backtests from cache.

Design notes:
- Uses `app.test_client()` rather than loopback HTTP so we never queue
  behind the user's own requests in Werkzeug's accept loop.
- Runs as a daemon thread: never blocks Flask shutdown.
- Yields briefly between requests so interactive user clicks still get
  GIL time.
- Stop event allows clean shutdown in tests.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Iterable
from urllib.parse import quote

log = logging.getLogger(__name__)

_PREWARM_INTERVALS: tuple[str, ...] = ("1d", "1wk")
_DEFAULT_LOOP_SECONDS = 3600  # one full pass, then wait an hour
_DEFAULT_INITIAL_DELAY = 45.0
_DEFAULT_PER_REQUEST_SLEEP = 0.25
_DEFAULT_IDLE_POLL_SECONDS = 5.0
_DEFAULT_STRATEGY = "ribbon"
DEFAULT_CHART_STRATEGIES: tuple[str, ...] = (
    "ribbon",
    "corpus_trend",
    "corpus_trend_layered",
    "cci_hysteresis",
    "polymarket",
    "trend_sr_macro_v1",
    "weekly_core_overlay_v1",
    "supertrend_i",
    "ema_9_26",
    "semis_persist_v1",
    "bb_breakout",
    "ema_crossover",
    "cci_trend",
)
_DEFAULT_STRATEGY_INTERVALS: tuple[str, ...] = ("1d", "1wk")


def _normalize_strategies(strategies: Iterable[str] | None) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for strategy in strategies or ():
        key = str(strategy or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return tuple(normalized)


def _chart_artifact_urls(
    ticker: str,
    interval: str,
    *,
    strategies: Iterable[str] | None = (_DEFAULT_STRATEGY,),
    strategy_intervals: Iterable[str] = ("1d",),
    start: str = "2015-01-01",
    period: str = "10",
    multiplier: str = "2.5",
    cache_only: bool = False,
) -> list[str]:
    base_url = (
        "/api/chart?ticker=" + quote(str(ticker).upper())
        + "&interval=" + quote(str(interval))
        + "&start=" + quote(str(start))
        + "&period=" + quote(str(period))
        + "&multiplier=" + quote(str(multiplier))
    )
    suffix = "&prewarm=1"
    if cache_only:
        suffix += "&cache_only=1"
    urls = [base_url + "&candles_only=1" + suffix]
    if str(interval) in {str(item) for item in strategy_intervals}:
        normalized_strategies = _normalize_strategies(strategies)
        if not normalized_strategies:
            normalized_strategies = (_DEFAULT_STRATEGY,)
    else:
        normalized_strategies = ()
    for strategy in normalized_strategies:
        urls.append(
            base_url
            + "&strategy_only=1&include_shared=1&strategy="
            + quote(str(strategy))
            + suffix
        )
    return urls


def build_watchlist_chart_artifacts(
    app,
    *,
    tickers: Iterable[str] | None = None,
    load_watchlist_fn=None,
    intervals: Iterable[str] = _PREWARM_INTERVALS,
    strategies: Iterable[str] = DEFAULT_CHART_STRATEGIES,
    strategy_intervals: Iterable[str] = _DEFAULT_STRATEGY_INTERVALS,
    per_request_sleep: float = 0.0,
    max_consecutive_failures: int | None = 9,
) -> dict[str, int]:
    """Synchronously build the chart artifacts used by the watchlist UI.

    This is the "bake the known universe" path: it intentionally performs real
    cache misses so the resulting candle + selected-strategy payloads are
    persisted to the chart payload cache for future app launches.
    """
    if tickers is None:
        if load_watchlist_fn is None:
            from routes.watchlist import load_watchlist as _load
            load_watchlist_fn = _load
        tickers = load_watchlist_fn() or []

    normalized_tickers = [
        str(ticker).upper().strip()
        for ticker in tickers
        if ticker and str(ticker).strip()
    ]
    normalized_strategies = _normalize_strategies(strategies)
    normalized_strategy_intervals = tuple(str(item) for item in strategy_intervals)
    summary = {
        "tickers": len(normalized_tickers),
        "strategies": len(normalized_strategies),
        "requests": 0,
        "ok": 0,
        "failed": 0,
        "aborted": 0,
    }
    client = app.test_client()
    consecutive_failures = 0
    for ticker in normalized_tickers:
        for interval in tuple(intervals):
            for url in _chart_artifact_urls(
                ticker,
                interval,
                strategies=normalized_strategies,
                strategy_intervals=normalized_strategy_intervals,
            ):
                if (
                    max_consecutive_failures is not None
                    and consecutive_failures >= max_consecutive_failures
                ):
                    summary["aborted"] = 1
                    log.warning(
                        "chart artifact build aborted after %s consecutive failures",
                        consecutive_failures,
                    )
                    return summary
                summary["requests"] += 1
                try:
                    resp = client.get(url)
                    if 200 <= int(getattr(resp, "status_code", 500)) < 400:
                        summary["ok"] += 1
                        consecutive_failures = 0
                    else:
                        summary["failed"] += 1
                        consecutive_failures += 1
                        log.warning(
                            "chart artifact build failed status=%s ticker=%s interval=%s url=%s",
                            getattr(resp, "status_code", "?"),
                            ticker,
                            interval,
                            url,
                        )
                except Exception:
                    summary["failed"] += 1
                    consecutive_failures += 1
                    log.exception(
                        "chart artifact build failed ticker=%s interval=%s url=%s",
                        ticker,
                        interval,
                        url,
                    )
                if per_request_sleep:
                    time.sleep(float(per_request_sleep))
    return summary


class ChartPrewarmer:
    """Daemon that calls `/api/chart` for every watchlist ticker on a schedule."""

    def __init__(
        self,
        app,
        *,
        load_watchlist_fn=None,
        loop_seconds: int = _DEFAULT_LOOP_SECONDS,
        initial_delay: float = _DEFAULT_INITIAL_DELAY,
        per_request_sleep: float = _DEFAULT_PER_REQUEST_SLEEP,
        intervals: Iterable[str] = _PREWARM_INTERVALS,
        strategies: Iterable[str] = DEFAULT_CHART_STRATEGIES,
        strategy_intervals: Iterable[str] = _DEFAULT_STRATEGY_INTERVALS,
        interactive_recently_fn=None,
        idle_poll_seconds: float = _DEFAULT_IDLE_POLL_SECONDS,
    ):
        self._app = app
        # Delay the import so the module is importable without Flask set up
        # (e.g. in tests that patch load_watchlist out).
        if load_watchlist_fn is None:
            from routes.watchlist import load_watchlist as _load
            load_watchlist_fn = _load
        self._load_watchlist = load_watchlist_fn
        self._loop_seconds = int(loop_seconds)
        self._initial_delay = float(initial_delay)
        self._per_request_sleep = float(per_request_sleep)
        self._intervals = tuple(intervals)
        self._strategies = _normalize_strategies(strategies)
        self._strategy_intervals = tuple(str(item) for item in strategy_intervals)
        if interactive_recently_fn is None:
            try:
                from routes.chart import chart_interactive_recently
                interactive_recently_fn = chart_interactive_recently
            except Exception:
                interactive_recently_fn = lambda: False
        self._interactive_recently = interactive_recently_fn
        self._idle_poll_seconds = float(idle_poll_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        thread = threading.Thread(
            target=self._loop,
            name="chart-prewarmer",
            daemon=True,
        )
        thread.start()
        self._thread = thread

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # Small delay so we don't contend with the user's first page load.
        if self._stop.wait(self._initial_delay):
            return
        while not self._stop.is_set():
            pass_started = time.perf_counter()
            self._run_one_pass()
            elapsed = time.perf_counter() - pass_started
            log.info("chart prewarmer pass finished in %.1fs", elapsed)
            if self._stop.wait(self._loop_seconds):
                return

    def _run_one_pass(self) -> None:
        try:
            tickers = list(self._load_watchlist() or [])
        except Exception:
            log.exception("chart prewarmer failed to load watchlist")
            return

        client = self._app.test_client()
        for ticker in tickers:
            if self._stop.is_set():
                return
            for interval in self._intervals:
                if self._stop.is_set():
                    return
                if not self._wait_for_interactive_idle():
                    return
                self._prewarm_one(client, ticker, interval)
                # Yield briefly so user clicks get fair GIL access.
                if self._stop.wait(self._per_request_sleep):
                    return

    def _wait_for_interactive_idle(self) -> bool:
        while not self._stop.is_set():
            try:
                if not self._interactive_recently():
                    return True
            except Exception:
                return True
            if self._stop.wait(self._idle_poll_seconds):
                return False
        return False

    def _prewarm_one(self, client, ticker: str, interval: str) -> None:
        for url in _chart_artifact_urls(
            ticker,
            interval,
            strategies=self._strategies,
            strategy_intervals=self._strategy_intervals,
        ):
            if self._stop.is_set():
                return
            try:
                if self._interactive_recently():
                    return
            except Exception:
                pass
            try:
                resp = client.get(url)
                # Touch status code so any lazy body stays referenced long enough
                # to exercise the caching paths; we don't need the body itself.
                _ = resp.status_code
            except Exception:
                log.exception(
                    "chart prewarmer request failed ticker=%s interval=%s url=%s",
                    ticker,
                    interval,
                    url,
                )
