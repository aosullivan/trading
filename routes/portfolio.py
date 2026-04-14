"""Portfolio backtesting API route with SSE progress streaming."""

from __future__ import annotations

import json as _json
import re
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, request, jsonify, stream_with_context

from lib.backtesting import MoneyManagementConfig, apply_managed_sizing_defaults
from lib.data_fetching import (
    cached_download,
    is_treasury_price_ticker,
    is_treasury_yield_ticker,
    normalize_ticker,
)
from lib import portfolio_campaigns
from lib.portfolio_backtesting import (
    DEFAULT_ALLOCATOR_POLICY,
    SUPPORTED_ALLOCATOR_POLICIES,
    backtest_portfolio,
)
from lib.portfolio_research import (
    DEFAULT_RESEARCH_ALLOCATOR_POLICIES,
    DEFAULT_RESEARCH_STRATEGIES,
    PORTFOLIO_PRESET_BASKETS,
    build_research_campaign_payload,
    research_matrix_catalog,
)
from lib.technical_indicators import compute_corpus_trend_signal, compute_cci_hysteresis
from lib.ribbon_signals import compute_confirmed_ribbon_direction
from lib.settings import DAILY_WARMUP_DAYS
from routes.watchlist import load_watchlist

bp = Blueprint("portfolio", __name__)

_SCHEDULER_THREAD = None
_SCHEDULER_THREAD_LOCK = threading.Lock()

_PORTFOLIO_DEFAULT_MM = MoneyManagementConfig(
    **apply_managed_sizing_defaults(
        {
            "sizing_method": "fixed_fraction",
            "stop_type": "atr",
            "stop_atr_period": 20,
            "stop_atr_multiple": 3.0,
        }
    )
)

_NON_TRADABLE_RAW = {
    "SPX", "DJI", "IXIC", "RUT", "VIX",
    "TNX", "TYX", "IRX", "FVX",
}

_SUPPORTED_PORTFOLIO_STRATEGIES = {
    "ribbon",
    "corpus_trend",
    "cci_hysteresis",
}
_PORTFOLIO_PRESET_BASKETS = PORTFOLIO_PRESET_BASKETS


def _is_tradable_raw(raw_ticker: str) -> bool:
    """Check tradability using the *un-normalized* ticker (before ^ prefixing)."""
    t = raw_ticker.upper().strip()
    if t in _NON_TRADABLE_RAW:
        return False
    if is_treasury_yield_ticker(t) or is_treasury_price_ticker(t):
        return False
    if t.startswith("^"):
        return False
    return True


def _parse_portfolio_mm_config() -> MoneyManagementConfig:
    sizing = request.args.get("mm_sizing", "")
    stop = request.args.get("mm_stop", "")
    stop_val = request.args.get("mm_stop_val", "")
    risk_cap = request.args.get("mm_risk_cap", "")
    compound = request.args.get("mm_compound", "trade")

    if not sizing and not stop and not risk_cap and compound == "trade":
        return _PORTFOLIO_DEFAULT_MM

    kwargs: dict = {
        "sizing_method": sizing or "fixed_fraction",
        "stop_type": stop or "atr",
        "stop_atr_period": 20,
        "stop_atr_multiple": 3.0,
    }
    if stop and stop_val:
        val = float(stop_val)
        if stop == "atr":
            kwargs["stop_atr_multiple"] = val
        elif stop == "pct":
            kwargs["stop_pct"] = val / 100.0
    if risk_cap:
        kwargs["vol_to_equity_limit"] = float(risk_cap)
    if compound != "trade":
        kwargs["compounding"] = compound

    return MoneyManagementConfig(**apply_managed_sizing_defaults(kwargs))


def _warmup_start(start: str) -> str:
    dt = datetime.strptime(start, "%Y-%m-%d")
    return (dt - timedelta(days=DAILY_WARMUP_DAYS)).strftime("%Y-%m-%d")


