"""Tests for Flask API routes."""

import json
from pathlib import Path
import time
from unittest.mock import patch, MagicMock

import pandas as pd
import numpy as np
import pytest

from lib.backtesting import build_weekly_confirmed_ribbon_direction
import routes.chart as chart_module
import routes.portfolio as portfolio_module
from routes.chart import _align_weekly_direction_to_daily, _carry_neutral_direction

PORTFOLIO_CONTRACT_RATCHET_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "portfolio_backtest_contract_ratchet.json"
)
PORTFOLIO_CAMPAIGN_CONTRACT_RATCHET_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "portfolio_campaign_contract_ratchet.json"
)
PORTFOLIO_RESEARCH_MATRIX_CONTRACT_RATCHET_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "portfolio_research_matrix_contract_ratchet.json"
)


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
        assert b'option value="ema_9_26"' in resp.data

    def test_portfolio_page_exposes_strategy_and_basket_controls(self, client):
        resp = client.get("/portfolio")
        assert resp.status_code == 200
        assert b'option value="ribbon"' in resp.data
        assert b'option value="corpus_trend"' in resp.data
        assert b'option value="cci_hysteresis"' in resp.data
        assert b'option value="monthly_breadth_guard_v1"' in resp.data
        assert b'option value="monthly_breadth_guard_ladder_v1"' in resp.data
        assert b'option value="watchlist"' in resp.data
        assert b'option value="manual"' in resp.data
        assert b'option value="preset"' in resp.data
        assert b'option value="focus_7"' in resp.data
        assert b'option value="growth_5"' in resp.data
        assert b'option value="diversified_10"' in resp.data
        assert b"Strategy Vs Buy &amp; Hold" in resp.data
        assert b"Order Activity" in resp.data
        assert b"Basket Diagnostics" in resp.data
        assert b"Campaign Dashboard" in resp.data
        assert b"Save Current Run As Campaign" in resp.data
        assert b"Create Canonical Research Matrix" in resp.data
        assert b"Saved Campaigns" in resp.data
        assert b"Selected Campaign" in resp.data
        assert b"Run Comparison" in resp.data
        assert b"Refresh Rankings" in resp.data
        assert b"Top Completed Runs" in resp.data
        assert b"Side-By-Side Comparison" in resp.data
        assert b"Gap Vs Buy &amp; Hold" in resp.data


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
            {"ticker": "AAPL", "daily": {}, "weekly": {}, "trade_setup": {}},
            {"ticker": "TSLA", "daily": {}, "weekly": {}, "trade_setup": {}},
        ]
        rows = [
            {
                "ticker": "AAPL",
                "daily": {"ribbon": {"date": "2024-03-15", "dir": "bullish"}},
                "weekly": {"ribbon": {"date": "2024-03-08", "dir": "bullish"}},
                "trade_setup": {},
            },
            {
                "ticker": "TSLA",
                "daily": {"ribbon": {"date": "2024-03-14", "dir": "bearish"}},
                "weekly": {"ribbon": {"date": "2024-02-23", "dir": "bearish"}},
                "trade_setup": {},
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


class TestPortfolioBacktestAPI:
    @staticmethod
    def _sample_portfolio_df():
        idx = pd.date_range("2024-01-02", periods=5, freq="D")
        return pd.DataFrame(
            {
                "Open": [100.0, 101.0, 103.0, 104.0, 105.0],
                "High": [101.0, 103.0, 104.0, 106.0, 107.0],
                "Low": [99.0, 100.0, 102.0, 103.0, 104.0],
                "Close": [100.0, 102.0, 103.0, 105.0, 106.0],
                "Volume": [1000, 1000, 1000, 1000, 1000],
            },
            index=idx,
        )

    @staticmethod
    def _sample_direction(df):
        return pd.Series([0, 1, 1, 1, -1], index=df.index)

    @patch("routes.portfolio._compute_signal_for_strategy")
    @patch("routes.portfolio.cached_download")
    def test_portfolio_backtest_supports_manual_basket_and_retained_strategy(
        self, mock_download, mock_compute_signal, client
    ):
        df = self._sample_portfolio_df()
        mock_download.return_value = df
        mock_compute_signal.side_effect = (
            lambda strategy, ticker, frame: self._sample_direction(frame)
        )

        resp = client.get(
            "/api/portfolio/backtest",
            query_string={
                "stream": "0",
                "strategy": "corpus_trend",
                "basket_source": "manual",
                "tickers": "MSFT,NVDA",
                "start": "2024-01-02",
            },
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["strategy"] == "corpus_trend"
        assert data["basket"]["source"] == "manual"
        assert data["config"]["strategy"] == "corpus_trend"
        assert data["config"]["basket_source"] == "manual"
        assert data["basket"]["requested_tickers"] == ["MSFT", "NVDA"]
        assert data["basket_diagnostics"]["size_bucket"] == "small"
        assert data["basket_diagnostics"]["composition"] == "equity_only"
        assert data["basket_diagnostics"]["traded_tickers"] >= 1
        assert data["comparison"]["winner"] in {"strategy", "buy_hold", "tie"}
        assert data["orders"]
        assert {order["ticker"] for order in data["orders"]}.issubset({"MSFT", "NVDA"})
        assert set(data["tickers"]) == {"MSFT", "NVDA"}
        assert {call.args[0] for call in mock_compute_signal.call_args_list} == {"corpus_trend"}
        assert {call.args[1] for call in mock_compute_signal.call_args_list} == {"MSFT", "NVDA"}

    @patch("routes.portfolio._compute_signal_for_strategy")
    @patch("routes.portfolio.cached_download")
    def test_portfolio_backtest_supports_focus_preset_basket(
        self, mock_download, mock_compute_signal, client
    ):
        df = self._sample_portfolio_df()
        mock_download.return_value = df
        mock_compute_signal.side_effect = (
            lambda strategy, ticker, frame: self._sample_direction(frame)
        )

        resp = client.get(
            "/api/portfolio/backtest",
            query_string={
                "stream": "0",
                "strategy": "cci_hysteresis",
                "basket_source": "preset",
                "preset": "focus",
                "start": "2024-01-02",
            },
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["strategy"] == "cci_hysteresis"
        assert data["basket"]["source"] == "preset"
        assert data["basket"]["preset"] == "focus"
        assert data["config"]["basket_preset"] == "focus"
        assert data["basket_diagnostics"]["composition"] == "mixed"
        assert data["comparison"]["strategy_ending_equity"] > 0
        assert len(data["tickers"]) == len(portfolio_module._PORTFOLIO_PRESET_BASKETS["focus"])
        assert set(data["tickers"]) == set(portfolio_module._PORTFOLIO_PRESET_BASKETS["focus"])

    @patch("routes.portfolio.compute_monthly_breadth_guard_directions")
    @patch("routes.portfolio.cached_download")
    def test_portfolio_backtest_supports_monthly_breadth_guard_strategy(
        self, mock_download, mock_monthly_breadth_guard, client
    ):
        df = self._sample_portfolio_df()
        mock_download.return_value = df
        mock_monthly_breadth_guard.return_value = {
            "MSFT": self._sample_direction(df),
            "NVDA": pd.Series([-1, -1, 1, 1, 1], index=df.index),
        }

        resp = client.get(
            "/api/portfolio/backtest",
            query_string={
                "stream": "0",
                "strategy": "monthly_breadth_guard_v1",
                "basket_source": "manual",
                "tickers": "MSFT,NVDA",
                "start": "2024-01-02",
            },
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["strategy"] == "monthly_breadth_guard_v1"
        assert data["basket"]["requested_tickers"] == ["MSFT", "NVDA"]
        assert set(data["tickers"]) == {"MSFT", "NVDA"}
        mock_monthly_breadth_guard.assert_called_once()

    @patch("routes.portfolio.compute_monthly_breadth_guard_ladder_directions")
    @patch("routes.portfolio.cached_download")
    def test_portfolio_backtest_supports_monthly_breadth_guard_ladder_strategy(
        self, mock_download, mock_monthly_breadth_guard_ladder, client
    ):
        df = self._sample_portfolio_df()
        mock_download.return_value = df
        mock_monthly_breadth_guard_ladder.return_value = {
            "MSFT": self._sample_direction(df),
            "NVDA": pd.Series([-1, 1, 1, 1, 1], index=df.index),
        }

        resp = client.get(
            "/api/portfolio/backtest",
            query_string={
                "stream": "0",
                "strategy": "monthly_breadth_guard_ladder_v1",
                "basket_source": "manual",
                "tickers": "MSFT,NVDA",
                "start": "2024-01-02",
            },
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["strategy"] == "monthly_breadth_guard_ladder_v1"
        assert data["basket"]["requested_tickers"] == ["MSFT", "NVDA"]
        assert set(data["tickers"]) == {"MSFT", "NVDA"}
        mock_monthly_breadth_guard_ladder.assert_called_once()

    def test_portfolio_backtest_rejects_unsupported_strategy(self, client):
        resp = client.get(
            "/api/portfolio/backtest",
            query_string={"stream": "0", "strategy": "polymarket"},
        )

        assert resp.status_code == 400
        assert "Unsupported portfolio strategy" in resp.get_json()["error"]

    def test_portfolio_backtest_rejects_empty_manual_basket(self, client):
        resp = client.get(
            "/api/portfolio/backtest",
            query_string={
                "stream": "0",
                "basket_source": "manual",
                "tickers": "",
            },
        )

        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Manual basket requires at least one ticker"

    @patch("routes.portfolio._compute_signal_for_strategy")
    @patch("routes.portfolio.cached_download")
    def test_portfolio_contract_ratchet(self, mock_download, mock_compute_signal, client):
        fixture = json.loads(PORTFOLIO_CONTRACT_RATCHET_PATH.read_text())
        df = self._sample_portfolio_df()
        mock_download.return_value = df
        mock_compute_signal.side_effect = (
            lambda strategy, ticker, frame: self._sample_direction(frame)
        )

        resp = client.get("/api/portfolio/backtest", query_string=fixture["request"])

        assert resp.status_code == 200
        data = resp.get_json()

        assert sorted(portfolio_module._SUPPORTED_PORTFOLIO_STRATEGIES) == sorted(
            fixture["supported_strategies"]
        )
        assert sorted(portfolio_module.SUPPORTED_ALLOCATOR_POLICIES) == sorted(
            fixture["supported_allocator_policies"]
        )
        assert sorted(portfolio_module._PORTFOLIO_PRESET_BASKETS) == sorted(
            fixture["preset_baskets"]
        )
        assert data["strategy"] == fixture["expected_response"]["strategy"]
        assert data["tickers"] == fixture["expected_response"]["tickers"]
        assert data["basket"] == fixture["expected_response"]["basket"]
        assert data["basket_diagnostics"] == fixture["expected_response"]["basket_diagnostics"]
        assert data["comparison"] == fixture["expected_response"]["comparison"]
        assert data["portfolio_diagnostics"] == fixture["expected_response"]["portfolio_diagnostics"]
        assert data["orders"] == fixture["expected_response"]["orders"]
        assert data["config"] == fixture["expected_response"]["config"]

    def test_portfolio_backtest_rejects_unsupported_allocator_policy(self, client):
        resp = client.get(
            "/api/portfolio/backtest",
            query_string={"stream": "0", "allocator_policy": "top_n_strength_v1"},
        )

        assert resp.status_code == 400
        assert "Unsupported allocator policy" in resp.get_json()["error"]

    @patch("routes.portfolio._compute_signal_for_strategy")
    @patch("routes.portfolio.cached_download")
    def test_portfolio_backtest_supports_non_default_allocator_policy(
        self, mock_download, mock_compute_signal, client
    ):
        df = self._sample_portfolio_df()
        mock_download.return_value = df
        mock_compute_signal.side_effect = (
            lambda strategy, ticker, frame: self._sample_direction(frame)
        )

        resp = client.get(
            "/api/portfolio/backtest",
            query_string={
                "stream": "0",
                "strategy": "corpus_trend",
                "allocator_policy": "signal_equal_weight_redeploy_v1",
                "basket_source": "manual",
                "tickers": "MSFT,NVDA",
                "start": "2024-01-02",
            },
        )

        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["config"]["allocator_policy"] == "signal_equal_weight_redeploy_v1"
        assert payload["portfolio_diagnostics"]["allocator_policy"] == "signal_equal_weight_redeploy_v1"


class TestPortfolioCampaignAPI:
    @staticmethod
    def _campaign_payload():
        return {
            "name": "Core Sweep",
            "goal": "Compare retained strategies across baskets",
            "tags": ["small", "favorites"],
            "runs": [
                {
                    "name": "Manual corpus run",
                    "strategy": "corpus_trend",
                    "basket_source": "manual",
                    "tickers": ["MSFT", "NVDA"],
                    "start": "2024-01-02",
                    "end": "",
                    "heat_limit": 0.2,
                    "money_management": {
                        "sizing_method": "fixed_fraction",
                        "stop_type": "atr",
                        "stop_atr_period": 20,
                        "stop_atr_multiple": 3.0,
                    },
                }
            ],
        }

    @staticmethod
    def _seed_completed_campaign(
        *,
        name,
        strategy,
        basket_source,
        last_result,
        tickers=None,
        preset=None,
        tags=None,
    ):
        from lib import portfolio_campaigns

        payload = {
            "name": name,
            "goal": "Seed completed campaign for comparison tests",
            "tags": tags or [],
            "runs": [
                {
                    "name": f"{strategy} run",
                    "strategy": strategy,
                    "basket_source": basket_source,
                    "tickers": tickers or [],
                    "preset": preset,
                    "start": "2024-01-02",
                    "heat_limit": 0.2,
                    "money_management": {
                        "sizing_method": "fixed_fraction",
                        "stop_type": "atr",
                        "stop_atr_period": 20,
                        "stop_atr_multiple": 3.0,
                        "initial_capital": 10000,
                    },
                }
            ],
        }
        campaign = portfolio_campaigns.create_campaign(payload)
        run_id = campaign["runs"][0]["run_id"]
        portfolio_campaigns.update_run_state(
            campaign["campaign_id"],
            run_id,
            status="completed",
            last_result=last_result,
            last_error=None,
        )
        return campaign["campaign_id"], run_id

    @patch("routes.portfolio._start_campaign_worker")
    def test_create_and_list_portfolio_campaigns(self, mock_start_worker, client):
        resp = client.post("/api/portfolio/campaigns", json=self._campaign_payload())

        assert resp.status_code == 201
        campaign = resp.get_json()
        assert campaign["name"] == "Core Sweep"
        assert campaign["runs"][0]["status"] == "planned"

        listed = client.get("/api/portfolio/campaigns")
        assert listed.status_code == 200
        items = listed.get_json()["items"]
        assert any(item["campaign_id"] == campaign["campaign_id"] for item in items)
        mock_start_worker.assert_not_called()

    def test_schedule_portfolio_campaign_persists_schedule_contract(self, client):
        create = client.post("/api/portfolio/campaigns", json=self._campaign_payload())
        campaign_id = create.get_json()["campaign_id"]

        resp = client.post(
            f"/api/portfolio/campaigns/{campaign_id}/schedule",
            json={
                "enabled": True,
                "cadence": "weekly",
                "weekdays": ["mon", "wed", "fri"],
                "hour": 9,
                "minute": 30,
            },
        )

        assert resp.status_code == 200
        campaign = resp.get_json()
        assert campaign["schedule"]["enabled"] is True
        assert campaign["schedule"]["cadence"] == "weekly"
        assert campaign["schedule"]["weekdays"] == ["mon", "wed", "fri"]
        assert campaign["schedule"]["hour"] == 9
        assert campaign["schedule"]["minute"] == 30
        assert campaign["schedule"]["next_run_at"]

    def test_portfolio_campaign_contract_ratchet(self, client):
        fixture = json.loads(PORTFOLIO_CAMPAIGN_CONTRACT_RATCHET_PATH.read_text())

        create = client.post("/api/portfolio/campaigns", json=fixture["create_request"])

        assert create.status_code == 201
        campaign = create.get_json()
        assert campaign["status"] == fixture["expected_defaults"]["campaign_status"]
        assert campaign["runs"][0]["status"] == fixture["expected_defaults"]["run_status"]
        assert campaign["progress"] == fixture["expected_defaults"]["progress"]

        schedule = client.post(
            f"/api/portfolio/campaigns/{campaign['campaign_id']}/schedule",
            json=fixture["schedule_request"],
        )

        assert schedule.status_code == 200
        scheduled_campaign = schedule.get_json()
        for key, value in fixture["expected_schedule"].items():
            assert scheduled_campaign["schedule"][key] == value
        assert scheduled_campaign["schedule"]["next_run_at"]

    @patch("routes.portfolio.cached_download")
    @patch("routes.portfolio._compute_signal_for_strategy")
    def test_queue_portfolio_campaign_executes_runs_and_persists_summary(
        self, mock_compute_signal, mock_download, client
    ):
        df = TestPortfolioBacktestAPI._sample_portfolio_df()
        mock_download.return_value = df
        mock_compute_signal.side_effect = (
            lambda strategy, ticker, frame: TestPortfolioBacktestAPI._sample_direction(frame)
        )

        create = client.post("/api/portfolio/campaigns", json=self._campaign_payload())
        campaign_id = create.get_json()["campaign_id"]

        with patch(
            "routes.portfolio._start_campaign_worker",
            side_effect=lambda campaign_id: portfolio_module._campaign_worker(campaign_id),
        ):
            queued = client.post(f"/api/portfolio/campaigns/{campaign_id}/queue")

        assert queued.status_code == 202
        queued_payload = queued.get_json()
        assert queued_payload["queued"] == 1
        campaign = queued_payload["campaign"]
        run = campaign["runs"][0]
        assert run["status"] == "completed"
        assert run["last_result"]["winner"] in {"strategy", "buy_hold", "tie"}
        assert run["last_result"]["order_count"] >= 1
        assert "drawdown_gap_pct" in run["last_result"]
        assert "upside_capture_pct" in run["last_result"]
        assert "avg_active_positions" in run["last_result"]
        assert "turnover_pct" in run["last_result"]

        fetched = client.get(f"/api/portfolio/campaigns/{campaign_id}")
        assert fetched.status_code == 200
        fetched_campaign = fetched.get_json()
        assert fetched_campaign["progress"]["completed"] == 1
        assert fetched_campaign["progress"]["remaining"] == 0
        assert fetched_campaign["runs"][0]["status"] == "completed"

    @patch("routes.portfolio.cached_download")
    @patch("routes.portfolio._compute_signal_for_strategy")
    def test_rerun_portfolio_campaign_requeues_completed_runs(
        self, mock_compute_signal, mock_download, client
    ):
        df = TestPortfolioBacktestAPI._sample_portfolio_df()
        mock_download.return_value = df
        mock_compute_signal.side_effect = (
            lambda strategy, ticker, frame: TestPortfolioBacktestAPI._sample_direction(frame)
        )

        create = client.post("/api/portfolio/campaigns", json=self._campaign_payload())
        campaign_id = create.get_json()["campaign_id"]

        with patch(
            "routes.portfolio._start_campaign_worker",
            side_effect=lambda queued_campaign_id: portfolio_module._campaign_worker(queued_campaign_id),
        ):
            first = client.post(f"/api/portfolio/campaigns/{campaign_id}/queue")
            rerun = client.post(f"/api/portfolio/campaigns/{campaign_id}/rerun")

        assert first.status_code == 202
        assert rerun.status_code == 202
        rerun_payload = rerun.get_json()
        assert rerun_payload["queued"] == 1
        assert rerun_payload["campaign"]["runs"][0]["status"] == "completed"

    @patch("routes.portfolio.cached_download")
    @patch("routes.portfolio._compute_signal_for_strategy")
    def test_run_due_portfolio_campaigns_queues_scheduled_campaigns(
        self, mock_compute_signal, mock_download, client
    ):
        df = TestPortfolioBacktestAPI._sample_portfolio_df()
        mock_download.return_value = df
        mock_compute_signal.side_effect = (
            lambda strategy, ticker, frame: TestPortfolioBacktestAPI._sample_direction(frame)
        )

        create = client.post("/api/portfolio/campaigns", json=self._campaign_payload())
        campaign_id = create.get_json()["campaign_id"]
        client.post(
            f"/api/portfolio/campaigns/{campaign_id}/schedule",
            json={
                "enabled": True,
                "cadence": "hourly",
                "interval_hours": 12,
                "next_run_at": "2000-01-01T00:00:00+00:00",
            },
        )

        with patch(
            "routes.portfolio._start_campaign_worker",
            side_effect=lambda queued_campaign_id: portfolio_module._campaign_worker(queued_campaign_id),
        ):
            due = client.post("/api/portfolio/campaigns/run-due")

        assert due.status_code == 200
        payload = due.get_json()
        assert payload["count"] == 1
        assert payload["queued_campaigns"][0]["campaign_id"] == campaign_id

        fetched = client.get(f"/api/portfolio/campaigns/{campaign_id}")
        assert fetched.status_code == 200
        campaign = fetched.get_json()
        assert campaign["runs"][0]["status"] == "completed"
        assert campaign["schedule"]["last_queued_at"]
        assert campaign["schedule"]["next_run_at"]

    def test_portfolio_research_matrix_catalog_returns_defaults(self, client):
        resp = client.get("/api/portfolio/research-matrix")

        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["version"] == "portfolio_rotation_matrix_v1"
        assert payload["strategies"] == ["ribbon", "corpus_trend", "cci_hysteresis"]
        assert payload["allocator_policies"] == [
            "signal_flip_v1",
            "signal_equal_weight_redeploy_v1",
            "signal_top_n_strength_v1",
            "core_plus_rotation_v1",
        ]
        assert [item["key"] for item in payload["baskets"]] == ["focus_7", "growth_5", "diversified_10"]
        assert [item["key"] for item in payload["windows"]] == [
            "crash_recovery_2020_2021",
            "drawdown_chop_2022",
            "bull_recovery_2023_2025",
        ]
        assert payload["run_count"] == 108

    def test_portfolio_research_matrix_contract_ratchet(self, client):
        fixture = json.loads(PORTFOLIO_RESEARCH_MATRIX_CONTRACT_RATCHET_PATH.read_text())

        create = client.post("/api/portfolio/campaigns/research-matrix", json=fixture["request"])

        assert create.status_code == 201
        payload = create.get_json()
        assert payload["matrix"] == fixture["expected_matrix"]

        campaign = payload["campaign"]
        assert campaign["name"] == fixture["request"]["name"]
        assert campaign["goal"] == fixture["request"]["goal"]
        assert len(campaign["runs"]) == fixture["expected_matrix"]["run_count"]
        first_run = campaign["runs"][0]
        for key, value in fixture["expected_first_run"].items():
            assert first_run[key] == value

    def test_portfolio_research_matrix_rejects_unknown_filters(self, client):
        resp = client.post(
            "/api/portfolio/campaigns/research-matrix",
            json={"allocator_policies": ["not_real_v1"]},
        )

        assert resp.status_code == 400
        assert "Unsupported allocator policies" in resp.get_json()["error"]

    def test_completed_run_rankings_return_sorted_saved_results(self, client):
        self._seed_completed_campaign(
            name="Higher Gap",
            strategy="corpus_trend",
            basket_source="manual",
            tickers=["MSFT", "NVDA"],
            last_result={
                "completed_at": "2026-04-14T12:00:00+00:00",
                "winner": "strategy",
                "strategy_ending_equity": 12800,
                "buy_hold_ending_equity": 11200,
                "return_gap_pct": 16.0,
                "equity_gap": 1600,
                "max_drawdown_pct": 8.0,
                "traded_tickers": 2,
                "order_count": 6,
            },
        )
        self._seed_completed_campaign(
            name="Lower Gap",
            strategy="cci_hysteresis",
            basket_source="preset",
            preset="focus",
            last_result={
                "completed_at": "2026-04-14T13:00:00+00:00",
                "winner": "strategy",
                "strategy_ending_equity": 11900,
                "buy_hold_ending_equity": 11300,
                "return_gap_pct": 6.0,
                "equity_gap": 600,
                "max_drawdown_pct": 5.0,
                "traded_tickers": 4,
                "order_count": 8,
            },
        )

        resp = client.get(
            "/api/portfolio/campaigns/completed-runs",
            query_string={"sort_by": "best_gap_vs_buy_hold"},
        )

        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["sort_by"] == "best_gap_vs_buy_hold"
        assert [item["campaign_name"] for item in payload["items"]] == ["Higher Gap", "Lower Gap"]
        assert payload["items"][0]["gap_vs_buy_hold_pct"] == 16.0
        assert payload["items"][0]["return_over_drawdown"] == 3.5

    def test_completed_run_rankings_support_filters(self, client):
        self._seed_completed_campaign(
            name="Corpus Manual",
            strategy="corpus_trend",
            basket_source="manual",
            tickers=["MSFT", "NVDA"],
            last_result={
                "completed_at": "2026-04-14T12:00:00+00:00",
                "winner": "strategy",
                "strategy_ending_equity": 12100,
                "buy_hold_ending_equity": 11500,
                "return_gap_pct": 6.0,
                "equity_gap": 600,
                "max_drawdown_pct": 7.0,
                "traded_tickers": 2,
                "order_count": 4,
            },
        )
        self._seed_completed_campaign(
            name="CCI Preset",
            strategy="cci_hysteresis",
            basket_source="preset",
            preset="focus",
            last_result={
                "completed_at": "2026-04-14T13:00:00+00:00",
                "winner": "buy_hold",
                "strategy_ending_equity": 10800,
                "buy_hold_ending_equity": 11200,
                "return_gap_pct": -4.0,
                "equity_gap": -400,
                "max_drawdown_pct": 4.0,
                "traded_tickers": 4,
                "order_count": 3,
            },
        )

        resp = client.get(
            "/api/portfolio/campaigns/completed-runs",
            query_string={"strategy": "corpus_trend", "basket_source": "manual"},
        )

        assert resp.status_code == 200
        payload = resp.get_json()
        assert len(payload["items"]) == 1
        assert payload["items"][0]["campaign_name"] == "Corpus Manual"
        assert payload["items"][0]["strategy"] == "corpus_trend"
        assert payload["items"][0]["basket_source"] == "manual"

    def test_compare_portfolio_runs_returns_side_by_side_rows_and_metric_winners(self, client):
        _campaign_a, run_a = self._seed_completed_campaign(
            name="Gap Leader",
            strategy="corpus_trend",
            basket_source="manual",
            tickers=["MSFT", "NVDA"],
            last_result={
                "completed_at": "2026-04-14T12:00:00+00:00",
                "winner": "strategy",
                "strategy_ending_equity": 13000,
                "buy_hold_ending_equity": 11500,
                "return_gap_pct": 15.0,
                "equity_gap": 1500,
                "max_drawdown_pct": 10.0,
                "traded_tickers": 2,
                "order_count": 7,
            },
        )
        _campaign_b, run_b = self._seed_completed_campaign(
            name="Drawdown Leader",
            strategy="cci_hysteresis",
            basket_source="preset",
            preset="focus",
            last_result={
                "completed_at": "2026-04-14T13:00:00+00:00",
                "winner": "strategy",
                "strategy_ending_equity": 11800,
                "buy_hold_ending_equity": 11000,
                "return_gap_pct": 8.0,
                "equity_gap": 800,
                "max_drawdown_pct": 4.0,
                "traded_tickers": 4,
                "order_count": 5,
            },
        )

        resp = client.get(
            "/api/portfolio/campaigns/compare",
            query_string={"run_ids": f"{run_a},{run_b}"},
        )

        assert resp.status_code == 200
        payload = resp.get_json()
        assert [item["run_id"] for item in payload["items"]] == [run_a, run_b]
        assert payload["metric_winners"]["best_gap_vs_buy_hold"]["run_id"] == run_a
        assert payload["metric_winners"]["lowest_drawdown"]["run_id"] == run_b

    def test_compare_portfolio_runs_requires_run_ids(self, client):
        resp = client.get("/api/portfolio/campaigns/compare")

        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Provide one or more run_ids"

    def test_watchlist_trends_returns_disk_snapshots_on_cold_memory_cache(self, client):
        import routes.watchlist as watchlist_module

        snapshot_row = {
            "ticker": "AAPL",
            "daily": {"ribbon": {"date": "2024-03-15", "dir": "bullish"}},
            "weekly": {"ribbon": {"date": "2024-03-08", "dir": "bullish"}},
            "trade_setup": {},
        }
        watchlist_module._save_disk_trend_row("AAPL", "2024-03-15", "2024-03-08", snapshot_row)

        with patch("routes.watchlist._build_watchlist_trends", return_value=[]):
            resp = client.get("/api/watchlist/trends")

        assert resp.status_code == 200
        assert resp.get_json() == {
            "items": [
                snapshot_row,
                {"ticker": "TSLA", "daily": {}, "weekly": {}, "trade_setup": {}},
            ],
            "loading": True,
            "stale": False,
        }

    def test_watchlist_trends_uses_stale_disk_rows_while_refreshing_new_version(self, client):
        import routes.watchlist as watchlist_module

        stale_row = {
            "ticker": "AAPL",
            "daily": {"ribbon": {"date": "2024-03-15", "dir": "bullish"}},
            "weekly": {"ribbon": {"date": "2024-03-08", "dir": "bullish"}},
        }
        path = watchlist_module._trend_cache_path("AAPL")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(
                {
                    "version": watchlist_module._TRENDS_CACHE_VERSION - 1,
                    "period": watchlist_module._TRENDS_PERIOD,
                    "multiplier": watchlist_module._TRENDS_MULTIPLIER,
                    "daily_date": "2024-03-15",
                    "weekly_date": "2024-03-08",
                    "row": stale_row,
                }
            )
        )

        with patch("routes.watchlist._build_watchlist_trends", return_value=[]):
            resp = client.get("/api/watchlist/trends")

        assert resp.status_code == 200
        assert resp.get_json() == {
            "items": [
                {
                    "ticker": "AAPL",
                    "daily": stale_row["daily"],
                    "weekly": stale_row["weekly"],
                    "trade_setup": {},
                },
                {"ticker": "TSLA", "daily": {}, "weekly": {}, "trade_setup": {}},
            ],
            "loading": True,
            "stale": False,
        }

    def test_watchlist_trends_handles_malformed_rows(self, client):
        malformed = [
            {"ticker": "AAPL", "daily": {}, "weekly": {}, "trade_setup": {}},
            {"ticker": "TSLA", "daily": {"ribbon": {"date": None, "dir": None}}, "weekly": {}, "trade_setup": {}},
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
            "trade_setup": {"daily": {"score": 42}, "weekly": {"score": 55}, "shared": {"price": 123.45}},
        }

        with patch("routes.watchlist.cached_download", side_effect=[sample_df, weekly_df, sample_df, weekly_df]):
            with patch(
                "routes.watchlist.compute_all_trend_flips",
                side_effect=[expected_row["daily"], expected_row["weekly"]],
            ) as mock_flips:
                with patch(
                    "routes.watchlist.compute_trade_setup",
                    return_value=expected_row["trade_setup"],
                ):
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
        assert "trend_flips" in data
        assert "trade_setup" in data
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
            "weekly_core_overlay_v1",
            "ema_9_26",
            "semis_persist_v1",
            "bb_breakout",
            "ema_crossover",
            "cci_trend",
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
        assert "buy_hold_equity_curve" in strategies["weekly_core_overlay_v1"]
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
        weekly_core_overlay = data["strategies"]["weekly_core_overlay_v1"]
        ema_9_26 = data["strategies"]["ema_9_26"]
        semis_persist = data["strategies"]["semis_persist_v1"]
        bb_breakout = data["strategies"]["bb_breakout"]
        ema_crossover = data["strategies"]["ema_crossover"]
        cci_trend = data["strategies"]["cci_trend"]
        cci_hysteresis = data["strategies"]["cci_hysteresis"]
        polymarket = data["strategies"]["polymarket"]

        assert ribbon["confirmation_mode"] == "layered_30_70"
        assert ribbon["confirmation_supported"] is True
        assert ribbon["confirmation_starter_fraction"] == pytest.approx(0.30)
        assert ribbon["confirmation_confirmed_fraction"] == pytest.approx(0.70)
        assert corpus["confirmation_mode"] == "layered_30_70"
        assert corpus["confirmation_supported"] is True
        assert layered["confirmation_supported"] is False
        assert weekly_core_overlay["confirmation_supported"] is False
        assert ema_9_26["confirmation_supported"] is True
        assert semis_persist["confirmation_supported"] is False
        assert bb_breakout["confirmation_supported"] is True
        assert ema_crossover["confirmation_supported"] is True
        assert cci_trend["confirmation_supported"] is True
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
        ema_9_26 = data["strategies"]["ema_9_26"]
        ema_crossover = data["strategies"]["ema_crossover"]
        bb_breakout = data["strategies"]["bb_breakout"]
        cci_trend = data["strategies"]["cci_trend"]
        assert ribbon["confirmation_mode"] == "escalation_50_50"
        assert ribbon["confirmation_supported"] is True
        assert ribbon["confirmation_starter_fraction"] == pytest.approx(0.50)
        assert ribbon["confirmation_confirmed_fraction"] == pytest.approx(0.50)
        assert "base 50%" in ribbon["confirmation_hint"].lower()
        assert corpus["confirmation_supported"] is True
        assert ema_9_26["confirmation_supported"] is True
        assert ema_crossover["confirmation_supported"] is True
        assert bb_breakout["confirmation_supported"] is True
        assert cci_trend["confirmation_supported"] is True

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
