"""Portfolio-level backtesting engine.

Runs a bar-synchronized simulation across multiple tickers with shared capital,
fixed-fraction position sizing, ATR trailing stops, and a portfolio heat governor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from lib.backtesting import (
    MoneyManagementConfig,
    _compute_atr,
    _compute_position_size,
    _compute_stop_distance,
    _apply_risk_caps,
    compute_summary,
)
from lib.settings import INITIAL_CAPITAL


@dataclass
class PortfolioResult:
    portfolio_equity_curve: list[dict]
    portfolio_buy_hold_curve: list[dict]
    portfolio_summary: dict
    per_ticker: dict[str, dict]
    heat_series: list[dict]
    tickers: list[str]


@dataclass
class _OpenPosition:
    ticker: str
    entry_date: str
    entry_price: float
    quantity: float
    stop_price: Optional[float]
    risk_per_share: float


def _build_union_index(
    ticker_data: dict[str, pd.DataFrame],
) -> pd.DatetimeIndex:
    all_indices = [df.index for df in ticker_data.values() if not df.empty]
    if not all_indices:
        return pd.DatetimeIndex([])
    union = all_indices[0]
    for idx in all_indices[1:]:
        union = union.union(idx)
    return union.sort_values()


def _atr_at_bar(df: pd.DataFrame, bar_idx: int, period: int = 20) -> Optional[float]:
    return _compute_atr(df["High"], df["Low"], df["Close"], bar_idx, period)


def _compute_per_ticker_summary(trades: list[dict]) -> dict:
    """Compute summary stats from trades only (no equity curve dependency)."""
    if not trades:
        return {
            "total_trades": 0, "open_trades": 0, "winners": 0, "losers": 0,
            "win_rate": 0, "total_pnl": 0, "net_profit_pct": 0,
            "avg_pnl": 0, "best_trade": 0, "worst_trade": 0,
            "gross_profit": 0, "gross_loss": 0, "profit_factor": None,
            "max_drawdown_pct": 0,
        }

    closed = [t for t in trades if not t.get("open")]
    open_trades = [t for t in trades if t.get("open")]
    winners = [t for t in closed if t["pnl"] > 0]
    losers = [t for t in closed if t["pnl"] <= 0]
    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss = abs(sum(t["pnl"] for t in losers))
    total_pnl = sum(t["pnl"] for t in trades)

    # Trade-by-trade drawdown (cumulative PnL curve)
    cum_pnl = 0.0
    peak_pnl = 0.0
    max_dd_pnl = 0.0
    for t in closed:
        cum_pnl += t["pnl"]
        peak_pnl = max(peak_pnl, cum_pnl)
        dd = peak_pnl - cum_pnl
        max_dd_pnl = max(max_dd_pnl, dd)

    return {
        "total_trades": len(closed),
        "open_trades": len(open_trades),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": round(len(winners) / len(closed) * 100, 1) if closed else 0,
        "total_pnl": round(total_pnl, 2),
        "realized_pnl": round(sum(t["pnl"] for t in closed), 2),
        "open_pnl": round(sum(t["pnl"] for t in open_trades), 2),
        "net_profit_pct": round(total_pnl / INITIAL_CAPITAL * 100, 2) if INITIAL_CAPITAL else 0,
        "avg_pnl": round(sum(t["pnl"] for t in closed) / len(closed), 2) if closed else 0,
        "best_trade": round(max((t["pnl"] for t in closed), default=0), 2),
        "worst_trade": round(min((t["pnl"] for t in closed), default=0), 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
        "max_drawdown_pct": round(max_dd_pnl / INITIAL_CAPITAL * 100, 2) if INITIAL_CAPITAL else 0,
    }


def backtest_portfolio(
    ticker_data: dict[str, pd.DataFrame],
    ticker_directions: dict[str, pd.Series],
    config: Optional[MoneyManagementConfig] = None,
    heat_limit: float = 0.20,
) -> PortfolioResult:
    """Run a portfolio backtest across multiple tickers with shared capital."""
    if config is None:
        config = MoneyManagementConfig(
            sizing_method="fixed_fraction",
            risk_fraction=0.08,
            stop_type="atr",
            stop_atr_period=20,
            stop_atr_multiple=3.0,
        )

    tickers = sorted(ticker_data.keys())
    union_index = _build_union_index(ticker_data)
    if union_index.empty:
        empty_summary = compute_summary([], [], initial_capital=config.initial_capital)
        return PortfolioResult(
            portfolio_equity_curve=[],
            portfolio_buy_hold_curve=[],
            portfolio_summary=empty_summary,
            per_ticker={},
            heat_series=[],
            tickers=tickers,
        )

    ticker_bar_idx: dict[str, dict[pd.Timestamp, int]] = {}
    for t in tickers:
        df = ticker_data[t]
        ticker_bar_idx[t] = {ts: i for i, ts in enumerate(df.index)}

    # Last known close price per ticker -- for mark-to-market on non-trading days
    last_close: dict[str, float] = {}

    cash = float(config.initial_capital)
    positions: dict[str, _OpenPosition] = {}
    per_ticker_trades: dict[str, list] = {t: [] for t in tickers}
    per_ticker_equity: dict[str, list] = {t: [] for t in tickers}

    portfolio_equity_curve: list[dict] = []
    heat_series: list[dict] = []

    prev_dirs: dict[str, int] = {t: 0 for t in tickers}

    # Buy-hold: equal-weight, initialize lazily per ticker
    bh_shares: dict[str, float] = {}
    bh_last_close: dict[str, float] = {}
    bh_capital_per_ticker = config.initial_capital / max(len(tickers), 1)

    for date in union_index:
        ts = int(date.timestamp())

        # Update last known close for every ticker that has data today
        for t in tickers:
            if date in ticker_bar_idx.get(t, {}):
                idx = ticker_bar_idx[t][date]
                last_close[t] = float(ticker_data[t]["Close"].iloc[idx])

        # --- Buy-hold initialization ---
        for t in tickers:
            if t not in bh_shares and date in ticker_bar_idx.get(t, {}):
                idx = ticker_bar_idx[t][date]
                open_price = float(ticker_data[t]["Open"].iloc[idx])
                if open_price > 0:
                    bh_shares[t] = bh_capital_per_ticker / open_price
                    bh_last_close[t] = float(ticker_data[t]["Close"].iloc[idx])

        # ---- 1. Process stop-loss exits ----
        for t in list(positions.keys()):
            if date not in ticker_bar_idx.get(t, {}):
                continue
            pos = positions[t]
            df = ticker_data[t]
            idx = ticker_bar_idx[t][date]
            low = float(df["Low"].iloc[idx])

            if pos.stop_price is not None and low <= pos.stop_price:
                exit_price = round(pos.stop_price, 2)
                pnl = (exit_price - pos.entry_price) * pos.quantity
                pnl_pct = ((exit_price / pos.entry_price) - 1) * 100 if pos.entry_price else 0
                per_ticker_trades[t].append({
                    "entry_date": pos.entry_date, "entry_price": pos.entry_price,
                    "exit_date": str(date.date()), "exit_price": exit_price,
                    "type": "long", "quantity": round(pos.quantity, 8),
                    "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2), "ticker": t,
                })
                cash += pos.quantity * exit_price
                del positions[t]

        # ---- 2. Update trailing stops ----
        for t, pos in positions.items():
            if date not in ticker_bar_idx.get(t, {}):
                continue
            df = ticker_data[t]
            idx = ticker_bar_idx[t][date]
            cp = float(df["Close"].iloc[idx])

            if config.stop_type == "atr":
                atr = _atr_at_bar(df, idx, config.stop_atr_period)
                if atr is not None:
                    new_stop = cp - config.stop_atr_multiple * atr
                    if pos.stop_price is None or new_stop > pos.stop_price:
                        pos.stop_price = new_stop
            elif config.stop_type == "pct":
                new_stop = cp * (1 - config.stop_pct)
                if pos.stop_price is None or new_stop > pos.stop_price:
                    pos.stop_price = new_stop

        # ---- 3. Process signal-based exits ----
        for t in list(positions.keys()):
            if date not in ticker_bar_idx.get(t, {}):
                continue
            df = ticker_data[t]
            idx = ticker_bar_idx[t][date]
            direction = ticker_directions[t]
            if idx >= len(direction):
                continue

            curr_dir = int(direction.iloc[idx]) if not pd.isna(direction.iloc[idx]) else 0

            if prev_dirs[t] == 1 and curr_dir != 1:
                pos = positions[t]
                next_idx = idx + 1
                if next_idx < len(df):
                    exit_price = round(float(df["Open"].iloc[next_idx]), 2)
                    exit_date = str(df.index[next_idx].date())
                else:
                    exit_price = round(float(df["Close"].iloc[idx]), 2)
                    exit_date = str(date.date())

                pnl = (exit_price - pos.entry_price) * pos.quantity
                pnl_pct = ((exit_price / pos.entry_price) - 1) * 100 if pos.entry_price else 0
                per_ticker_trades[t].append({
                    "entry_date": pos.entry_date, "entry_price": pos.entry_price,
                    "exit_date": exit_date, "exit_price": exit_price,
                    "type": "long", "quantity": round(pos.quantity, 8),
                    "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2), "ticker": t,
                })
                cash += pos.quantity * exit_price
                del positions[t]

        # ---- 4. Mark-to-market using last known close ----
        market_value = 0.0
        for t, pos in positions.items():
            price = last_close.get(t, pos.entry_price)
            market_value += pos.quantity * price
        equity = cash + market_value

        # ---- 5. Compute portfolio heat (actual risk = close - stop) ----
        current_risk = 0.0
        for t, pos in positions.items():
            price = last_close.get(t, pos.entry_price)
            if pos.stop_price is not None and pos.stop_price > 0:
                risk = max(0.0, (price - pos.stop_price) * pos.quantity)
            else:
                risk = pos.risk_per_share * pos.quantity
            current_risk += risk
        heat_pct = current_risk / equity if equity > 0 else 0.0
        available_risk = max(0.0, heat_limit * equity - current_risk)

        # ---- 6. Process entries ----
        entry_candidates = []
        for t in tickers:
            if t in positions:
                continue
            if date not in ticker_bar_idx.get(t, {}):
                continue
            df = ticker_data[t]
            idx = ticker_bar_idx[t][date]
            direction = ticker_directions[t]
            if idx >= len(direction):
                continue
            curr_dir = int(direction.iloc[idx]) if not pd.isna(direction.iloc[idx]) else 0
            if prev_dirs[t] != 1 and curr_dir == 1:
                entry_candidates.append(t)

        for t in entry_candidates:
            df = ticker_data[t]
            idx = ticker_bar_idx[t][date]
            next_idx = idx + 1
            if next_idx >= len(df):
                continue

            execution_price = round(float(df["Open"].iloc[next_idx]), 2)
            if execution_price <= 0:
                continue

            stop_dist = _compute_stop_distance(df, idx, config)
            risk_per_share = stop_dist if stop_dist and stop_dist > 0 else execution_price * 0.02

            quantity = _compute_position_size(
                config, equity, execution_price, df, idx, stop_dist
            )
            if quantity is None:
                quantity = cash / execution_price if execution_price > 0 else 0.0
            quantity = _apply_risk_caps(config, quantity, execution_price, equity, df, idx)

            trade_risk = risk_per_share * quantity
            if trade_risk > available_risk:
                if available_risk > 0:
                    quantity = available_risk / risk_per_share
                    trade_risk = risk_per_share * quantity
                else:
                    continue

            cost = quantity * execution_price
            if cost > cash:
                quantity = cash / execution_price
                cost = quantity * execution_price
                trade_risk = risk_per_share * quantity

            if quantity <= 0:
                continue

            positions[t] = _OpenPosition(
                ticker=t,
                entry_date=str(df.index[next_idx].date()),
                entry_price=execution_price,
                quantity=round(quantity, 8),
                stop_price=None,
                risk_per_share=risk_per_share,
            )

            if config.stop_type == "atr" and stop_dist:
                positions[t].stop_price = execution_price - stop_dist
            elif config.stop_type == "pct":
                positions[t].stop_price = execution_price * (1 - config.stop_pct)

            cash -= cost
            available_risk -= trade_risk

        # ---- 7. Update prev_dirs ----
        for t in tickers:
            if date in ticker_bar_idx.get(t, {}):
                idx = ticker_bar_idx[t][date]
                direction = ticker_directions[t]
                if idx < len(direction) and not pd.isna(direction.iloc[idx]):
                    prev_dirs[t] = int(direction.iloc[idx])

        # ---- 8. Record equity (use last_close for all positions) ----
        market_value = 0.0
        for t, pos in positions.items():
            price = last_close.get(t, pos.entry_price)
            market_value += pos.quantity * price
        equity = cash + market_value

        current_risk = 0.0
        for t, pos in positions.items():
            price = last_close.get(t, pos.entry_price)
            if pos.stop_price is not None and pos.stop_price > 0:
                risk = max(0.0, (price - pos.stop_price) * pos.quantity)
            else:
                risk = pos.risk_per_share * pos.quantity
            current_risk += risk
        heat_pct = current_risk / equity if equity > 0 else 0.0

        portfolio_equity_curve.append({"time": ts, "value": round(equity, 2)})
        heat_series.append({"time": ts, "value": round(heat_pct * 100, 2)})

        for t in tickers:
            contribution = 0.0
            if t in positions:
                price = last_close.get(t, positions[t].entry_price)
                contribution = positions[t].quantity * price
            per_ticker_equity[t].append({"time": ts, "value": round(contribution, 2)})

        # Update buy-hold last known closes
        for t in tickers:
            if date in ticker_bar_idx.get(t, {}):
                bh_last_close[t] = float(ticker_data[t]["Close"].iloc[ticker_bar_idx[t][date]])

    # ---- Mark remaining open positions ----
    all_trades = []
    for t in tickers:
        if t in positions:
            pos = positions[t]
            lc = last_close.get(t, pos.entry_price)
            last_date_str = str(union_index[-1].date()) if not union_index.empty else pos.entry_date
            pnl = (lc - pos.entry_price) * pos.quantity
            pnl_pct = ((lc / pos.entry_price) - 1) * 100 if pos.entry_price else 0
            per_ticker_trades[t].append({
                "entry_date": pos.entry_date, "entry_price": pos.entry_price,
                "exit_date": last_date_str, "exit_price": round(lc, 2),
                "type": "long", "quantity": round(pos.quantity, 8),
                "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
                "open": True, "ticker": t,
            })
        all_trades.extend(per_ticker_trades[t])

    # ---- Build buy-hold equity curve (carry forward last close) ----
    portfolio_buy_hold_curve: list[dict] = []
    for date in union_index:
        ts_val = int(date.timestamp())
        for t in tickers:
            if date in ticker_bar_idx.get(t, {}):
                bh_last_close[t] = float(ticker_data[t]["Close"].iloc[ticker_bar_idx[t][date]])
        bh_value = sum(bh_shares.get(t, 0) * bh_last_close.get(t, 0) for t in tickers)
        if bh_value > 0:
            portfolio_buy_hold_curve.append({"time": ts_val, "value": round(bh_value, 2)})
        elif portfolio_buy_hold_curve:
            portfolio_buy_hold_curve.append({"time": ts_val, "value": portfolio_buy_hold_curve[-1]["value"]})
        else:
            portfolio_buy_hold_curve.append({"time": ts_val, "value": round(config.initial_capital, 2)})

    # ---- Summaries ----
    per_ticker_result: dict[str, dict] = {}
    for t in tickers:
        per_ticker_result[t] = {
            "trades": per_ticker_trades[t],
            "summary": _compute_per_ticker_summary(per_ticker_trades[t]),
            "equity_contribution": per_ticker_equity[t],
        }

    portfolio_summary = compute_summary(
        all_trades, portfolio_equity_curve, initial_capital=config.initial_capital,
    )

    return PortfolioResult(
        portfolio_equity_curve=portfolio_equity_curve,
        portfolio_buy_hold_curve=portfolio_buy_hold_curve,
        portfolio_summary=portfolio_summary,
        per_ticker=per_ticker_result,
        heat_series=heat_series,
        tickers=tickers,
    )