def _tokenize_tickers(raw_value: str) -> list[str]:
    parts = re.split(r"[\s,]+", raw_value or "")
    seen: set[str] = set()
    tickers: list[str] = []
    for part in parts:
        ticker = part.upper().strip()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def _validate_strategy(strategy: str) -> str:
    strategy = strategy.strip() or "ribbon"
    if strategy not in _SUPPORTED_PORTFOLIO_STRATEGIES:
        raise ValueError(
            f"Unsupported portfolio strategy '{strategy}'. "
            f"Supported: {', '.join(sorted(_SUPPORTED_PORTFOLIO_STRATEGIES))}"
        )
    return strategy


def _parse_strategy() -> str:
    return _validate_strategy(request.args.get("strategy", "ribbon"))


def _validate_allocator_policy(policy: str) -> str:
    policy = policy.strip() or DEFAULT_ALLOCATOR_POLICY
    if policy not in SUPPORTED_ALLOCATOR_POLICIES:
        raise ValueError(
            f"Unsupported allocator policy '{policy}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_ALLOCATOR_POLICIES))}"
        )
    return policy


def _parse_allocator_policy() -> str:
    return _validate_allocator_policy(request.args.get("allocator_policy", DEFAULT_ALLOCATOR_POLICY))


def _resolve_basket_request_values(
    source: str,
    preset: str,
    manual_tickers: list[str],
) -> tuple[list[str], dict]:
    source = source.strip() or "watchlist"
    preset = preset.strip().lower()

    if source == "watchlist":
        raw_tickers = load_watchlist()
    elif source == "manual":
        if not manual_tickers:
            raise ValueError("Manual basket requires at least one ticker")
        raw_tickers = manual_tickers
    elif source == "preset":
        preset_key = preset or "focus"
        raw_tickers = _PORTFOLIO_PRESET_BASKETS.get(preset_key)
        if not raw_tickers:
            raise ValueError(
                f"Unsupported basket preset '{preset_key}'. "
                f"Supported: {', '.join(sorted(_PORTFOLIO_PRESET_BASKETS))}"
            )
        preset = preset_key
    else:
        raise ValueError("Unsupported basket source. Supported: watchlist, manual, preset")

    return raw_tickers, {
        "source": source,
        "preset": preset or None,
        "requested_tickers": manual_tickers if source == "manual" else list(raw_tickers),
    }


def _resolve_basket_request() -> tuple[list[str], dict]:
    return _resolve_basket_request_values(
        request.args.get("basket_source", "watchlist"),
        request.args.get("preset", ""),
        _tokenize_tickers(request.args.get("tickers", "")),
    )


def _fetch_ticker_data(ticker: str, start: str, end: str | None):
    warmup = _warmup_start(start)
    kwargs = {"start": warmup, "interval": "1d", "progress": False}
    if end:
        kwargs["end"] = end
    df = cached_download(ticker, **kwargs)
    if df is not None and not df.empty:
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        if df.index.duplicated().any():
            df = df[~df.index.duplicated(keep="last")]
    return ticker, df


def _compute_signal_for_strategy(strategy: str, ticker: str, df):
    if strategy == "ribbon":
        return compute_confirmed_ribbon_direction(ticker, df)
    if strategy == "corpus_trend":
        _entry_upper, _exit_lower, _atr, _stop_line, direction = compute_corpus_trend_signal(df)
        return direction
    if strategy == "cci_hysteresis":
        _cci, direction = compute_cci_hysteresis(df)
        return direction
    raise ValueError(f"Unsupported portfolio strategy '{strategy}'")


def _compute_signal(strategy: str, ticker: str, df):
    """Compute a retained strategy direction for a single ticker."""
    try:
        direction = _compute_signal_for_strategy(strategy, ticker, df)
        return ticker, direction
    except Exception:
        return ticker, None


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {_json.dumps(data)}\n\n"


def _resolve_requested_portfolio() -> tuple[str, str, list[str], list[str], dict]:
    strategy = _parse_strategy()
    allocator_policy = _parse_allocator_policy()
    tickers_raw, basket_meta = _resolve_basket_request()
    if not tickers_raw:
        raise ValueError("Selected basket is empty")

    tradable_raw = [t for t in tickers_raw if _is_tradable_raw(t)]
    skipped = sorted(set(t.upper() for t in tickers_raw if not _is_tradable_raw(t)))
    tickers = [normalize_ticker(t) for t in tradable_raw]
    if not tickers:
        raise ValueError("No tradable tickers found in the selected basket")

    basket = {
        **basket_meta,
        "effective_tickers": tickers,
        "included_count": len(tickers),
        "skipped_count": len(skipped),
    }
    return strategy, allocator_policy, tickers, skipped, basket


