"""Tests for Flask API routes."""

import json
import time
from unittest.mock import patch, MagicMock

import pandas as pd
import numpy as np
import pytest

from lib.backtesting import build_weekly_confirmed_ribbon_direction
import routes.chart as chart_module
from routes.chart import _align_weekly_direction_to_daily, _carry_neutral_direction


class TestIndexRoute:
    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"chart-container" in resp.data

    def test_backtest_page_returns_html(self, client):
        resp = client.get("/backtest")
        assert resp.status_code == 200
        assert b"Backtest Report" in resp.data
        assert b"strategy-select" in resp.data


class TestChartHelpers:
    def test_carry_neutral_direction_holds_last_nonzero_state(self):
        direction = pd.Series([0, 1, 0, 0, -1, 0, 1, 0])

        carried = _carry_neutral_direction(direction)

        assert carried.tolist() == [0, 1, 1, 1, -1, -1, 1, 1]

    def test_weekly_alignment_does_not_backfill_into_pre_signal_daily_bars(self):
        idx = pd.date_range("2025-01-01", periods=6, freq="D")
        daily_direction = pd.Series([1, 1, 1, 1, 1, 1], index=idx)
        weekly_direction = pd.Series([1], index=[idx[4]])

        aligned_weekly = _align_weekly_direction_to_daily(weekly_direction, idx)
        confirmed = build_weekly_confirmed_ribbon_direction(daily_direction, aligned_weekly)

        assert aligned_weekly.tolist() == [0, 0, 0, 0, 1, 1]
        assert confirmed.tolist() == [0, 0, 0, 0, 1, 1]


