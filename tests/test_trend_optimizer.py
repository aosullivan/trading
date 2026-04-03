import pandas as pd

import lib.trend_optimizer as trend_optimizer
from lib.trend_optimizer import (
    DateWindow,
    EvaluationTarget,
    LoadedFrame,
    OptimizerConfig,
    build_date_windows,
    build_evaluation_targets,
    build_ribbon_configs,
    ribbon_config_id,
    run_optimizer,
)


def _synthetic_loaded_frame() -> LoadedFrame:
    idx = pd.date_range("2024-01-01", periods=12, freq="D")
    df = pd.DataFrame(
        {
            "Open": [100 + i for i in range(len(idx))],
            "High": [101 + i for i in range(len(idx))],
            "Low": [99 + i for i in range(len(idx))],
            "Close": [100 + i for i in range(len(idx))],
            "Volume": [1_000_000 for _ in range(len(idx))],
        },
        index=idx,
    )
    return LoadedFrame(full_df=df, view_df=df.iloc[2:10].copy(), prior_direction_source=df)


def _always_available_loader(_target: EvaluationTarget):
    return _synthetic_loaded_frame(), ""


def test_build_ribbon_configs_returns_exact_grid_with_stable_ids():
    configs = build_ribbon_configs()
    configs_again = build_ribbon_configs()

    assert len(configs) == 2187
    assert len({config.config_id for config in configs}) == 2187
    assert configs[0].params == {
        "ema_period": 13,
        "atr_period": 10,
        "fast_period": 4,
        "slow_period": 13,
        "smooth_period": 3,
        "collapse_threshold": 0.06,
        "expand_threshold": 0.12,
    }
    assert configs[-1].params == {
        "ema_period": 34,
        "atr_period": 20,
        "fast_period": 8,
        "slow_period": 34,
        "smooth_period": 8,
        "collapse_threshold": 0.1,
        "expand_threshold": 0.18,
    }
    assert [config.config_id for config in configs] == [
        config.config_id for config in configs_again
    ]
    assert configs[0].config_id == ribbon_config_id(configs[0].params)


def test_build_date_windows_uses_exact_recency_weighted_manifest():
    windows = build_date_windows(as_of="2026-04-02")

    assert len(windows) == 56
    assert sum(window.duration == "6m" for window in windows) == 19
    assert sum(window.duration == "1y" for window in windows) == 14
    assert sum(window.duration == "2y" for window in windows) == 9
    assert sum(window.duration == "3y" for window in windows) == 8
    assert sum(window.duration == "5y" for window in windows) == 4
    assert sum(window.duration == "8y" for window in windows) == 2
    assert windows[0] == DateWindow(
        window_id="6m_2025-10-02_2026-04-02",
        duration="6m",
        start_date="2025-10-02",
        end_date="2026-04-02",
        months=6,
    )
    assert windows[-1] == DateWindow(
        window_id="8y_2016-04-02_2024-04-02",
        duration="8y",
        start_date="2016-04-02",
        end_date="2024-04-02",
        months=96,
    )


def test_build_evaluation_targets_normalizes_spx_and_marks_skips():
    windows = [
        DateWindow(
            window_id="8y_2016-04-02_2024-04-02",
            duration="8y",
            start_date="2016-04-02",
            end_date="2024-04-02",
            months=96,
        ),
        DateWindow(
            window_id="6m_2025-10-02_2026-04-02",
            duration="6m",
            start_date="2025-10-02",
            end_date="2026-04-02",
            months=6,
        ),
    ]

    def loader(target: EvaluationTarget):
        if target.ticker == "ETH-USD" and target.start_date == "2016-04-02":
            return None, "skipped_insufficient_history"
        return _synthetic_loaded_frame(), ""

    targets = build_evaluation_targets(
        tickers=["SPX", "ETH-USD"],
        intervals=["1d"],
        windows=windows,
        frame_loader=loader,
    )

    assert len(targets) == 4
    assert targets[0].ticker == "SPX"
    assert targets[0].data_ticker == "^GSPC"
    eth_old = [
        target
        for target in targets
        if target.ticker == "ETH-USD" and target.window_id == "8y_2016-04-02_2024-04-02"
    ][0]
    assert eth_old.status == "skipped"
    assert eth_old.skip_reason == "skipped_insufficient_history"


