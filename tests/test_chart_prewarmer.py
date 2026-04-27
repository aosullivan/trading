"""Tests for lib/chart_prewarmer.py."""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lib.chart_prewarmer import (
    DEFAULT_CHART_STRATEGIES,
    ChartPrewarmer,
    build_watchlist_chart_artifacts,
)


class _StubClient:
    """Minimal stand-in for `flask.Flask.test_client()` return value."""

    def __init__(self):
        self.requests: list[str] = []

    def get(self, url: str):
        self.requests.append(url)
        return SimpleNamespace(status_code=200)


def _make_app_with_stub_client(client):
    app = MagicMock()
    app.test_client.return_value = client
    return app


def test_run_one_pass_hits_each_ticker_for_every_interval():
    stub_client = _StubClient()
    warmer = ChartPrewarmer(
        _make_app_with_stub_client(stub_client),
        load_watchlist_fn=lambda: ["AAA", "BBB"],
        intervals=("1d", "1wk"),
        strategies=("ribbon",),
        strategy_intervals=("1d",),
        per_request_sleep=0.0,
    )

    warmer._run_one_pass()

    assert len(stub_client.requests) == 6
    assert any("ticker=AAA" in url and "interval=1d" in url for url in stub_client.requests)
    assert any("ticker=AAA" in url and "interval=1wk" in url for url in stub_client.requests)
    assert any("ticker=BBB" in url and "interval=1d" in url for url in stub_client.requests)
    assert any("ticker=BBB" in url and "interval=1wk" in url for url in stub_client.requests)
    # Default view params are present on every URL.
    for url in stub_client.requests:
        assert "period=10" in url
        assert "multiplier=2.5" in url
        assert "start=2015-01-01" in url
        assert "prewarm=1" in url
    assert sum("candles_only=1" in url for url in stub_client.requests) == 4
    assert sum("strategy_only=1" in url and "include_shared=1" in url for url in stub_client.requests) == 2
    assert all("strategy=ribbon" in url for url in stub_client.requests if "strategy_only=1" in url)
    assert all("interval=1d" in url for url in stub_client.requests if "strategy_only=1" in url)


def test_build_watchlist_chart_artifacts_builds_full_ui_artifact_set():
    stub_client = _StubClient()
    summary = build_watchlist_chart_artifacts(
        _make_app_with_stub_client(stub_client),
        tickers=["AAA", "bbb"],
        intervals=("1d", "1wk"),
        strategies=("ribbon",),
        strategy_intervals=("1d",),
    )

    assert summary == {
        "tickers": 2,
        "strategies": 1,
        "requests": 6,
        "ok": 6,
        "failed": 0,
        "aborted": 0,
    }
    assert len(stub_client.requests) == 6
    assert all("prewarm=1" in url for url in stub_client.requests)
    assert all("cache_only=1" not in url for url in stub_client.requests)
    assert any("ticker=AAA" in url and "candles_only=1" in url for url in stub_client.requests)
    assert any("ticker=BBB" in url and "strategy_only=1" in url for url in stub_client.requests)
    assert sum("strategy_only=1" in url for url in stub_client.requests) == 2


def test_build_watchlist_chart_artifacts_defaults_to_all_ui_strategies_on_daily_and_weekly():
    stub_client = _StubClient()
    summary = build_watchlist_chart_artifacts(
        _make_app_with_stub_client(stub_client),
        tickers=["AAA"],
        intervals=("1d", "1wk"),
    )

    assert summary == {
        "tickers": 1,
        "strategies": len(DEFAULT_CHART_STRATEGIES),
        "requests": 2 + (2 * len(DEFAULT_CHART_STRATEGIES)),
        "ok": 2 + (2 * len(DEFAULT_CHART_STRATEGIES)),
        "failed": 0,
        "aborted": 0,
    }
    for strategy in DEFAULT_CHART_STRATEGIES:
        assert any(
            f"strategy={strategy}" in url and "interval=1d" in url
            for url in stub_client.requests
        )
        assert any(
            f"strategy={strategy}" in url and "interval=1wk" in url
            for url in stub_client.requests
        )


def test_build_watchlist_chart_artifacts_counts_failed_responses():
    class _FailingClient:
        def __init__(self):
            self.requests = []

        def get(self, url):
            self.requests.append(url)
            return SimpleNamespace(status_code=500)

    stub_client = _FailingClient()
    summary = build_watchlist_chart_artifacts(
        _make_app_with_stub_client(stub_client),
        tickers=["AAA"],
        intervals=("1d",),
        strategies=("ribbon",),
    )

    assert summary == {
        "tickers": 1,
        "strategies": 1,
        "requests": 2,
        "ok": 0,
        "failed": 2,
        "aborted": 0,
    }