class TestWatchlistAPI:
    def test_get_watchlist(self, client):
        resp = client.get("/api/watchlist")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert "AAPL" in data
        assert "TSLA" in data

    def test_add_ticker(self, client):
        resp = client.post(
            "/api/watchlist",
            json={"ticker": "GOOG"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "GOOG" in data

    def test_add_duplicate_ticker(self, client):
        client.post("/api/watchlist", json={"ticker": "AAPL"})
        resp = client.get("/api/watchlist")
        data = resp.get_json()
        assert data.count("AAPL") == 1

    def test_add_empty_ticker(self, client):
        resp = client.post("/api/watchlist", json={"ticker": ""})
        assert resp.status_code == 400

    def test_add_lowercase_gets_uppercased(self, client):
        resp = client.post("/api/watchlist", json={"ticker": "msft"})
        data = resp.get_json()
        assert "MSFT" in data

    def test_remove_ticker(self, client):
        resp = client.delete(
            "/api/watchlist",
            json={"ticker": "AAPL"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "AAPL" not in data

    def test_remove_nonexistent_ticker(self, client):
        resp = client.delete("/api/watchlist", json={"ticker": "ZZZZ"})
        assert resp.status_code == 200

    @patch("lib.cache.yf.download")
    def test_watchlist_quotes_support_treasury_price_proxies(self, mock_download, client):
        import routes.watchlist as watchlist_module

        with open(watchlist_module.WATCHLIST_FILE, "w") as f:
            json.dump(["UST10Y"], f)

        dates = pd.bdate_range("2024-01-01", periods=5)
        values = np.array([92.1, 92.3, 92.2, 92.4, 92.8])
        mock_download.return_value = pd.DataFrame(
            {
                "Open": values - 0.1,
                "High": values + 0.2,
                "Low": values - 0.2,
                "Close": values,
                "Volume": np.full(len(values), 1_000_000),
            },
            index=dates,
        )

        resp = client.get("/api/watchlist/quotes")
        assert resp.status_code == 200
        data = resp.get_json()
        mock_download.assert_called_once()
        assert mock_download.call_args.args[0] == ["IEF"]
        assert data == [{"ticker": "UST10Y", "last": 92.8, "chg": 0.4, "chg_pct": 0.43}]

    @patch("lib.cache.yf.download")
    def test_watchlist_quotes_fall_back_to_single_ticker_fetches_when_bulk_download_fails(
        self, mock_download, client
    ):
        import routes.watchlist as watchlist_module

        with open(watchlist_module.WATCHLIST_FILE, "w") as f:
            json.dump(["AAPL", "TSLA"], f)

        dates = pd.bdate_range("2024-01-01", periods=5)

        def make_df(closes):
            closes = np.array(closes, dtype=float)
            return pd.DataFrame(
                {
                    "Open": closes - 0.5,
                    "High": closes + 1,
                    "Low": closes - 1,
                    "Close": closes,
                    "Volume": np.full(len(closes), 1_000_000),
                },
                index=dates,
            )

        def side_effect(tickers, **kwargs):
            if isinstance(tickers, list):
                raise RuntimeError("unable to open database file")
            if tickers == "AAPL":
                return make_df([190, 191, 192, 193, 194])
            if tickers == "TSLA":
                return make_df([240, 242, 241, 244, 246])
            raise AssertionError(f"Unexpected ticker request: {tickers}")

        mock_download.side_effect = side_effect

        resp = client.get("/api/watchlist/quotes")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == [
            {"ticker": "AAPL", "last": 194.0, "chg": 1.0, "chg_pct": 0.52},
            {"ticker": "TSLA", "last": 246.0, "chg": 2.0, "chg_pct": 0.82},
        ]

    def test_watchlist_trends_returns_loading_then_cached_rows(self, client):
        cold_rows = [
            {"ticker": "AAPL", "daily": {}, "weekly": {}},
            {"ticker": "TSLA", "daily": {}, "weekly": {}},
        ]
        rows = [
            {
                "ticker": "AAPL",
                "daily": {"ribbon": {"date": "2024-03-15", "dir": "bullish"}},
                "weekly": {"ribbon": {"date": "2024-03-08", "dir": "bullish"}},
            },
            {
                "ticker": "TSLA",
                "daily": {"ribbon": {"date": "2024-03-14", "dir": "bearish"}},
                "weekly": {"ribbon": {"date": "2024-02-23", "dir": "bearish"}},
            },
        ]

        with patch("routes.watchlist._build_watchlist_trends", return_value=rows) as mock_build:
            cold = client.get("/api/watchlist/trends")
            assert cold.status_code == 200
            assert cold.get_json() == {"items": cold_rows, "loading": True, "stale": False}

            data = {}
            for _ in range(30):
                warm = client.get("/api/watchlist/trends")
                assert warm.status_code == 200
                data = warm.get_json()
                if data["items"] == rows and data["loading"] is False:
                    break
                time.sleep(0.01)

            assert data["items"] == rows
            assert data["loading"] is False
            assert data["stale"] is False
            mock_build.assert_called_once()

    def test_watchlist_trends_returns_disk_snapshots_on_cold_memory_cache(self, client):
        import routes.watchlist as watchlist_module

        snapshot_row = {
            "ticker": "AAPL",
            "daily": {"ribbon": {"date": "2024-03-15", "dir": "bullish"}},
            "weekly": {"ribbon": {"date": "2024-03-08", "dir": "bullish"}},
        }
        watchlist_module._save_disk_trend_row("AAPL", "2024-03-15", "2024-03-08", snapshot_row)

        with patch("routes.watchlist._build_watchlist_trends", return_value=[]):
            resp = client.get("/api/watchlist/trends")

        assert resp.status_code == 200
        assert resp.get_json() == {
            "items": [
                snapshot_row,
                {"ticker": "TSLA", "daily": {}, "weekly": {}},
            ],
            "loading": True,
            "stale": False,
        }

    def test_watchlist_trends_handles_malformed_rows(self, client):
        malformed = [
            {"ticker": "AAPL", "daily": {}, "weekly": {}},
            {"ticker": "TSLA", "daily": {"ribbon": {"date": None, "dir": None}}, "weekly": {}},
        ]

        with patch("routes.watchlist._build_watchlist_trends", return_value=malformed):
            client.get("/api/watchlist/trends")

            data = {}
            for _ in range(30):
                resp = client.get("/api/watchlist/trends")
                assert resp.status_code == 200
                data = resp.get_json()
                if data["items"] == malformed and data["loading"] is False:
                    break
                time.sleep(0.01)

            assert data["items"] == malformed
            assert data["loading"] is False
            assert data["stale"] is False

    def test_watchlist_trends_empty_watchlist(self, client):
        import routes.watchlist as watchlist_module

        with open(watchlist_module.WATCHLIST_FILE, "w") as f:
            json.dump([], f)

        resp = client.get("/api/watchlist/trends")
        assert resp.status_code == 200
        assert resp.get_json() == {"items": [], "loading": False, "stale": False}

    def test_build_trend_row_reuses_disk_snapshot_when_latest_bar_dates_match(self, app, sample_df):
        import routes.watchlist as watchlist_module

        weekly_df = sample_df.resample("W-FRI").agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        ).dropna(subset=["Open", "High", "Low", "Close"])
        expected_row = {
            "ticker": "AAPL",
            "daily": {"ribbon": {"date": "2024-01-01", "dir": "bullish"}},
            "weekly": {"ribbon": {"date": "2024-01-05", "dir": "bullish"}},
        }

        with patch("routes.watchlist.cached_download", side_effect=[sample_df, weekly_df, sample_df, weekly_df]):
            with patch(
                "routes.watchlist.compute_all_trend_flips",
                side_effect=[expected_row["daily"], expected_row["weekly"]],
            ) as mock_flips:
                first = watchlist_module._build_trend_row("AAPL")
                second = watchlist_module._build_trend_row("AAPL")

        assert first == expected_row
        assert second == expected_row
        assert mock_flips.call_count == 2


class TestYFinanceCacheConfig:
    def test_configure_yfinance_cache_uses_project_local_directory(self, tmp_path, monkeypatch):
        import lib.cache as cache_module

        calls = []
        target = tmp_path / "yf-cache"
        monkeypatch.setattr(cache_module.yf, "set_tz_cache_location", lambda path: calls.append(path))

        resolved = cache_module._configure_yfinance_cache(str(target))

        assert resolved == str(target)
        assert target.is_dir()
        assert calls == [str(target)]


class TestChartAPI:
    @patch("lib.cache.yf.download")
    def test_chart_returns_data(self, mock_download, client):
        n = 100
        dates = pd.bdate_range("2023-01-01", periods=n)
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame(
            {
                "Open": close + 0.5,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 5_000_000),
            },
            index=dates,
        )
        mock_download.return_value = df

        resp = client.get("/api/chart?ticker=TSLA&start=2023-01-01&period=10&multiplier=3")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "candles" in data
        assert "supertrend_up" in data
        assert "supertrend_down" in data
        assert "volumes" in data
        assert "buy_hold_equity_curve" in data
        assert "strategies" in data
        assert len(data["candles"]) == n
        assert len(data["buy_hold_equity_curve"]) == n

    @pytest.mark.parametrize("sizing", ["vol", "fixed_fraction"])
    @patch("lib.cache.yf.download")
    def test_chart_managed_sizing_marks_midtrend_windows_visible_range_only(
        self, mock_download, client, sizing
    ):
        n = 220
        dates = pd.bdate_range("2023-01-01", periods=n)
        close = np.linspace(100, 220, n)
        df = pd.DataFrame(
            {
                "Open": close,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 5_000_000),
            },
            index=dates,
        )
        mock_download.return_value = df

        resp = client.get(
            "/api/chart?ticker=TSLA&start=2023-07-03&period=2&multiplier=1"
            f"&mm_sizing={sizing}"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        strategy = data["strategies"]["ribbon"]

        assert strategy["backtest_window_policy"] == "visible_range_only"
        assert strategy["window_started_mid_trend"] is True
        assert strategy["summary"]["ending_equity"] == 10000
        assert strategy["summary"]["total_trades"] == 0

    @patch("lib.cache.yf.download")
    def test_chart_candles_only_minimal_payload(self, mock_download, client):
        n = 100
        dates = pd.bdate_range("2023-01-01", periods=n)
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame(
            {
                "Open": close + 0.5,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 5_000_000),
            },
            index=dates,
        )
        mock_download.return_value = df

        resp = client.get(
            "/api/chart?ticker=TSLA&start=2023-01-01&candles_only=1&period=10&multiplier=3"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "candles" in data
        assert "ticker_name" in data
        assert len(data["candles"]) == n
        assert "strategies" not in data
        assert "supertrend_up" not in data

    @patch("lib.cache.yf.download")
    def test_supertrend_payload_includes_whitespace_breaks(self, mock_download, client):
        close = [10, 11, 12, 13, 14, 15, 5, 4, 3, 2, 6, 7, 8]
        dates = pd.bdate_range("2024-01-01", periods=len(close))
        mock_download.return_value = pd.DataFrame(
            {
                "Open": close,
                "High": [c + 0.5 for c in close],
                "Low": [c - 0.5 for c in close],
                "Close": close,
                "Volume": np.full(len(close), 1_000),
            },
            index=dates,
        )

        resp = client.get("/api/chart?ticker=TEST&start=2024-01-01&period=2&multiplier=1")
        assert resp.status_code == 200
        data = resp.get_json()

        st_up = data["supertrend_up"]
        st_down = data["supertrend_down"]
        assert len(st_up) == len(st_down)
        assert [pt["time"] for pt in st_up] == [pt["time"] for pt in st_down]
        assert any("value" not in pt for pt in st_up), "Bullish series should include break markers"
        assert any("value" not in pt for pt in st_down), "Bearish series should include break markers"

    @patch("lib.cache.yf.download")
    def test_chart_empty_data(self, mock_download, client):
        mock_download.return_value = pd.DataFrame()
        resp = client.get("/api/chart?ticker=INVALID")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    @patch("lib.cache.yf.download")
    def test_chart_strategies_present(self, mock_download, client):
        n = 100
        dates = pd.bdate_range("2023-01-01", periods=n)
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame(
            {
                "Open": close + 0.5,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 5_000_000),
            },
            index=dates,
        )
        mock_download.return_value = df

        resp = client.get("/api/chart?ticker=TSLA&start=2023-01-01")
        data = resp.get_json()
        strategies = data["strategies"]
        expected_keys = [
            "ribbon",
            "corpus_trend",
            "corpus_trend_layered",
            "cci_hysteresis",
            "polymarket",
        ]
        for key in expected_keys:
            assert key in strategies, f"Missing strategy: {key}"
            assert "trades" in strategies[key]
            assert "summary" in strategies[key]
            assert "equity_curve" in strategies[key]

        assert "buy_hold_equity_curve" in strategies["corpus_trend"]
        assert "buy_hold_equity_curve" in strategies["corpus_trend_layered"]
        assert "buy_hold_equity_curve" in strategies["cci_hysteresis"]

    @patch("lib.cache.yf.download")
    def test_chart_confirmation_mode_marks_supported_strategies(self, mock_download, client):
        n = 220
        dates = pd.bdate_range("2023-01-01", periods=n)
        close = np.linspace(100, 160, n)
        df = pd.DataFrame(
            {
                "Open": close,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 5_000_000),
            },
            index=dates,
        )
        mock_download.return_value = df

        resp = client.get(
            "/api/chart?ticker=TSLA&start=2023-01-01&confirm_mode=layered_30_70"
        )
        assert resp.status_code == 200
        data = resp.get_json()

        ribbon = data["strategies"]["ribbon"]
        corpus = data["strategies"]["corpus_trend"]
        layered = data["strategies"]["corpus_trend_layered"]
        cci_hysteresis = data["strategies"]["cci_hysteresis"]
        polymarket = data["strategies"]["polymarket"]

        assert ribbon["confirmation_mode"] == "layered_30_70"
        assert ribbon["confirmation_supported"] is True
        assert ribbon["confirmation_starter_fraction"] == pytest.approx(0.30)
        assert ribbon["confirmation_confirmed_fraction"] == pytest.approx(0.70)
        assert corpus["confirmation_mode"] == "layered_30_70"
        assert corpus["confirmation_supported"] is True
        assert layered["confirmation_supported"] is False
        assert cci_hysteresis["confirmation_supported"] is False
        assert polymarket["confirmation_supported"] is False

    @patch("lib.cache.yf.download")
    def test_chart_escalation_confirmation_mode_exposes_hint_metadata(self, mock_download, client):
        n = 220
        dates = pd.bdate_range("2023-01-01", periods=n)
        close = np.linspace(100, 160, n)
        df = pd.DataFrame(
            {
                "Open": close,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 5_000_000),
            },
            index=dates,
        )
        mock_download.return_value = df

        resp = client.get(
            "/api/chart?ticker=TSLA&start=2023-01-01&confirm_mode=escalation_50_50"
        )
        assert resp.status_code == 200
        data = resp.get_json()

        ribbon = data["strategies"]["ribbon"]
        corpus = data["strategies"]["corpus_trend"]
        assert ribbon["confirmation_mode"] == "escalation_50_50"
        assert ribbon["confirmation_supported"] is True
        assert ribbon["confirmation_starter_fraction"] == pytest.approx(0.50)
        assert ribbon["confirmation_confirmed_fraction"] == pytest.approx(0.50)
        assert "base 50%" in ribbon["confirmation_hint"].lower()
        assert corpus["confirmation_supported"] is True

    @patch("lib.cache.yf.Ticker")
    @patch("lib.cache.yf.download")
    def test_chart_monthly_view_derives_from_weekly_data(self, mock_download, mock_ticker, client):
        weekly_dates = pd.date_range("2023-09-01", periods=40, freq="W-FRI")
        weekly_close = np.linspace(100, 140, len(weekly_dates))
        weekly_df = pd.DataFrame(
            {
                "Open": weekly_close - 1,
                "High": weekly_close + 2,
                "Low": weekly_close - 3,
                "Close": weekly_close,
                "Volume": np.full(len(weekly_dates), 2_000_000),
            },
            index=weekly_dates,
        )
        daily_dates = pd.bdate_range("2023-09-01", periods=180)
        daily_close = np.linspace(95, 145, len(daily_dates))
        daily_df = pd.DataFrame(
            {
                "Open": daily_close - 0.5,
                "High": daily_close + 1.5,
                "Low": daily_close - 1.5,
                "Close": daily_close,
                "Volume": np.full(len(daily_dates), 1_500_000),
            },
            index=daily_dates,
        )

        def download_side_effect(*args, **kwargs):
            interval = kwargs.get("interval")
            if interval == "1wk":
                return weekly_df
            if interval == "1d":
                return daily_df
            raise AssertionError(f"Unexpected download interval: {interval}")

        mock_download.side_effect = download_side_effect
        mock_ticker.return_value.info = {}

        resp = client.get("/api/chart?ticker=TSLA&interval=1mo&start=2023-09-01")
        assert resp.status_code == 200
        data = resp.get_json()

        expected_monthly = (
            weekly_df.resample("ME")
            .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
            .dropna(subset=["Open", "High", "Low", "Close"])
        )
        assert len(data["candles"]) == len(expected_monthly)
        assert data["candles"][0]["open"] == round(float(expected_monthly["Open"].iloc[0]), 2)
        assert data["candles"][0]["close"] == round(float(expected_monthly["Close"].iloc[0]), 2)

        requested_intervals = [call.kwargs.get("interval") for call in mock_download.call_args_list]
        assert "1mo" not in requested_intervals
        assert "1wk" in requested_intervals

    @patch("lib.cache.yf.download")
    def test_chart_supports_treasury_price_proxies(self, mock_download, client):
        dates = pd.bdate_range("2023-01-01", periods=260)
        values = np.linspace(88.0, 95.0, len(dates))
        mock_download.return_value = pd.DataFrame(
            {
                "Open": values - 0.1,
                "High": values + 0.2,
                "Low": values - 0.2,
                "Close": values,
                "Volume": np.full(len(values), 500_000),
            },
            index=dates,
        )

        resp = client.get("/api/chart?ticker=UST10Y&start=2023-01-01")
        assert resp.status_code == 200
        data = resp.get_json()
        requested_tickers = [call.args[0] for call in mock_download.call_args_list]
        assert "IEF" in requested_tickers
        assert data["ticker_name"] == "10-Year Treasury Price Proxy (IEF)"
        assert len(data["candles"]) == len(dates)
        assert data["candles"][0]["close"] == round(float(values[0]), 2)


