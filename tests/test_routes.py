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