def test_build_watchlist_chart_artifacts_aborts_repeated_failures():
    class _FailingClient:
        def get(self, url):
            return SimpleNamespace(status_code=500)

    summary = build_watchlist_chart_artifacts(
        _make_app_with_stub_client(_FailingClient()),
        tickers=["AAA", "BBB", "CCC"],
        intervals=("1d",),
        strategies=("ribbon",),
        max_consecutive_failures=3,
    )

    assert summary == {
        "tickers": 3,
        "strategies": 1,
        "requests": 3,
        "ok": 0,
        "failed": 3,
        "aborted": 1,
    }


def test_run_one_pass_waits_for_interactive_idle():
    stub_client = _StubClient()
    calls = 0

    def interactive_recently():
        nonlocal calls
        calls += 1
        return calls == 1

    warmer = ChartPrewarmer(
        _make_app_with_stub_client(stub_client),
        load_watchlist_fn=lambda: ["AAA"],
        intervals=("1d",),
        strategies=("ribbon",),
        per_request_sleep=0.0,
        interactive_recently_fn=interactive_recently,
        idle_poll_seconds=0.001,
    )

    warmer._run_one_pass()

    assert calls >= 2
    assert len(stub_client.requests) == 2


def test_run_one_pass_short_circuits_when_stopped():
    stub_client = _StubClient()
    warmer = ChartPrewarmer(
        _make_app_with_stub_client(stub_client),
        load_watchlist_fn=lambda: ["AAA", "BBB", "CCC"],
        intervals=("1d",),
        strategies=("ribbon",),
        per_request_sleep=0.0,
    )
    warmer._stop.set()  # pre-stopped

    warmer._run_one_pass()

    assert stub_client.requests == []


def test_run_one_pass_swallows_load_watchlist_errors():
    def _bad():
        raise RuntimeError("disk gone")

    warmer = ChartPrewarmer(
        _make_app_with_stub_client(_StubClient()),
        load_watchlist_fn=_bad,
        strategies=("ribbon",),
        per_request_sleep=0.0,
    )
    # Must not raise.
    warmer._run_one_pass()


def test_run_one_pass_swallows_client_errors_and_continues():
    class _FlakyClient:
        def __init__(self):
            self.calls = 0
        def get(self, url):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("nope")
            return SimpleNamespace(status_code=200)

    flaky = _FlakyClient()
    warmer = ChartPrewarmer(
        _make_app_with_stub_client(flaky),
        load_watchlist_fn=lambda: ["AAA", "BBB"],
        intervals=("1d",),
        strategies=("ribbon",),
        per_request_sleep=0.0,
    )

    warmer._run_one_pass()

    # First call raised, the paired strategy request and next ticker should still fire.
    assert flaky.calls == 4


def test_run_one_pass_skips_prewarm_when_user_is_active():
    stub_client = _StubClient()
    warmer = ChartPrewarmer(
        _make_app_with_stub_client(stub_client),
        load_watchlist_fn=lambda: ["AAA"],
        intervals=("1d",),
        strategies=("ribbon",),
        per_request_sleep=0.0,
        interactive_recently_fn=lambda: True,
    )

    warmer._prewarm_one(stub_client, "AAA", "1d")

    assert stub_client.requests == []


def test_run_one_pass_stops_between_candle_and_strategy_when_user_becomes_active():
    stub_client = _StubClient()
    calls = 0

    def interactive_recently():
        nonlocal calls
        calls += 1
        return calls >= 2

    warmer = ChartPrewarmer(
        _make_app_with_stub_client(stub_client),
        load_watchlist_fn=lambda: ["AAA"],
        intervals=("1d",),
        strategies=("ribbon",),
        per_request_sleep=0.0,
        interactive_recently_fn=interactive_recently,
    )

    warmer._prewarm_one(stub_client, "AAA", "1d")

    assert len(stub_client.requests) == 1
    assert "candles_only=1" in stub_client.requests[0]


def test_start_then_stop_cleanly_within_one_second():
    warmer = ChartPrewarmer(
        _make_app_with_stub_client(_StubClient()),
        load_watchlist_fn=lambda: [],
        initial_delay=10.0,  # so it spends its life in .wait()
        loop_seconds=10,
        per_request_sleep=0.0,
    )
    warmer.start()
    assert warmer._thread is not None and warmer._thread.is_alive()

    start = time.perf_counter()
    warmer.stop()
    warmer._thread.join(timeout=1.0)
    assert not warmer._thread.is_alive()
    assert time.perf_counter() - start < 1.0


def test_start_is_idempotent():
    warmer = ChartPrewarmer(
        _make_app_with_stub_client(_StubClient()),
        load_watchlist_fn=lambda: [],
        initial_delay=10.0,
        loop_seconds=10,
    )
    warmer.start()
    first_thread = warmer._thread
    warmer.start()  # second call should not spawn another
    assert warmer._thread is first_thread
    warmer.stop()
    warmer._thread.join(timeout=1.0)