def test_run_optimizer_resumes_without_recomputing_completed_rows(tmp_path, monkeypatch):
    config = OptimizerConfig(
        config_id="cfg_resume",
        strategy="ribbon",
        params={
            "ema_period": 13,
            "atr_period": 10,
            "fast_period": 4,
            "slow_period": 13,
            "smooth_period": 3,
            "collapse_threshold": 0.06,
            "expand_threshold": 0.12,
        },
    )
    window = DateWindow(
        window_id="6m_2025-10-02_2026-04-02",
        duration="6m",
        start_date="2025-10-02",
        end_date="2026-04-02",
        months=6,
    )
    calls = {"count": 0}

    def fake_evaluate_ribbon_config(config, target, loaded_frame, drawdown_weight=0.45):
        calls["count"] += 1
        return {
            "config_id": config.config_id,
            "ticker": target.ticker,
            "data_ticker": target.data_ticker,
            "interval": target.interval,
            "window_id": target.window_id,
            "duration": target.duration,
            "start_date": target.start_date,
            "end_date": target.end_date,
            "status": "completed",
            "skip_reason": "",
            "score": 4.2,
            "net_profit_pct": 5.0,
            "max_drawdown_pct": 1.0,
            "total_trades": 2,
            "trades_per_year": 4.0,
            "error": "",
            "completed_at": "2026-04-02T00:00:00",
        }

    monkeypatch.setattr(
        trend_optimizer,
        "evaluate_ribbon_config",
        fake_evaluate_ribbon_config,
    )

    kwargs = {
        "run_id": "resume-smoke",
        "as_of": "2026-04-02",
        "db_path": tmp_path / "optimizer.sqlite3",
        "tickers": ["AAPL"],
        "intervals": ["1d"],
        "configs": [config],
        "windows": [window],
        "frame_loader": _always_available_loader,
        "progress_every": 0,
    }

    first = run_optimizer(**kwargs)
    second = run_optimizer(**kwargs)

    assert first["recorded_evaluations"] == 1
    assert second["recorded_evaluations"] == 1
    assert calls["count"] == 1
    assert second["top_configs"][0]["config_id"] == "cfg_resume"


def test_run_optimizer_filters_overtrading_configs_from_rankings(tmp_path, monkeypatch):
    low_turnover = OptimizerConfig(
        config_id="cfg_low_turnover",
        strategy="ribbon",
        params={
            "ema_period": 21,
            "atr_period": 14,
            "fast_period": 6,
            "slow_period": 21,
            "smooth_period": 5,
            "collapse_threshold": 0.08,
            "expand_threshold": 0.15,
        },
    )
    high_turnover = OptimizerConfig(
        config_id="cfg_high_turnover",
        strategy="ribbon",
        params={
            "ema_period": 13,
            "atr_period": 10,
            "fast_period": 4,
            "slow_period": 13,
            "smooth_period": 3,
            "collapse_threshold": 0.06,
            "expand_threshold": 0.12,
        },
    )
    window = DateWindow(
        window_id="1y_2025-04-02_2026-04-02",
        duration="1y",
        start_date="2025-04-02",
        end_date="2026-04-02",
        months=12,
    )

    def fake_evaluate_ribbon_config(config, target, loaded_frame, drawdown_weight=0.45):
        if config.config_id == "cfg_high_turnover":
            net_profit_pct = 40.0
            max_drawdown_pct = 2.0
            trades_per_year = 8.5
        else:
            net_profit_pct = 12.0
            max_drawdown_pct = 3.0
            trades_per_year = 4.0
        return {
            "config_id": config.config_id,
            "ticker": target.ticker,
            "data_ticker": target.data_ticker,
            "interval": target.interval,
            "window_id": target.window_id,
            "duration": target.duration,
            "start_date": target.start_date,
            "end_date": target.end_date,
            "status": "completed",
            "skip_reason": "",
            "score": net_profit_pct - drawdown_weight * max_drawdown_pct,
            "net_profit_pct": net_profit_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "total_trades": 4,
            "trades_per_year": trades_per_year,
            "error": "",
            "completed_at": "2026-04-02T00:00:00",
        }

    monkeypatch.setattr(
        trend_optimizer,
        "evaluate_ribbon_config",
        fake_evaluate_ribbon_config,
    )

    result = run_optimizer(
        run_id="ranking-smoke",
        as_of="2026-04-02",
        db_path=tmp_path / "optimizer.sqlite3",
        tickers=["AAPL"],
        intervals=["1d"],
        configs=[high_turnover, low_turnover],
        windows=[window],
        frame_loader=_always_available_loader,
        max_round_trips_per_year=6.0,
        progress_every=0,
    )

    assert [row["config_id"] for row in result["top_configs"]] == ["cfg_low_turnover"]
    assert result["top_configs"][0]["avg_trades_per_year"] == 4.0