class TestFinancialsAPI:
    @patch("routes.financials._get_cached_ticker_info")
    def test_financials_returns_sections(self, mock_info, client):
        mock_info.return_value = {
            "shortName": "Tesla, Inc.",
            "currency": "USD",
            "quoteType": "EQUITY",
            "sector": "Consumer Cyclical",
            "industry": "Auto Manufacturers",
            "website": "https://www.tesla.com",
            "longBusinessSummary": "Tesla designs and sells EVs.",
            "trailingPE": 61.2,
            "forwardPE": 54.4,
            "marketCap": 900_000_000_000,
            "enterpriseValue": 925_000_000_000,
            "totalRevenue": 98_000_000_000,
            "freeCashflow": 6_000_000_000,
            "grossMargins": 0.18,
            "operatingMargins": 0.11,
            "profitMargins": 0.09,
            "returnOnEquity": 0.22,
            "returnOnAssets": 0.08,
            "revenueGrowth": 0.17,
            "earningsGrowth": 0.14,
            "currentRatio": 1.8,
            "quickRatio": 1.3,
            "debtToEquity": 17.5,
            "beta": 2.1,
        }

        resp = client.get("/api/financials?ticker=TSLA")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["available"] is True
        assert data["overview"]["ticker_name"] == "Tesla, Inc."
        section_titles = [section["title"] for section in data["sections"]]
        assert "Valuation" in section_titles
        assert "Scale" in section_titles
        assert any(metric["label"] == "Trailing P/E" for metric in data["sections"][0]["metrics"])

    @patch("routes.financials._get_cached_ticker_info")
    def test_financials_endpoint_uses_cache(self, mock_info, client):
        mock_info.return_value = {
            "shortName": "Tesla, Inc.",
            "currency": "USD",
            "quoteType": "EQUITY",
            "trailingPE": 61.2,
        }

        first = client.get("/api/financials?ticker=TSLA")
        second = client.get("/api/financials?ticker=TSLA")

        assert first.status_code == 200
        assert second.status_code == 200
        mock_info.assert_called_once_with("TSLA")

    def test_financials_unavailable_for_treasury_price_proxies(self, client):
        resp = client.get("/api/financials?ticker=UST10Y")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["available"] is False
        assert "Treasury price proxies" in data["message"]
        assert data["overview"]["yf_ticker"] == "IEF"


