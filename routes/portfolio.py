"""Portfolio backtesting API route with SSE progress streaming."""

from __future__ import annotations

import json as _json
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from flask import Blueprint, Response, request, jsonify, stream_with_context

from lib.backtesting import MoneyManagementConfig, apply_managed_sizing_defaults
from lib.data_fetching import (
    cached_download,
    is_treasury_price_ticker,
    is_treasury_yield_ticker,
    normalize_ticker,
)
from lib.portfolio_backtesting import backtest_portfolio
from lib.ribbon_signals import compute_confirmed_ribbon_direction
from lib.settings import DAILY_WARMUP_DAYS
from routes.watchlist import load_watchlist

bp = Blueprint("portfolio", __name__)

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


def _compute_signal(ticker: str, df):
    """Compute ribbon direction for a single ticker; returns (ticker, series) or (ticker, None)."""
    try:
        direction = compute_confirmed_ribbon_direction(ticker, df)
        return ticker, direction
    except Exception:
        return ticker, None


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {_json.dumps(data)}\n\n"


@bp.route("/api/portfolio/backtest")
def portfolio_backtest():
    """Run a portfolio backtest with SSE progress streaming."""
    tickers_raw = load_watchlist()
    if not tickers_raw:
        return jsonify({"error": "Watchlist is empty"}), 400

    tradable_raw = [t for t in tickers_raw if _is_tradable_raw(t)]
    skipped = sorted(set(t.upper() for t in tickers_raw if not _is_tradable_raw(t)))
    tickers = [normalize_ticker(t) for t in tradable_raw]

    start = request.args.get("start", "2015-01-01")
    end = request.args.get("end", "")
    heat_limit = float(request.args.get("heat_limit", "0.20"))
    mm_config = _parse_portfolio_mm_config()

    use_sse = request.args.get("stream", "1") == "1"
    if not use_sse:
        return _run_sync(tickers, skipped, start, end, heat_limit, mm_config)

    def generate():
        t0 = _time.perf_counter()
        n = len(tickers)
        yield _sse_event("progress", {
            "stage": "init",
            "message": f"Portfolio: {n} tradable tickers ({len(skipped)} skipped)",
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
            futures = {pool.submit(_compute_signal, t, ticker_data[t]): t for t in sig_tickers}
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
            visible_data, visible_directions, config=mm_config, heat_limit=heat_limit
        )

        yield _sse_event("progress", {"stage": "serialize", "message": "Building response…", "pct": 95})

        per_ticker_json = {}
        for t, data in result.per_ticker.items():
            per_ticker_json[t] = {
                "trades": data["trades"],
                "summary": data["summary"],
                "equity_contribution": data["equity_contribution"],
            }

        payload = {
            "tickers": result.tickers,
            "skipped": skipped,
            "portfolio_equity_curve": result.portfolio_equity_curve,
            "portfolio_buy_hold_curve": result.portfolio_buy_hold_curve,
            "portfolio_summary": result.portfolio_summary,
            "per_ticker": per_ticker_json,
            "heat_series": result.heat_series,
            "config": {
                "sizing_method": mm_config.sizing_method,
                "risk_fraction": mm_config.risk_fraction,
                "stop_type": mm_config.stop_type,
                "heat_limit": heat_limit,
                "initial_capital": mm_config.initial_capital,
            },
        }

        elapsed = round(_time.perf_counter() - t0, 1)
        yield _sse_event("progress", {"stage": "done", "message": f"Done in {elapsed}s", "pct": 100})
        yield _sse_event("result", payload)

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


def _run_sync(tickers, skipped, start, end, heat_limit, mm_config):
    """Non-streaming fallback for programmatic callers."""
    ticker_data: dict = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_ticker_data, t, start, end): t for t in tickers}
        for fut in as_completed(futures):
            t, df = fut.result()
            if df is not None and not df.empty:
                ticker_data[t] = df

    if not ticker_data:
        return jsonify({"error": "No data available"}), 400

    ticker_directions = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_compute_signal, t, ticker_data[t]): t for t in ticker_data}
        for fut in as_completed(futures):
            t, direction = fut.result()
            if direction is not None:
                ticker_directions[t] = direction

    if not ticker_directions:
        return jsonify({"error": "Could not compute signals"}), 400

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
        return jsonify({"error": "No data in the selected date range"}), 400

    result = backtest_portfolio(visible_data, visible_directions, config=mm_config, heat_limit=heat_limit)

    per_ticker_json = {}
    for t, data in result.per_ticker.items():
        per_ticker_json[t] = {
            "trades": data["trades"],
            "summary": data["summary"],
            "equity_contribution": data["equity_contribution"],
        }

    return jsonify({
        "tickers": result.tickers,
        "skipped": skipped,
        "portfolio_equity_curve": result.portfolio_equity_curve,
        "portfolio_buy_hold_curve": result.portfolio_buy_hold_curve,
        "portfolio_summary": result.portfolio_summary,
        "per_ticker": per_ticker_json,
        "heat_series": result.heat_series,
        "config": {
            "sizing_method": mm_config.sizing_method,
            "risk_fraction": mm_config.risk_fraction,
            "stop_type": mm_config.stop_type,
            "heat_limit": heat_limit,
            "initial_capital": mm_config.initial_capital,
        },
    })