def _money_management_payload(mm_config: MoneyManagementConfig) -> dict:
    payload = {
        "sizing_method": mm_config.sizing_method,
        "risk_fraction": mm_config.risk_fraction,
        "stop_type": mm_config.stop_type,
        "heat_limit": None,
        "initial_capital": mm_config.initial_capital,
    }
    if getattr(mm_config, "stop_atr_period", None) is not None:
        payload["stop_atr_period"] = mm_config.stop_atr_period
    if getattr(mm_config, "stop_atr_multiple", None) is not None:
        payload["stop_atr_multiple"] = mm_config.stop_atr_multiple
    if getattr(mm_config, "stop_pct", None) is not None:
        payload["stop_pct"] = mm_config.stop_pct
    if getattr(mm_config, "vol_to_equity_limit", None) is not None:
        payload["vol_to_equity_limit"] = mm_config.vol_to_equity_limit
    if getattr(mm_config, "compounding", None):
        payload["compounding"] = mm_config.compounding
    return payload


def _build_mm_config_from_saved_payload(payload: dict | None) -> MoneyManagementConfig:
    if not payload:
        return _PORTFOLIO_DEFAULT_MM

    kwargs = {
        "sizing_method": payload.get("sizing_method") or "fixed_fraction",
        "stop_type": payload.get("stop_type") or "atr",
        "stop_atr_period": int(payload.get("stop_atr_period", 20)),
        "stop_atr_multiple": float(payload.get("stop_atr_multiple", 3.0)),
    }
    if payload.get("risk_fraction") is not None:
        kwargs["risk_fraction"] = float(payload["risk_fraction"])
    if payload.get("stop_pct") is not None:
        kwargs["stop_pct"] = float(payload["stop_pct"])
    if payload.get("vol_to_equity_limit") is not None:
        kwargs["vol_to_equity_limit"] = float(payload["vol_to_equity_limit"])
    if payload.get("compounding"):
        kwargs["compounding"] = payload["compounding"]
    return MoneyManagementConfig(**apply_managed_sizing_defaults(kwargs))


def _classify_basket_shape(tickers: list[str]) -> dict:
    count = len(tickers)
    crypto_count = sum(1 for ticker in tickers if ticker.upper().endswith("-USD"))
    equity_count = max(0, count - crypto_count)
    if count <= 5:
        size_bucket = "small"
    elif count >= 10:
        size_bucket = "large"
    else:
        size_bucket = "medium"

    if crypto_count and equity_count:
        composition = "mixed"
    elif crypto_count:
        composition = "crypto_only"
    else:
        composition = "equity_only"

    return {
        "count": count,
        "size_bucket": size_bucket,
        "composition": composition,
        "crypto_count": crypto_count,
        "equity_count": equity_count,
    }