class TestChartOverlays:
    """Test that the chart API returns trend ribbon and volume profile data."""

    @patch("lib.cache.yf.download")
    def test_chart_returns_ribbon_overlay(self, mock_download, client):
        n = 200
        dates = pd.bdate_range("2023-01-01", periods=n)
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame(
            {
                "Open": close + 0.5,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 5_000_000),
            },
            index=dates,
        )
        mock_download.return_value = df

        resp = client.get("/api/chart?ticker=TEST&start=2023-01-01&period=10&multiplier=3")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "overlays" in data
        overlays = data["overlays"]
        assert "ribbon" in overlays, "Overlays should include ribbon"
        ribbon = overlays["ribbon"]
        assert "upper" in ribbon
        assert "lower" in ribbon
        assert "center" in ribbon
        assert len(ribbon["upper"]) > 0, "Ribbon upper should have data"
        assert len(ribbon["lower"]) > 0, "Ribbon lower should have data"
        assert len(ribbon["center"]) > 0, "Ribbon center should have data"

    @patch("lib.cache.yf.download")
    def test_ribbon_data_has_color_fields(self, mock_download, client):
        n = 200
        dates = pd.bdate_range("2023-01-01", periods=n)
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame(
            {
                "Open": close + 0.5,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 5_000_000),
            },
            index=dates,
        )
        mock_download.return_value = df

        resp = client.get("/api/chart?ticker=TEST&start=2023-01-01")
        data = resp.get_json()
        ribbon = data["overlays"]["ribbon"]
        sample = ribbon["upper"][0]
        assert "time" in sample
        assert "value" in sample
        assert "color" in sample
        assert "lineColor" in sample
        assert sample["color"].startswith("rgba(")

    @patch("lib.cache.yf.download")
    def test_ribbon_band_ordering_in_response(self, mock_download, client):
        n = 200
        dates = pd.bdate_range("2023-01-01", periods=n)
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame(
            {
                "Open": close + 0.5,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 5_000_000),
            },
            index=dates,
        )
        mock_download.return_value = df

        resp = client.get("/api/chart?ticker=TEST&start=2023-01-01")
        data = resp.get_json()
        ribbon = data["overlays"]["ribbon"]
        upper_map = {d["time"]: d["value"] for d in ribbon["upper"]}
        for pt in ribbon["lower"]:
            if pt["time"] in upper_map:
                assert upper_map[pt["time"]] >= pt["value"], \
                    f"Upper ({upper_map[pt['time']]}) should be >= lower ({pt['value']}) at {pt['time']}"

    @patch("lib.cache.yf.download")
    def test_chart_returns_vol_profile(self, mock_download, client):
        n = 200
        dates = pd.bdate_range("2023-01-01", periods=n)
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame(
            {
                "Open": close + 0.5,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 5_000_000),
            },
            index=dates,
        )
        mock_download.return_value = df

        resp = client.get("/api/chart?ticker=TEST&start=2023-01-01")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "vol_profile" in data, "Response should include vol_profile"
        vp = data["vol_profile"]
        assert isinstance(vp, list)
        assert len(vp) == 40, "Should have 40 price buckets"

    @patch("lib.cache.yf.download")
    def test_vol_profile_structure(self, mock_download, client):
        n = 200
        dates = pd.bdate_range("2023-01-01", periods=n)
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame(
            {
                "Open": close + 0.5,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 5_000_000),
            },
            index=dates,
        )
        mock_download.return_value = df

        resp = client.get("/api/chart?ticker=TEST&start=2023-01-01")
        data = resp.get_json()
        bucket = data["vol_profile"][0]
        assert "price" in bucket
        assert "total" in bucket
        assert "buy" in bucket
        assert "sell" in bucket

    @patch("lib.cache.yf.download")
    def test_vol_profile_buy_sell_sum(self, mock_download, client):
        """Buy + sell volume should equal total for each bucket."""
        n = 200
        dates = pd.bdate_range("2023-01-01", periods=n)
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame(
            {
                "Open": close + 0.5,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 5_000_000),
            },
            index=dates,
        )
        mock_download.return_value = df

        resp = client.get("/api/chart?ticker=TEST&start=2023-01-01")
        data = resp.get_json()
        for bucket in data["vol_profile"]:
            assert abs(bucket["buy"] + bucket["sell"] - bucket["total"]) < 1, \
                f"Buy ({bucket['buy']}) + Sell ({bucket['sell']}) should equal Total ({bucket['total']})"

    @patch("lib.cache.yf.download")
    def test_vol_profile_total_volume(self, mock_download, client):
        """Sum of all bucket totals should approximate total volume in the data."""
        n = 200
        dates = pd.bdate_range("2023-01-01", periods=n)
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        vol = np.full(n, 5_000_000)
        df = pd.DataFrame(
            {
                "Open": close + 0.5,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": vol,
            },
            index=dates,
        )
        mock_download.return_value = df

        resp = client.get("/api/chart?ticker=TEST&start=2023-01-01")
        data = resp.get_json()
        vp_total = sum(b["total"] for b in data["vol_profile"])
        expected_total = float(vol.sum())
        assert abs(vp_total - expected_total) < expected_total * 0.01, \
            f"Volume profile total ({vp_total}) should be close to actual total ({expected_total})"


