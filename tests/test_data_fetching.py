import io
import json
import time
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