def _build_comparison_summary(result, initial_capital: float) -> dict:
    strategy_curve = result.portfolio_equity_curve or []
    buy_hold_curve = result.portfolio_buy_hold_curve or []

    strategy_end = (
        float(strategy_curve[-1]["value"])
        if strategy_curve
        else float(initial_capital)
    )
    buy_hold_end = (
        float(buy_hold_curve[-1]["value"])
        if buy_hold_curve
        else float(initial_capital)
    )
    strategy_return_pct = float(result.portfolio_summary.get("net_profit_pct", 0))
    buy_hold_return_pct = (
        ((buy_hold_end / float(initial_capital)) - 1) * 100
        if initial_capital
        else 0.0
    )
    equity_gap = round(strategy_end - buy_hold_end, 2)
    return_gap_pct = round(strategy_return_pct - buy_hold_return_pct, 2)
    winner = "tie"
    if equity_gap > 0:
        winner = "strategy"
    elif equity_gap < 0:
        winner = "buy_hold"

    buy_hold_max_drawdown_pct = _curve_max_drawdown_pct(buy_hold_curve)
    strategy_max_drawdown_pct = float(result.portfolio_summary.get("max_drawdown_pct", 0) or 0)
    drawdown_gap_pct = round(buy_hold_max_drawdown_pct - strategy_max_drawdown_pct, 2)
    upside_capture_pct = None
    if buy_hold_return_pct > 0:
        upside_capture_pct = round((strategy_return_pct / buy_hold_return_pct) * 100, 2)

    return {
        "strategy_ending_equity": round(strategy_end, 2),
        "buy_hold_ending_equity": round(buy_hold_end, 2),
        "strategy_return_pct": round(strategy_return_pct, 2),
        "buy_hold_return_pct": round(buy_hold_return_pct, 2),
        "buy_hold_max_drawdown_pct": buy_hold_max_drawdown_pct,
        "drawdown_gap_pct": drawdown_gap_pct,
        "upside_capture_pct": upside_capture_pct,
        "equity_gap": equity_gap,
        "return_gap_pct": return_gap_pct,
        "winner": winner,
    }


def _curve_max_drawdown_pct(curve: list[dict]) -> float:
    peak = None
    max_drawdown = 0.0
    for point in curve or []:
        value = float(point.get("value", 0) or 0)
        if peak is None or value > peak:
            peak = value
        if not peak:
            continue
        drawdown = ((peak - value) / peak) * 100.0
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return round(max_drawdown, 2)


def _build_order_ledger(per_ticker: dict[str, dict]) -> list[dict]:
    orders: list[dict] = []
    for ticker, payload in per_ticker.items():
        for trade in payload.get("trades", []):
            orders.append(
                {
                    "ticker": ticker,
                    "entry_date": trade.get("entry_date"),
                    "entry_price": trade.get("entry_price"),
                    "exit_date": trade.get("exit_date"),
                    "exit_price": trade.get("exit_price"),
                    "quantity": trade.get("quantity"),
                    "side": trade.get("type", "long"),
                    "status": "open" if trade.get("open") else "closed",
                    "pnl": trade.get("pnl"),
                    "pnl_pct": trade.get("pnl_pct"),
                }
            )
    orders.sort(
        key=lambda order: (
            order.get("exit_date") or "",
            order.get("entry_date") or "",
            order.get("ticker") or "",
        ),
        reverse=True,
    )
    return orders


def _serialize_result(result, skipped, mm_config, heat_limit, strategy, allocator_policy, basket):
    per_ticker_json = {}
    for t, data in result.per_ticker.items():
        per_ticker_json[t] = {
            "trades": data["trades"],
            "summary": data["summary"],
            "equity_contribution": data["equity_contribution"],
        }

    orders = _build_order_ledger(per_ticker_json)
    traded_tickers = sum(
        1
        for data in per_ticker_json.values()
        if (data["summary"].get("total_trades", 0) + data["summary"].get("open_trades", 0)) > 0
    )
    active_tickers = sum(
        1
        for data in per_ticker_json.values()
        if data["equity_contribution"]
        and float(data["equity_contribution"][-1]["value"]) > 0
    )
    basket_diagnostics = {
        **_classify_basket_shape(result.tickers),
        "traded_tickers": traded_tickers,
        "active_tickers": active_tickers,
        "skipped_count": len(skipped),
    }
    comparison = _build_comparison_summary(result, mm_config.initial_capital)

    return {
        "strategy": strategy,
        "basket": basket,
        "basket_diagnostics": basket_diagnostics,
        "comparison": comparison,
        "orders": orders,
        "tickers": result.tickers,
        "skipped": skipped,
        "portfolio_equity_curve": result.portfolio_equity_curve,
        "portfolio_buy_hold_curve": result.portfolio_buy_hold_curve,
        "portfolio_summary": result.portfolio_summary,
        "portfolio_diagnostics": result.portfolio_diagnostics,
        "per_ticker": per_ticker_json,
        "heat_series": result.heat_series,
        "config": {
            "strategy": strategy,
            "allocator_policy": allocator_policy,
            "basket_source": basket["source"],
            "basket_preset": basket.get("preset"),
            "requested_tickers": basket["requested_tickers"],
            "sizing_method": mm_config.sizing_method,
            "risk_fraction": mm_config.risk_fraction,
            "stop_type": mm_config.stop_type,
            "heat_limit": heat_limit,
            "initial_capital": mm_config.initial_capital,
        },
    }