class TestHelperFunctions:
    def test_parse_start_date(self):
        from routes.chart import _parse_start_date
        result = _parse_start_date("2024-01-15")
        assert result == pd.Timestamp("2024-01-15")

    def test_parse_end_date_empty(self):
        from routes.chart import _parse_end_date
        assert _parse_end_date("") is None
        assert _parse_end_date(None) is None

    def test_warmup_start_daily(self):
        from routes.chart import _warmup_start
        from lib.settings import DAILY_WARMUP_DAYS
        result = _warmup_start("2024-06-01", "1d")
        expected = pd.Timestamp("2024-06-01") - pd.Timedelta(days=DAILY_WARMUP_DAYS)
        assert result == expected.strftime("%Y-%m-%d")

    def test_warmup_start_weekly(self):
        from routes.chart import _warmup_start
        from lib.settings import WEEKLY_WARMUP_DAYS
        result = _warmup_start("2024-06-01", "1wk")
        expected = pd.Timestamp("2024-06-01") - pd.Timedelta(days=WEEKLY_WARMUP_DAYS)
        assert result == expected.strftime("%Y-%m-%d")

    def test_warmup_start_monthly_uses_weekly_warmup(self):
        from routes.chart import _warmup_start
        from lib.settings import WEEKLY_WARMUP_DAYS
        result = _warmup_start("2024-06-01", "1mo")
        expected = pd.Timestamp("2024-06-01") - pd.Timedelta(days=WEEKLY_WARMUP_DAYS)
        assert result == expected.strftime("%Y-%m-%d")

    def test_source_interval_maps_monthly_to_weekly(self):
        from routes.chart import _source_interval

        assert _source_interval("1mo") == "1wk"
        assert _source_interval("1d") == "1d"

    def test_derive_chart_frame_monthly_resamples_ohlcv(self):
        from routes.chart import _derive_chart_frame

        weekly_dates = pd.to_datetime(
            ["2024-01-05", "2024-01-12", "2024-01-19", "2024-02-02", "2024-02-09"]
        )
        weekly_df = pd.DataFrame(
            {
                "Open": [10, 11, 12, 20, 21],
                "High": [15, 16, 18, 25, 27],
                "Low": [9, 10, 11, 18, 19],
                "Close": [11, 12, 13, 21, 22],
                "Volume": [100, 110, 120, 200, 210],
            },
            index=weekly_dates,
        )

        monthly_df = _derive_chart_frame(weekly_df, "1mo")

        assert list(monthly_df["Open"]) == [10, 20]
        assert list(monthly_df["High"]) == [18, 27]
        assert list(monthly_df["Low"]) == [9, 18]
        assert list(monthly_df["Close"]) == [13, 22]
        assert list(monthly_df["Volume"]) == [330, 410]
