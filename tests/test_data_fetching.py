import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pandas as pd

import lib.data_fetching as data_fetching
from lib.data_fetching import _fetch_treasury_yield_history, _quote_from_frame


def test_fetch_treasury_yield_history_supports_observation_date_column():
    csv_payload = (
        "observation_date,DGS1\n"
        "2026-03-30,3.71\n"
        "2026-03-31,3.68\n"
    )

    with (
        patch("lib.data_fetching._cache_get", return_value=None),
        patch("lib.data_fetching._cache_set"),
        patch(
            "lib.data_fetching.urllib.request.urlopen",
            return_value=io.BytesIO(csv_payload.encode("utf-8")),
        ),
    ):
        df = _fetch_treasury_yield_history("UST1Y")

    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert list(df.index.strftime("%Y-%m-%d")) == ["2026-03-30", "2026-03-31"]
    assert _quote_from_frame("UST1Y", df) == {
        "ticker": "UST1Y",
        "last": 3.68,
        "chg": -0.03,
        "chg_pct": -0.81,
    }


def test_cached_download_reuses_fresh_cache_when_requested_window_is_covered(tmp_path, monkeypatch):
    monkeypatch.setattr(data_fetching, "_DATA_CACHE_DIR", str(tmp_path))
    ticker = "AAPL"
    interval = "1d"
    cached_df = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0]},
        index=pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05"]),
    )
    cached_df.to_csv(data_fetching._disk_cache_path(ticker, interval))
    with open(data_fetching._meta_path(ticker, interval), "w") as handle:
        json.dump({"last_fetch": time.time()}, handle)

    def unexpected_download(*args, **kwargs):
        raise AssertionError("fresh covered cache should not refetch")

    monkeypatch.setattr(data_fetching, "_yf_rate_limited_download", unexpected_download)

    result = data_fetching.cached_download(
        ticker,
        start="2022-01-04",
        end="2022-01-05",
        interval=interval,
    )

    assert list(result.index.strftime("%Y-%m-%d")) == ["2022-01-04", "2022-01-05"]


def test_cached_download_refetches_when_fresh_cache_misses_requested_window(tmp_path, monkeypatch):
    monkeypatch.setattr(data_fetching, "_DATA_CACHE_DIR", str(tmp_path))
    ticker = "AAPL"
    interval = "1d"
    cached_df = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0]},
        index=pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]),
    )
    cached_df.to_csv(data_fetching._disk_cache_path(ticker, interval))
    with open(data_fetching._meta_path(ticker, interval), "w") as handle:
        json.dump({"last_fetch": time.time()}, handle)

    refetched_df = pd.DataFrame(
        {"Close": [103.0, 104.0, 105.0]},
        index=pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05"]),
    )
    calls = []

    def fake_download(*args, **kwargs):
        calls.append(kwargs)
        return refetched_df

    monkeypatch.setattr(data_fetching, "_yf_rate_limited_download", fake_download)

    result = data_fetching.cached_download(
        ticker,
        start="2022-01-03",
        end="2022-01-05",
        interval=interval,
    )

    assert calls
    assert calls[0]["start"] == "2020-01-07"
    assert list(result.index.strftime("%Y-%m-%d")) == ["2022-01-03", "2022-01-04", "2022-01-05"]
    assert result["Close"].tolist() == [103.0, 104.0, 105.0]


def test_cached_download_reuses_stale_cache_when_it_already_extends_past_requested_end(tmp_path, monkeypatch):
    monkeypatch.setattr(data_fetching, "_DATA_CACHE_DIR", str(tmp_path))
    ticker = "AAPL"
    interval = "1d"
    cached_df = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0, 103.0]},
        index=pd.to_datetime(["2025-12-29", "2025-12-30", "2025-12-31", "2026-01-02"]),
    )
    cached_df.to_csv(data_fetching._disk_cache_path(ticker, interval))
    with open(data_fetching._meta_path(ticker, interval), "w") as handle:
        json.dump({"last_fetch": 0}, handle)

    def unexpected_download(*args, **kwargs):
        raise AssertionError("covered stale cache should not attempt a fetch beyond requested end")

    monkeypatch.setattr(data_fetching, "_yf_rate_limited_download", unexpected_download)

    result = data_fetching.cached_download(
        ticker,
        start="2025-01-01",
        end="2025-12-31",
        interval=interval,
    )

    assert list(result.index.strftime("%Y-%m-%d")) == ["2025-12-29", "2025-12-30", "2025-12-31"]


def test_cached_download_reuses_same_day_latest_interval_cache_without_refetch(tmp_path, monkeypatch):
    monkeypatch.setattr(data_fetching, "_DATA_CACHE_DIR", str(tmp_path))
    ticker = "AAPL"
    interval = "1d"
    dates = pd.to_datetime(["2026-04-21", "2026-04-22", "2026-04-23"])
    cached_df = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0]},
        index=dates,
    )
    cached_df.to_csv(data_fetching._disk_cache_path(ticker, interval))
    with open(data_fetching._meta_path(ticker, interval), "w") as handle:
        json.dump({"last_fetch": time.time() - 3600}, handle)

    def unexpected_download(*args, **kwargs):
        raise AssertionError("same-day latest-bar cache should not refetch")

    monkeypatch.setattr(data_fetching, "_yf_rate_limited_download", unexpected_download)

    result = data_fetching.cached_download(
        ticker,
        start=dates[0].strftime("%Y-%m-%d"),
        interval=interval,
    )

    assert list(result.index) == list(dates)