def _summarize_campaign_result(payload: dict) -> dict:
    comparison = payload.get("comparison", {})
    summary = payload.get("portfolio_summary", {})
    diagnostics = payload.get("portfolio_diagnostics", {})
    basket_diagnostics = payload.get("basket_diagnostics", {})
    return {
        "completed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "allocator_policy": payload.get("config", {}).get("allocator_policy", DEFAULT_ALLOCATOR_POLICY),
        "winner": comparison.get("winner"),
        "strategy_ending_equity": comparison.get("strategy_ending_equity"),
        "buy_hold_ending_equity": comparison.get("buy_hold_ending_equity"),
        "strategy_return_pct": comparison.get("strategy_return_pct"),
        "buy_hold_return_pct": comparison.get("buy_hold_return_pct"),
        "return_gap_pct": comparison.get("return_gap_pct"),
        "equity_gap": comparison.get("equity_gap"),
        "max_drawdown_pct": summary.get("max_drawdown_pct"),
        "buy_hold_max_drawdown_pct": comparison.get("buy_hold_max_drawdown_pct"),
        "drawdown_gap_pct": comparison.get("drawdown_gap_pct"),
        "upside_capture_pct": comparison.get("upside_capture_pct"),
        "avg_invested_pct": diagnostics.get("avg_invested_pct"),
        "avg_active_positions": diagnostics.get("avg_active_positions"),
        "redeployment_events": diagnostics.get("redeployment_events"),
        "avg_redeployment_lag_bars": diagnostics.get("avg_redeployment_lag_bars"),
        "turnover_pct": diagnostics.get("turnover_pct"),
        "max_single_name_weight_pct": diagnostics.get("max_single_name_weight_pct"),
        "traded_tickers": basket_diagnostics.get("traded_tickers"),
        "order_count": len(payload.get("orders", [])),
    }


def _execute_portfolio_payload(strategy, allocator_policy, tickers, skipped, basket, start, end, heat_limit, mm_config):
    ticker_data: dict = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_ticker_data, t, start, end): t for t in tickers}
        for fut in as_completed(futures):
            t, df = fut.result()
            if df is not None and not df.empty:
                ticker_data[t] = df

    if not ticker_data:
        raise ValueError("No data available")

    ticker_directions = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_compute_signal, strategy, t, ticker_data[t]): t
            for t in ticker_data
        }
        for fut in as_completed(futures):
            t, direction = fut.result()
            if direction is not None:
                ticker_directions[t] = direction

    if not ticker_directions:
        raise ValueError("Could not compute signals")

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    visible_data = {}
    visible_directions = {}
    for t in ticker_directions:
        df = ticker_data[t]
        mask = df.index >= start_dt
        if end:
            end_dt = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
            mask &= df.index < end_dt
        df_view = df.loc[mask]
        if df_view.empty:
            continue
        visible_data[t] = df_view
        visible_directions[t] = ticker_directions[t]

    if not visible_data:
        raise ValueError("No data in the selected date range")

    result = backtest_portfolio(
        visible_data,
        visible_directions,
        config=mm_config,
        heat_limit=heat_limit,
        allocator_policy=allocator_policy,
    )
    return _serialize_result(result, skipped, mm_config, heat_limit, strategy, allocator_policy, basket)


