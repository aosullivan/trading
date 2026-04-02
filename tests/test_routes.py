"""Tests for Flask API routes."""

import json
from unittest.mock import patch, MagicMock

import pandas as pd
import numpy as np
import pytest


class TestIndexRoute:
    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Trading App" in resp.data


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

    @patch("app._fetch_treasury_yield_history")
    def test_watchlist_quotes_support_treasury_yields(self, mock_history, client):
        import app as app_module

        with open(app_module.WATCHLIST_FILE, "w") as f:
            json.dump(["UST10Y"], f)

        dates = pd.bdate_range("2024-01-01", periods=5)
        values = np.array([4.1, 4.15, 4.08, 4.12, 4.2])
        mock_history.return_value = pd.DataFrame(
            {
                "Open": values,
                "High": values,
                "Low": values,
                "Close": values,
                "Volume": np.zeros(len(values)),
            },
            index=dates,
        )

        resp = client.get("/api/watchlist/quotes")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == [{"ticker": "UST10Y", "last": 4.2, "chg": 0.08, "chg_pct": 1.94}]

    @patch("app._yf_rate_limited_download")
    def test_watchlist_quotes_fall_back_to_single_ticker_fetches_when_bulk_download_fails(
        self, mock_download, client
    ):
        import app as app_module

        with open(app_module.WATCHLIST_FILE, "w") as f:
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


class TestYFinanceCacheConfig:
    def test_configure_yfinance_cache_uses_project_local_directory(self, tmp_path, monkeypatch):
        import app as app_module

        calls = []
        target = tmp_path / "yf-cache"
        monkeypatch.setattr(app_module.yf, "set_tz_cache_location", lambda path: calls.append(path))

        resolved = app_module._configure_yfinance_cache(str(target))

        assert resolved == str(target)
        assert target.is_dir()
        assert calls == [str(target)]


class TestChartAPI:
    @patch("app.yf.download")
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
        assert "strategies" in data
        assert len(data["candles"]) == n

    @patch("app.yf.download")
    def test_chart_empty_data(self, mock_download, client):
        mock_download.return_value = pd.DataFrame()
        resp = client.get("/api/chart?ticker=INVALID")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    @patch("app.yf.download")
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
            "supertrend", "ema_crossover", "macd", "ma_confirm",
            "donchian", "adx_trend", "bb_breakout", "keltner",
            "parabolic_sar", "cci_trend",
        ]
        for key in expected_keys:
            assert key in strategies, f"Missing strategy: {key}"
            assert "trades" in strategies[key]
            assert "summary" in strategies[key]

    @patch("app.yf.Ticker")
    @patch("app.yf.download")
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

    @patch("app._fetch_treasury_yield_history")
    def test_chart_supports_treasury_yield_series(self, mock_history, client):
        dates = pd.bdate_range("2023-01-01", periods=260)
        values = np.linspace(3.5, 4.5, len(dates))
        mock_history.return_value = pd.DataFrame(
            {
                "Open": values,
                "High": values,
                "Low": values,
                "Close": values,
                "Volume": np.zeros(len(values)),
            },
            index=dates,
        )

        resp = client.get("/api/chart?ticker=UST10Y&start=2023-01-01")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ticker_name"] == "10-Year Treasury Yield"
        assert len(data["candles"]) == len(dates)
        assert data["candles"][0]["close"] == round(float(values[0]), 2)


class TestFinancialsAPI:
    @patch("app._get_cached_ticker_info")
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

    @patch("app._get_cached_ticker_info")
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

    def test_financials_unavailable_for_treasury_series(self, client):
        resp = client.get("/api/financials?ticker=UST10Y")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["available"] is False
        assert "Treasury yield series" in data["message"]


class TestChartOverlays:
    """Test that the chart API returns trend ribbon and volume profile data."""

    @patch("app.yf.download")
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

    @patch("app.yf.download")
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
        # Each upper/lower point should have time, value, color, lineColor
        sample = ribbon["upper"][0]
        assert "time" in sample
        assert "value" in sample
        assert "color" in sample
        assert "lineColor" in sample
        assert sample["color"].startswith("rgba(")

    @patch("app.yf.download")
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
        # Upper should be >= lower for matching timestamps
        upper_map = {d["time"]: d["value"] for d in ribbon["upper"]}
        for pt in ribbon["lower"]:
            if pt["time"] in upper_map:
                assert upper_map[pt["time"]] >= pt["value"], \
                    f"Upper ({upper_map[pt['time']]}) should be >= lower ({pt['value']}) at {pt['time']}"

    @patch("app.yf.download")
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

    @patch("app.yf.download")
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

    @patch("app.yf.download")
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

    @patch("app.yf.download")
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
        from app import _parse_start_date
        result = _parse_start_date("2024-01-15")
        assert result == pd.Timestamp("2024-01-15")

    def test_parse_end_date_empty(self):
        from app import _parse_end_date
        assert _parse_end_date("") is None
        assert _parse_end_date(None) is None

    def test_warmup_start_daily(self):
        from app import _warmup_start, DAILY_WARMUP_DAYS
        result = _warmup_start("2024-06-01", "1d")
        expected = pd.Timestamp("2024-06-01") - pd.Timedelta(days=DAILY_WARMUP_DAYS)
        assert result == expected.strftime("%Y-%m-%d")

    def test_warmup_start_weekly(self):
        from app import _warmup_start, WEEKLY_WARMUP_DAYS
        result = _warmup_start("2024-06-01", "1wk")
        expected = pd.Timestamp("2024-06-01") - pd.Timedelta(days=WEEKLY_WARMUP_DAYS)
        assert result == expected.strftime("%Y-%m-%d")

    def test_warmup_start_monthly_uses_weekly_warmup(self):
        from app import _warmup_start, WEEKLY_WARMUP_DAYS
        result = _warmup_start("2024-06-01", "1mo")
        expected = pd.Timestamp("2024-06-01") - pd.Timedelta(days=WEEKLY_WARMUP_DAYS)
        assert result == expected.strftime("%Y-%m-%d")

    def test_source_interval_maps_monthly_to_weekly(self):
        from app import _source_interval

        assert _source_interval("1mo") == "1wk"
        assert _source_interval("1d") == "1d"

    def test_derive_chart_frame_monthly_resamples_ohlcv(self):
        from app import _derive_chart_frame

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