def test_cached_download_returns_stale_latest_interval_cache_and_schedules_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(data_fetching, "_DATA_CACHE_DIR", str(tmp_path))
    ticker = "AAPL"
    interval = "1d"
    dates = pd.to_datetime(["2026-04-21", "2026-04-22", "2026-04-23"])
    cached_df = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0]},
        index=dates,
    )
    cached_df.to_csv(data_fetching._disk_cache_path(ticker, interval))
    with open(data_fetching._meta_path(ticker, interval), "w") as handle:
        json.dump({"last_fetch": time.time() - 7200}, handle)

    scheduled = []

    def fake_schedule(refresh_ticker, refresh_kwargs):
        scheduled.append((refresh_ticker, refresh_kwargs))

    def unexpected_download(*args, **kwargs):
        raise AssertionError("stale latest-bar cache should return immediately")

    monkeypatch.setattr(data_fetching, "_schedule_lazy_cache_refresh", fake_schedule)
    monkeypatch.setattr(data_fetching, "_yf_rate_limited_download", unexpected_download)

    result = data_fetching.cached_download(
        ticker,
        start=dates[0].strftime("%Y-%m-%d"),
        interval=interval,
    )

    assert list(result.index) == list(dates)
    assert scheduled == [
        (
            ticker,
            {
                "start": dates[0].strftime("%Y-%m-%d"),
                "interval": interval,
            },
        )
    ]


def test_cached_download_does_not_rewrite_csv_when_refresh_returns_no_new_bars(tmp_path, monkeypatch):
    monkeypatch.setattr(data_fetching, "_DATA_CACHE_DIR", str(tmp_path))
    ticker = "AAPL"
    interval = "1d"
    cached_df = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0]},
        index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
    )
    csv_path = data_fetching._disk_cache_path(ticker, interval)
    cached_df.to_csv(csv_path)
    with open(data_fetching._meta_path(ticker, interval), "w") as handle:
        json.dump({"last_fetch": 0}, handle)
    original_mtime = os.path.getmtime(csv_path)

    monkeypatch.setattr(
        data_fetching,
        "_yf_rate_limited_download",
        lambda *args, **kwargs: pd.DataFrame(),
    )

    result = data_fetching.cached_download(
        ticker,
        start="2026-01-02",
        end="2026-01-10",
        interval=interval,
        allow_stale_latest=False,
    )

    assert result["Close"].tolist() == [100.0, 101.0, 102.0]
    assert os.path.getmtime(csv_path) == original_mtime
    with open(data_fetching._meta_path(ticker, interval)) as handle:
        meta = json.load(handle)
    assert meta["data_signature"] == data_fetching._frame_cache_signature(cached_df)


def test_cached_download_coalesces_concurrent_identical_period_requests(monkeypatch):
    ticker = "SINGLEFLIGHT"
    calls = []
    df = pd.DataFrame(
        {"Close": [100.0, 101.0]},
        index=pd.to_datetime(["2026-01-02", "2026-01-05"]),
    )

    def fake_download(*args, **kwargs):
        calls.append((args, kwargs))
        time.sleep(0.05)
        return df

    monkeypatch.setattr(data_fetching, "_yf_rate_limited_download", fake_download)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: data_fetching.cached_download(
                    ticker,
                    period="5d",
                    interval="1d",
                    progress=False,
                ),
                range(2),
            )
        )

    assert len(calls) == 1
    assert all(result.equals(df) for result in results)


def test_cached_download_serves_stale_disk_cache_during_yf_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(data_fetching, "_DATA_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(data_fetching, "_yf_cooldown_active", lambda: True)
    ticker = "AAPL"
    interval = "1d"
    cached_df = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0]},
        index=pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05"]),
    )
    cached_df.to_csv(data_fetching._disk_cache_path(ticker, interval))
    with open(data_fetching._meta_path(ticker, interval), "w") as handle:
        json.dump({"last_fetch": 0}, handle)

    def unexpected_download(*args, **kwargs):
        raise AssertionError("cooldown should not call Yahoo")

    monkeypatch.setattr(data_fetching, "_yf_rate_limited_download", unexpected_download)

    result = data_fetching.cached_download(
        ticker,
        start="2022-01-04",
        interval=interval,
    )

    assert list(result.index.strftime("%Y-%m-%d")) == ["2022-01-04", "2022-01-05"]


def test_cached_download_returns_stale_disk_cache_after_rate_limit_error(tmp_path, monkeypatch):
    monkeypatch.setattr(data_fetching, "_DATA_CACHE_DIR", str(tmp_path))
    ticker = "AAPL"
    interval = "1d"
    cached_df = pd.DataFrame(
        {"Close": [100.0, 101.0]},
        index=pd.to_datetime(["2022-01-03", "2022-01-04"]),
    )
    cached_df.to_csv(data_fetching._disk_cache_path(ticker, interval))
    with open(data_fetching._meta_path(ticker, interval), "w") as handle:
        json.dump({"last_fetch": 0}, handle)

    def rate_limited(*args, **kwargs):
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(data_fetching, "_yf_rate_limited_download", rate_limited)

    result = data_fetching.cached_download(
        ticker,
        start="2022-01-03",
        interval=interval,
    )

    assert result["Close"].tolist() == [100.0, 101.0]