def _resolve_portfolio_request_from_run_spec(run_spec: dict):
    strategy = _validate_strategy(run_spec.get("strategy", "ribbon"))
    allocator_policy = _validate_allocator_policy(run_spec.get("allocator_policy", DEFAULT_ALLOCATOR_POLICY))
    raw_tickers, basket_meta = _resolve_basket_request_values(
        run_spec.get("basket_source", "watchlist"),
        run_spec.get("preset", "") or "",
        list(run_spec.get("tickers") or []),
    )
    if not raw_tickers:
        raise ValueError("Selected basket is empty")

    tradable_raw = [t for t in raw_tickers if _is_tradable_raw(t)]
    skipped = sorted(set(t.upper() for t in raw_tickers if not _is_tradable_raw(t)))
    tickers = [normalize_ticker(t) for t in tradable_raw]
    if not tickers:
        raise ValueError("No tradable tickers found in the selected basket")

    basket = {
        **basket_meta,
        "effective_tickers": tickers,
        "included_count": len(tickers),
        "skipped_count": len(skipped),
    }
    start = run_spec.get("start") or "2015-01-01"
    end = run_spec.get("end") or ""
    heat_limit = float(run_spec.get("heat_limit", 0.20))
    mm_config = _build_mm_config_from_saved_payload(run_spec.get("money_management"))
    return strategy, allocator_policy, tickers, skipped, basket, start, end, heat_limit, mm_config


def _campaign_worker(campaign_id: str) -> None:
    try:
        for run_id in portfolio_campaigns.queued_run_ids(campaign_id):
            campaign = portfolio_campaigns.get_campaign(campaign_id)
            if not campaign:
                break
            run = next((item for item in campaign.get("runs", []) if item["run_id"] == run_id), None)
            if run is None:
                continue
            portfolio_campaigns.update_run_state(campaign_id, run_id, status="running", last_error=None)
            try:
                args = _resolve_portfolio_request_from_run_spec(run)
                payload = _execute_portfolio_payload(*args)
                portfolio_campaigns.update_run_state(
                    campaign_id,
                    run_id,
                    status="completed",
                    last_result=_summarize_campaign_result(payload),
                    last_error=None,
                )
            except Exception as exc:
                portfolio_campaigns.update_run_state(
                    campaign_id,
                    run_id,
                    status="failed",
                    last_error=str(exc),
                )
    finally:
        portfolio_campaigns.end_campaign_execution(campaign_id)


def _start_campaign_worker(campaign_id: str) -> None:
    worker = threading.Thread(target=_campaign_worker, args=(campaign_id,), daemon=True)
    worker.start()


def _dispatch_due_campaigns() -> list[dict]:
    queued = portfolio_campaigns.claim_due_campaigns()
    for item in queued:
        campaign_id = item["campaign_id"]
        if portfolio_campaigns.begin_campaign_execution(campaign_id):
            _start_campaign_worker(campaign_id)
    return queued


def _scheduler_loop() -> None:
    while True:
        try:
            _dispatch_due_campaigns()
        except Exception:
            pass
        _time.sleep(30)


def _ensure_scheduler_started() -> None:
    global _SCHEDULER_THREAD
    with _SCHEDULER_THREAD_LOCK:
        if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
            return
        _SCHEDULER_THREAD = threading.Thread(target=_scheduler_loop, daemon=True)
        _SCHEDULER_THREAD.start()


@bp.route("/api/portfolio/backtest")
def portfolio_backtest():
    """Run a portfolio backtest with SSE progress streaming."""
    try:
        strategy, allocator_policy, tickers, skipped, basket = _resolve_requested_portfolio()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    start = request.args.get("start", "2015-01-01")
    end = request.args.get("end", "")
    heat_limit = float(request.args.get("heat_limit", "0.20"))
    mm_config = _parse_portfolio_mm_config()

    use_sse = request.args.get("stream", "1") == "1"
    if not use_sse:
        return _run_sync(strategy, allocator_policy, tickers, skipped, basket, start, end, heat_limit, mm_config)

    def generate():
        t0 = _time.perf_counter()
        n = len(tickers)
        yield _sse_event("progress", {
            "stage": "init",
            "message": (
                f"Portfolio: {strategy} on {basket['source']} basket "
                f"with {n} tradable tickers ({len(skipped)} skipped)"
            ),
            "pct": 0,
        })

        # --- Fetch data in parallel ---
        yield _sse_event("progress", {"stage": "fetch", "message": f"Fetching data for {n} tickers…", "pct": 5})
        ticker_data: dict = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch_ticker_data, t, start, end): t for t in tickers}
            done = 0
            for fut in as_completed(futures):
                t, df = fut.result()
                done += 1
                if df is not None and not df.empty:
                    ticker_data[t] = df
                if done % 5 == 0 or done == n:
                    pct = 5 + int(35 * done / n)
                    yield _sse_event("progress", {
                        "stage": "fetch",
                        "message": f"Fetched {done}/{n}",
                        "pct": pct,
                    })

        if not ticker_data:
            yield _sse_event("error_event", {"message": "No data available for any tradable ticker"})
            return

        # --- Compute signals in parallel ---
        sig_tickers = list(ticker_data.keys())
        ns = len(sig_tickers)
        yield _sse_event("progress", {"stage": "signals", "message": f"Computing signals for {ns} tickers…", "pct": 40})

        ticker_directions = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(_compute_signal, strategy, t, ticker_data[t]): t
                for t in sig_tickers
            }
            done = 0
            for fut in as_completed(futures):
                t, direction = fut.result()
                done += 1
                if direction is not None:
                    ticker_directions[t] = direction
                if done % 3 == 0 or done == ns:
                    pct = 40 + int(40 * done / ns)
                    yield _sse_event("progress", {
                        "stage": "signals",
                        "message": f"Signals {done}/{ns}",
                        "pct": pct,
                    })

        if not ticker_directions:
            yield _sse_event("error_event", {"message": "Could not compute signals for any ticker"})
            return

        # --- Trim to visible window ---
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        visible_data = {}
        visible_directions = {}
        for t in ticker_directions:
            df = ticker_data[t]
            mask = df.index >= start_dt
            if end:
                end_dt = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
                mask &= df.index < end_dt
            df_view = df.loc[mask]
            if df_view.empty:
                continue
            visible_data[t] = df_view
            visible_directions[t] = ticker_directions[t]

        if not visible_data:
            yield _sse_event("error_event", {"message": "No data in the selected date range"})
            return

        # --- Run portfolio backtest ---
        yield _sse_event("progress", {
            "stage": "backtest",
            "message": f"Running portfolio backtest ({len(visible_data)} tickers)…",
            "pct": 82,
        })

        result = backtest_portfolio(
            visible_data,
            visible_directions,
            config=mm_config,
            heat_limit=heat_limit,
            allocator_policy=allocator_policy,
        )

        yield _sse_event("progress", {"stage": "serialize", "message": "Building response…", "pct": 95})
        payload = _serialize_result(result, skipped, mm_config, heat_limit, strategy, allocator_policy, basket)

        elapsed = round(_time.perf_counter() - t0, 1)
        yield _sse_event("progress", {"stage": "done", "message": f"Done in {elapsed}s", "pct": 100})
        yield _sse_event("result", payload)

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@bp.route("/api/portfolio/campaigns", methods=["GET"])
def list_portfolio_campaigns():
    _ensure_scheduler_started()
    return jsonify({"items": portfolio_campaigns.list_campaigns()})


@bp.route("/api/portfolio/campaigns", methods=["POST"])
def create_portfolio_campaign():
    _ensure_scheduler_started()
    payload = request.get_json(silent=True) or {}
    campaign = portfolio_campaigns.create_campaign(payload)
    return jsonify(campaign), 201


@bp.route("/api/portfolio/research-matrix", methods=["GET"])
def get_portfolio_research_matrix():
    _ensure_scheduler_started()
    return jsonify(
        research_matrix_catalog(
            strategies=[item for item in DEFAULT_RESEARCH_STRATEGIES if item in _SUPPORTED_PORTFOLIO_STRATEGIES],
            allocator_policies=[
                item for item in DEFAULT_RESEARCH_ALLOCATOR_POLICIES if item in SUPPORTED_ALLOCATOR_POLICIES
            ],
        )
    )


@bp.route("/api/portfolio/campaigns/research-matrix", methods=["POST"])
def create_portfolio_research_matrix_campaign():
    _ensure_scheduler_started()
    payload = request.get_json(silent=True) or {}
    try:
        campaign_payload = build_research_campaign_payload(
            payload,
            supported_strategies=sorted(_SUPPORTED_PORTFOLIO_STRATEGIES),
            supported_allocator_policies=sorted(SUPPORTED_ALLOCATOR_POLICIES),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    campaign = portfolio_campaigns.create_campaign(campaign_payload)
    return jsonify({"campaign": campaign, "matrix": campaign_payload["matrix"]}), 201


@bp.route("/api/portfolio/campaigns/completed-runs", methods=["GET"])
def list_completed_portfolio_runs():
    _ensure_scheduler_started()
    payload = portfolio_campaigns.list_comparison_runs(
        campaign_id=request.args.get("campaign_id") or None,
        strategy=request.args.get("strategy") or None,
        basket_source=request.args.get("basket_source") or None,
        status=request.args.get("status", "completed") or None,
        sort_by=request.args.get("sort_by") or None,
    )
    return jsonify(payload)


@bp.route("/api/portfolio/campaigns/compare", methods=["GET"])
def compare_portfolio_runs():
    _ensure_scheduler_started()
    run_ids = [item.strip() for item in (request.args.get("run_ids") or "").split(",") if item.strip()]
    if not run_ids:
        return jsonify({"error": "Provide one or more run_ids"}), 400
    return jsonify(portfolio_campaigns.compare_run_ids(run_ids))


@bp.route("/api/portfolio/campaigns/<campaign_id>", methods=["GET"])
def get_portfolio_campaign(campaign_id: str):
    _ensure_scheduler_started()
    campaign = portfolio_campaigns.get_campaign(campaign_id)
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404
    return jsonify(campaign)


@bp.route("/api/portfolio/campaigns/<campaign_id>/queue", methods=["POST"])
def queue_portfolio_campaign(campaign_id: str):
    _ensure_scheduler_started()
    try:
        queued = portfolio_campaigns.queue_campaign(campaign_id)
    except KeyError:
        return jsonify({"error": "Campaign not found"}), 404

    if queued["queued"] == 0:
        return jsonify({"error": "No planned runs available to queue"}), 400
    if not portfolio_campaigns.begin_campaign_execution(campaign_id):
        return jsonify({"error": "Campaign is already running"}), 409

    _start_campaign_worker(campaign_id)
    campaign = portfolio_campaigns.get_campaign(campaign_id)
    return jsonify({"queued": queued["queued"], "campaign": campaign}), 202


@bp.route("/api/portfolio/campaigns/<campaign_id>/rerun", methods=["POST"])
def rerun_portfolio_campaign(campaign_id: str):
    _ensure_scheduler_started()
    try:
        queued = portfolio_campaigns.queue_campaign(campaign_id, rerun_all=True)
    except KeyError:
        return jsonify({"error": "Campaign not found"}), 404

    if queued["queued"] == 0:
        return jsonify({"error": "No runs available to rerun"}), 400
    if not portfolio_campaigns.begin_campaign_execution(campaign_id):
        return jsonify({"error": "Campaign is already running"}), 409

    _start_campaign_worker(campaign_id)
    campaign = portfolio_campaigns.get_campaign(campaign_id)
    return jsonify({"queued": queued["queued"], "campaign": campaign}), 202


@bp.route("/api/portfolio/campaigns/<campaign_id>/schedule", methods=["POST"])
def schedule_portfolio_campaign(campaign_id: str):
    _ensure_scheduler_started()
    payload = request.get_json(silent=True) or {}
    try:
        campaign = portfolio_campaigns.update_campaign_schedule(campaign_id, payload)
    except KeyError:
        return jsonify({"error": "Campaign not found"}), 404
    return jsonify(campaign)


@bp.route("/api/portfolio/campaigns/run-due", methods=["POST"])
def run_due_portfolio_campaigns():
    _ensure_scheduler_started()
    queued = _dispatch_due_campaigns()
    return jsonify({"queued_campaigns": queued, "count": len(queued)})


def _run_sync(strategy, allocator_policy, tickers, skipped, basket, start, end, heat_limit, mm_config):
    """Non-streaming fallback for programmatic callers."""
    try:
        payload = _execute_portfolio_payload(
            strategy,
            allocator_policy,
            tickers,
            skipped,
            basket,
            start,
            end,
            heat_limit,
            mm_config,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(payload)
