from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from lib.settings import (
    INITIAL_CAPITAL,
    RIBBON_DAILY_ADD_CAPITAL,
    RIBBON_DAILY_SELL_FRACTION,
    RIBBON_MAX_CAPITAL,
    RIBBON_WEEKLY_ADD_CAPITAL,
    RIBBON_WEEKLY_SELL_FRACTION,
)


@dataclass(frozen=True)
class MoneyManagementConfig:
    """Configurable money management for the backtesting engine.

    Default values reproduce backtest_direction() behavior:
    all-in/all-out with INITIAL_CAPITAL, no stops, no vol sizing.
    """

    initial_capital: float = INITIAL_CAPITAL

    # Sizing: None=all-in, "vol", "fixed_fraction"
    sizing_method: Optional[str] = None
    vol_scale_factor: float = 0.001
    vol_lookback: int = 100
    point_value: float = 1.0
    risk_fraction: float = 0.01

    # Stops: None=no stop, "atr", "pct"
    stop_type: Optional[str] = None
    stop_atr_period: int = 20
    stop_atr_multiple: float = 3.0
    stop_pct: float = 0.02

    # Basso three-layer risk caps (None=disabled)
    risk_to_stop_limit: Optional[float] = None
    vol_to_equity_limit: Optional[float] = None
    vol_to_equity_atr_period: int = 20
    margin_to_equity_limit: Optional[float] = None
    margin_per_unit: float = 0.0

    # Compounding: "trade"=current equity, "monthly"=month-start, "fixed"=initial only
    compounding: str = "trade"


def _compute_atr(highs, lows, closes, end_idx, period):
    """Compute ATR ending at end_idx using Wilder's method."""
    start = max(0, end_idx - period * 2)
    if end_idx - start < period:
        return None
    tr_vals = []
    for j in range(start + 1, end_idx + 1):
        hi = float(highs.iloc[j])
        lo = float(lows.iloc[j])
        prev_c = float(closes.iloc[j - 1])
        tr_vals.append(max(hi - lo, abs(hi - prev_c), abs(lo - prev_c)))
    if len(tr_vals) < period:
        return None
    atr = sum(tr_vals[:period]) / period
    for v in tr_vals[period:]:
        atr = (atr * (period - 1) + v) / period
    return atr


def _compute_stop_distance(df, bar_idx, config):
    """Compute the stop distance in price units for position sizing."""
    if config.stop_type == "atr":
        atr = _compute_atr(
            df["High"], df["Low"], df["Close"], bar_idx, config.stop_atr_period
        )
        if atr is not None:
            return atr * config.stop_atr_multiple
        return None
    elif config.stop_type == "pct":
        return float(df["Close"].iloc[bar_idx]) * config.stop_pct
    return None


def _compute_position_size(config, sizing_equity, price, df, bar_idx, stop_dist):
    """Compute base position size in shares before risk caps."""
    if config.sizing_method is None:
        return None  # signals all-in

    if config.sizing_method == "vol":
        start = max(0, bar_idx - config.vol_lookback)
        if bar_idx - start < 2:
            return 0.0
        changes = df["Close"].iloc[start : bar_idx + 1].diff().dropna()
        stddev = float(changes.std()) if len(changes) > 1 else 0.0
        if stddev <= 0:
            return 0.0
        return config.vol_scale_factor * sizing_equity / (stddev * config.point_value)

    if config.sizing_method == "fixed_fraction":
        risk_per_share = stop_dist
        if risk_per_share is None or risk_per_share <= 0:
            atr = _compute_atr(
                df["High"], df["Low"], df["Close"], bar_idx, 20
            )
            risk_per_share = atr if atr and atr > 0 else price * 0.02
        return (sizing_equity * config.risk_fraction) / risk_per_share

    return None


def _apply_risk_caps(config, quantity, price, equity, df, bar_idx):
    """Apply Basso three-layer risk caps, returning the minimum qualifying quantity."""
    candidates = [quantity]

    if config.risk_to_stop_limit is not None:
        stop_dist = _compute_stop_distance(df, bar_idx, config)
        if stop_dist and stop_dist > 0:
            max_qty = (equity * config.risk_to_stop_limit) / stop_dist
            candidates.append(max_qty)

    if config.vol_to_equity_limit is not None:
        atr = _compute_atr(
            df["High"],
            df["Low"],
            df["Close"],
            bar_idx,
            config.vol_to_equity_atr_period,
        )
        if atr and atr > 0:
            max_qty = (equity * config.vol_to_equity_limit) / atr
            candidates.append(max_qty)

    if config.margin_to_equity_limit is not None and config.margin_per_unit > 0:
        max_qty = (equity * config.margin_to_equity_limit) / config.margin_per_unit
        candidates.append(max_qty)

    return max(0.0, min(candidates))


def _is_new_month(current_date, previous_date):
    return (
        current_date.month != previous_date.month
        or current_date.year != previous_date.year
    )


def build_equity_curve(df, trades):
    equity_curve = []
    if df.empty:
        return equity_curve

    entry_map = {t["entry_date"]: t for t in trades}
    exit_map = {t["exit_date"]: t for t in trades if not t.get("open")}

    cash = INITIAL_CAPITAL
    shares = 0.0
    active_trade = None

    for date, row in df.iterrows():
        day = str(date.date())

        if shares == 0 and day in entry_map:
            active_trade = entry_map[day]
            shares = active_trade["quantity"]
            cash = 0.0

        if shares > 0 and day in exit_map and active_trade is exit_map[day]:
            cash = round(shares * exit_map[day]["exit_price"], 2)
            shares = 0.0
            active_trade = None

        equity = cash if shares == 0 else shares * float(row["Close"])
        equity_curve.append({"time": int(date.timestamp()), "value": round(equity, 2)})

    return equity_curve


def build_buy_hold_equity_curve(df, contributions=None):
    equity_curve = []
    if df.empty:
        return equity_curve

    contributions = contributions or {}
    entry_price = round(float(df["Open"].iloc[0]), 2)
    shares = INITIAL_CAPITAL / entry_price if entry_price else 0

    for date, row in df.iterrows():
        day = str(date.date())
        add_cash = float(contributions.get(day, 0))
        open_price = float(row["Open"])
        if add_cash > 0 and open_price > 0:
            shares += add_cash / open_price
        equity = shares * float(row["Close"]) if shares else INITIAL_CAPITAL
        equity_curve.append({"time": int(date.timestamp()), "value": round(equity, 2)})

    return equity_curve


def compute_summary(trades, equity_curve, initial_capital=INITIAL_CAPITAL):
    """Compute enhanced summary stats for a list of trades."""
    empty_summary = {
        "total_trades": 0,
        "open_trades": 0,
        "winners": 0,
        "losers": 0,
        "win_rate": 0,
        "total_pnl": 0,
        "realized_pnl": 0,
        "open_pnl": 0,
        "net_profit_pct": 0,
        "avg_pnl": 0,
        "best_trade": 0,
        "worst_trade": 0,
        "gross_profit": 0,
        "gross_loss": 0,
        "profit_factor": None,
        "max_drawdown": 0,
        "max_drawdown_pct": 0,
        "avg_winner": 0,
        "avg_loser": 0,
        "ending_equity": initial_capital,
        "initial_capital": initial_capital,
    }
    if not trades:
        return empty_summary

    closed_trades = [t for t in trades if not t.get("open")]
    open_trades = [t for t in trades if t.get("open")]
    realized_pnl = sum(t["pnl"] for t in closed_trades)
    open_pnl = sum(t["pnl"] for t in open_trades)
    total_pnl = realized_pnl + open_pnl
    winners = [t for t in closed_trades if t["pnl"] > 0]
    losers = [t for t in closed_trades if t["pnl"] <= 0]
    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss = abs(sum(t["pnl"] for t in losers))

    peak = initial_capital
    max_dd = 0
    max_dd_pct = 0
    ending_equity = initial_capital
    for point in equity_curve:
        equity = point["value"]
        peak = max(peak, equity)
        ending_equity = equity
        drawdown = peak - equity
        drawdown_pct = (drawdown / peak) * 100 if peak else 0
        if drawdown > max_dd:
            max_dd = drawdown
            max_dd_pct = drawdown_pct

    return {
        "total_trades": len(closed_trades),
        "open_trades": len(open_trades),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": round(len(winners) / len(closed_trades) * 100, 1) if closed_trades else 0,
        "total_pnl": round(total_pnl, 2),
        "realized_pnl": round(realized_pnl, 2),
        "open_pnl": round(open_pnl, 2),
        "net_profit_pct": round(((ending_equity / initial_capital) - 1) * 100, 2)
        if initial_capital
        else 0,
        "avg_pnl": round(realized_pnl / len(closed_trades), 2) if closed_trades else 0,
        "best_trade": round(max((t["pnl"] for t in closed_trades), default=0), 2),
        "worst_trade": round(min((t["pnl"] for t in closed_trades), default=0), 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "avg_winner": round(gross_profit / len(winners), 2) if winners else 0,
        "avg_loser": round(gross_loss / len(losers), 2) if losers else 0,
        "ending_equity": round(ending_equity, 2),
        "initial_capital": round(initial_capital, 2),
    }


def backtest_direction(df, direction, start_in_position=False, prior_direction=None):
    """Generic backtest: long when direction=1, flat otherwise, filled next bar open."""
    trades = []
    position = None
    open_prices = df["Open"]
    close = df["Close"]
    dates = df.index
    cash = INITIAL_CAPITAL
    initial_prev_dir = prior_direction
    if initial_prev_dir is None and len(df) > 0:
        initial_prev_dir = 1 if start_in_position else direction.iloc[0]

    if start_in_position and len(df) > 0:
        entry_price = round(float(open_prices.iloc[0]), 2)
        quantity = cash / entry_price if entry_price else 0
        position = {
            "entry_date": str(dates[0].date()),
            "entry_price": entry_price,
            "type": "long",
            "quantity": round(quantity, 8),
        }
        cash = 0.0

    for i in range(0, len(df) - 1):
        prev_dir = initial_prev_dir if i == 0 else direction.iloc[i - 1]
        curr_dir = direction.iloc[i]
        execution_idx = i + 1
        execution_price = round(float(open_prices.iloc[execution_idx]), 2)
        execution_date = str(dates[execution_idx].date())

        if prev_dir != 1 and curr_dir == 1 and position is None:
            quantity = cash / execution_price if execution_price else 0
            position = {
                "entry_date": execution_date,
                "entry_price": execution_price,
                "type": "long",
                "quantity": round(quantity, 8),
            }
            cash = 0.0
        elif prev_dir == 1 and curr_dir != 1 and position is not None:
            pnl = (execution_price - position["entry_price"]) * position["quantity"]
            pnl_pct = (
                ((execution_price / position["entry_price"]) - 1) * 100
                if position["entry_price"]
                else 0
            )
            cash = execution_price * position["quantity"]
            trades.append(
                {
                    **position,
                    "exit_date": execution_date,
                    "exit_price": execution_price,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                }
            )
            position = None

    if position is not None:
        last_close = round(float(close.iloc[-1]), 2)
        pnl = (last_close - position["entry_price"]) * position["quantity"]
        pnl_pct = (
            ((last_close / position["entry_price"]) - 1) * 100
            if position["entry_price"]
            else 0
        )
        trades.append(
            {
                **position,
                "exit_date": str(dates[-1].date()),
                "exit_price": last_close,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "open": True,
            }
        )

    equity_curve = build_equity_curve(df, trades)
    summary = compute_summary(trades, equity_curve)
    return trades, summary, equity_curve


def backtest_supertrend(df, direction, start_in_position=False):
    """Backtest a Supertrend strategy: long when bullish, flat when bearish."""
    return backtest_direction(df, direction, start_in_position=start_in_position)




def backtest_managed(
    df,
    direction,
    config=None,
    start_in_position=False,
    prior_direction=None,
):
    """Backtest with configurable money management layers.

    When config is None or default, reproduces backtest_direction() behavior.
    Returns (trades, summary, equity_curve) matching the existing format.
    """
    if config is None:
        config = MoneyManagementConfig()

    # All-in mode: delegate to backtest_direction for exact equivalence
    has_mm = (
        config.sizing_method is not None
        or config.stop_type is not None
        or config.risk_to_stop_limit is not None
        or config.vol_to_equity_limit is not None
        or config.margin_to_equity_limit is not None
    )
    if not has_mm and config.compounding == "trade":
        return backtest_direction(
            df,
            direction,
            start_in_position=start_in_position,
            prior_direction=prior_direction,
        )

    trades = []
    open_lots = []
    equity_curve = []
    cash = float(config.initial_capital)
    sizing_equity = float(config.initial_capital)
    open_prices = df["Open"]
    close_prices = df["Close"]
    dates = df.index
    completed_trades = []

    initial_prev_dir = prior_direction
    if initial_prev_dir is None and len(df) > 0:
        initial_prev_dir = 1 if start_in_position else direction.iloc[0]

    if start_in_position and len(df) > 0:
        entry_price = round(float(open_prices.iloc[0]), 2)
        if entry_price > 0:
            quantity = _compute_position_size(
                config, sizing_equity, entry_price, df, 0, None
            )
            if quantity is None:
                quantity = cash / entry_price
            quantity = _apply_risk_caps(config, quantity, entry_price, cash, df, 0)
            quantity = min(quantity, cash / entry_price) if entry_price > 0 else 0
            if quantity > 0:
                cost = quantity * entry_price
                open_lots.append(
                    {
                        "entry_date": str(dates[0].date()),
                        "entry_price": entry_price,
                        "quantity": round(quantity, 8),
                        "type": "long",
                        "stop_price": None,
                    }
                )
                cash -= cost
                if config.stop_type == "atr":
                    sd = _compute_stop_distance(df, 0, config)
                    if sd:
                        open_lots[-1]["stop_price"] = entry_price - sd
                elif config.stop_type == "pct":
                    open_lots[-1]["stop_price"] = entry_price * (1 - config.stop_pct)

    for i in range(len(df)):
        close_price = float(close_prices.iloc[i])
        market_value = sum(lot["quantity"] * close_price for lot in open_lots)
        equity = cash + market_value

        # Monthly compounding reset
        if config.compounding == "monthly" and i > 0:
            if _is_new_month(dates[i], dates[i - 1]):
                sizing_equity = equity
        elif config.compounding == "trade":
            sizing_equity = equity
        # "fixed" keeps sizing_equity = initial_capital

        # Stop loss checks
        if open_lots and config.stop_type is not None:
            low_price = float(df["Low"].iloc[i])
            new_open = []
            for lot in open_lots:
                if lot["stop_price"] is not None and low_price <= lot["stop_price"]:
                    exit_price = round(lot["stop_price"], 2)
                    pnl = (exit_price - lot["entry_price"]) * lot["quantity"]
                    pnl_pct = (
                        ((exit_price / lot["entry_price"]) - 1) * 100
                        if lot["entry_price"]
                        else 0
                    )
                    trade = {
                        "entry_date": lot["entry_date"],
                        "entry_price": lot["entry_price"],
                        "exit_date": str(dates[i].date()),
                        "exit_price": exit_price,
                        "type": "long",
                        "quantity": round(lot["quantity"], 8),
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 2),
                    }
                    trades.append(trade)
                    completed_trades.append(trade)
                    cash += lot["quantity"] * exit_price
                else:
                    new_open.append(lot)
            open_lots[:] = new_open

            # Update trailing stops (ratchet up only)
            if open_lots:
                if config.stop_type == "atr":
                    atr = _compute_atr(
                        df["High"],
                        df["Low"],
                        df["Close"],
                        i,
                        config.stop_atr_period,
                    )
                    if atr is not None:
                        new_stop = close_price - config.stop_atr_multiple * atr
                        for lot in open_lots:
                            if lot["stop_price"] is None or new_stop > lot["stop_price"]:
                                lot["stop_price"] = new_stop
                elif config.stop_type == "pct":
                    new_stop = close_price * (1 - config.stop_pct)
                    for lot in open_lots:
                        if lot["stop_price"] is None or new_stop > lot["stop_price"]:
                            lot["stop_price"] = new_stop

        # Signal processing (1-bar delay)
        if i < len(df) - 1:
            prev_dir = initial_prev_dir if i == 0 else direction.iloc[i - 1]
            curr_dir = direction.iloc[i]
            execution_idx = i + 1
            execution_price = round(float(open_prices.iloc[execution_idx]), 2)
            execution_date = str(dates[execution_idx].date())

            # Exit signal
            if prev_dir == 1 and curr_dir != 1 and open_lots:
                for lot in open_lots:
                    pnl = (execution_price - lot["entry_price"]) * lot["quantity"]
                    pnl_pct = (
                        ((execution_price / lot["entry_price"]) - 1) * 100
                        if lot["entry_price"]
                        else 0
                    )
                    trade = {
                        "entry_date": lot["entry_date"],
                        "entry_price": lot["entry_price"],
                        "exit_date": execution_date,
                        "exit_price": execution_price,
                        "type": "long",
                        "quantity": round(lot["quantity"], 8),
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 2),
                    }
                    trades.append(trade)
                    completed_trades.append(trade)
                    cash += lot["quantity"] * execution_price
                open_lots.clear()

            # Entry signal
            elif prev_dir != 1 and curr_dir == 1 and not open_lots:
                if execution_price > 0:
                    stop_dist = _compute_stop_distance(df, i, config)
                    quantity = _compute_position_size(
                        config, sizing_equity, execution_price, df, i, stop_dist
                    )
                    if quantity is None:
                        quantity = cash / execution_price
                    quantity = _apply_risk_caps(
                        config, quantity, execution_price, equity, df, i
                    )
                    quantity = min(quantity, cash / execution_price)
                    if quantity > 0:
                        cost = quantity * execution_price
                        lot = {
                            "entry_date": execution_date,
                            "entry_price": execution_price,
                            "quantity": round(quantity, 8),
                            "type": "long",
                            "stop_price": None,
                        }
                        if config.stop_type == "atr" and stop_dist:
                            lot["stop_price"] = execution_price - stop_dist
                        elif config.stop_type == "pct":
                            lot["stop_price"] = execution_price * (1 - config.stop_pct)
                        open_lots.append(lot)
                        cash -= cost

        # Record equity
        market_value = sum(lot["quantity"] * close_price for lot in open_lots)
        equity = cash + market_value
        equity_curve.append(
            {"time": int(dates[i].timestamp()), "value": round(equity, 2)}
        )

    # Mark open positions to market
    if open_lots:
        last_close = round(float(close_prices.iloc[-1]), 2)
        last_date = str(dates[-1].date())
        for lot in open_lots:
            pnl = (last_close - lot["entry_price"]) * lot["quantity"]
            pnl_pct = (
                ((last_close / lot["entry_price"]) - 1) * 100
                if lot["entry_price"]
                else 0
            )
            trades.append(
                {
                    "entry_date": lot["entry_date"],
                    "entry_price": lot["entry_price"],
                    "exit_date": last_date,
                    "exit_price": last_close,
                    "type": "long",
                    "quantity": round(lot["quantity"], 8),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "open": True,
                }
            )

    summary = compute_summary(trades, equity_curve, initial_capital=config.initial_capital)
    return trades, summary, equity_curve


def _direction_at(series, idx, fallback):
    value = series.iloc[idx]
    if pd.isna(value):
        return fallback
    return int(value)


def _position_quantity(open_lots, sleeve=None):
    return sum(
        lot["quantity"]
        for lot in open_lots
        if sleeve is None or lot.get("sleeve") == sleeve
    )


def _buy_lot(open_lots, date, price, amount, sleeve="tactical"):
    if amount <= 0 or price <= 0:
        return
    open_lots.append(
        {
            "entry_date": str(date.date()),
            "entry_price": round(float(price), 2),
            "quantity": amount / float(price),
            "sleeve": sleeve,
            "type": "long",
        }
    )


def _buy_budget(open_lots, price, cash, total_contributed, add_amount, max_capital):
    position_value = _position_quantity(open_lots) * float(price)
    capacity_by_position = max(0.0, max_capital - position_value)
    capacity_by_funding = cash + max(0.0, max_capital - total_contributed)
    return min(add_amount, capacity_by_position, capacity_by_funding)


def _sell_fraction(open_lots, trades, date, price, fraction, sleeve=None):
    if fraction <= 0 or price <= 0:
        return 0.0

    target_qty = _position_quantity(open_lots, sleeve=sleeve) * fraction
    if target_qty <= 0:
        return 0.0

    remaining_qty = target_qty
    new_open_lots = []
    proceeds = 0.0
    exit_price = round(float(price), 2)
    exit_date = str(date.date())

    for lot in open_lots:
        if sleeve is not None and lot.get("sleeve") != sleeve:
            new_open_lots.append(lot)
            continue

        if remaining_qty <= 1e-12:
            new_open_lots.append(lot)
            continue

        sold_qty = min(lot["quantity"], remaining_qty)
        remaining_qty -= sold_qty
        proceeds += sold_qty * float(price)

        pnl = (float(price) - lot["entry_price"]) * sold_qty
        pnl_pct = (
            ((float(price) / lot["entry_price"]) - 1) * 100
            if lot["entry_price"]
            else 0
        )
        trades.append(
            {
                "entry_date": lot["entry_date"],
                "entry_price": lot["entry_price"],
                "exit_date": exit_date,
                "exit_price": exit_price,
                "sleeve": lot.get("sleeve"),
                "type": "long",
                "quantity": round(sold_qty, 8),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
            }
        )

        remaining_lot_qty = lot["quantity"] - sold_qty
        if remaining_lot_qty > 1e-12:
            new_open_lots.append({**lot, "quantity": remaining_lot_qty})

    open_lots[:] = new_open_lots
    return proceeds


def _mark_open_lots_to_market(open_lots, close_date, close_price):
    open_trades = []
    exit_price = round(float(close_price), 2)
    exit_date = str(close_date.date())
    for lot in open_lots:
        pnl = (float(close_price) - lot["entry_price"]) * lot["quantity"]
        pnl_pct = (
            ((float(close_price) / lot["entry_price"]) - 1) * 100
            if lot["entry_price"]
            else 0
        )
        open_trades.append(
            {
                "entry_date": lot["entry_date"],
                "entry_price": lot["entry_price"],
                "exit_date": exit_date,
                "exit_price": exit_price,
                "sleeve": lot.get("sleeve"),
                "type": "long",
                "quantity": round(lot["quantity"], 8),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "open": True,
            }
        )
    return open_trades


def build_weekly_confirmed_ribbon_direction(
    daily_direction: pd.Series,
    weekly_direction: pd.Series,
    initial_direction: int = 0,
    reentry_cooldown_bars: int = 0,
    reentry_cooldown_ratio: float = 0.0,
    weekly_nonbull_confirm_bars: int = 1,
) -> pd.Series:
    """Build a cycle-level ribbon regime from daily flips and weekly confirmation.

    Bull entries require daily bull + weekly carried bull. Bear exits trigger on a
    daily bear flip once the raw weekly ribbon has been non-bull for enough bars.
    After each exit, re-entry can be locked out for either a fixed number of bars
    or a fraction of the just-completed bull regime's duration.
    """
    if daily_direction.empty:
        return pd.Series(dtype=int, index=daily_direction.index)

    daily_state = (
        daily_direction.replace(0, pd.NA)
        .ffill()
        .fillna(0)
        .astype(int)
    )
    weekly_raw_state = (
        weekly_direction.reindex(daily_direction.index)
        .ffill()
        .bfill()
        .fillna(0)
        .astype(int)
    )
    weekly_state = (
        weekly_raw_state.replace(0, pd.NA)
        .ffill()
        .fillna(0)
        .astype(int)
    )

    confirmed = []
    state = int(initial_direction) if not pd.isna(initial_direction) else 0
    cooldown_remaining = 0
    bull_duration_bars = 0
    weekly_nonbull_streak = 0
    cooldown_ratio = max(0.0, float(reentry_cooldown_ratio))
    cooldown_floor = max(0, int(reentry_cooldown_bars))
    nonbull_confirm_bars = max(1, int(weekly_nonbull_confirm_bars))

    for daily_value, weekly_value, weekly_raw_value in zip(
        daily_state,
        weekly_state,
        weekly_raw_state,
    ):
        weekly_nonbull_streak = (
            weekly_nonbull_streak + 1 if weekly_raw_value != 1 else 0
        )

        if (
            state == 1
            and daily_value == -1
            and weekly_nonbull_streak >= nonbull_confirm_bars
        ):
            state = -1
            ratio_cooldown = int(round(bull_duration_bars * cooldown_ratio))
            cooldown_remaining = max(cooldown_floor, ratio_cooldown)
            bull_duration_bars = 0
        elif state != 1 and cooldown_remaining <= 0 and daily_value == 1 and weekly_value == 1:
            state = 1
            bull_duration_bars = 1
        elif cooldown_remaining > 0:
            cooldown_remaining -= 1
        elif state == 1:
            bull_duration_bars += 1
        confirmed.append(state)

    return pd.Series(confirmed, index=daily_direction.index, dtype=int)


def backtest_ribbon_regime(
    df,
    daily_direction,
    weekly_direction,
    prior_direction=None,
    reentry_cooldown_bars=0,
    reentry_cooldown_ratio=0.0,
    weekly_nonbull_confirm_bars=1,
):
    """Backtest a weekly-confirmed bull/bear ribbon regime: long in bull, cash in bear."""
    confirmed_direction = build_weekly_confirmed_ribbon_direction(
        daily_direction,
        weekly_direction,
        initial_direction=prior_direction or 0,
        reentry_cooldown_bars=reentry_cooldown_bars,
        reentry_cooldown_ratio=reentry_cooldown_ratio,
        weekly_nonbull_confirm_bars=weekly_nonbull_confirm_bars,
    )
    return backtest_direction(
        df,
        confirmed_direction,
        start_in_position=prior_direction == 1,
        prior_direction=prior_direction,
    )


def backtest_ribbon_accumulation(
    df,
    daily_direction,
    weekly_direction,
    prior_daily_direction=None,
    prior_weekly_direction=None,
    initial_capital=INITIAL_CAPITAL,
    daily_add_capital=RIBBON_DAILY_ADD_CAPITAL,
    weekly_add_capital=RIBBON_WEEKLY_ADD_CAPITAL,
    max_capital=RIBBON_MAX_CAPITAL,
    daily_sell_fraction=RIBBON_DAILY_SELL_FRACTION,
    weekly_sell_fraction=RIBBON_WEEKLY_SELL_FRACTION,
):
    """Backtest a core-long ribbon strategy with daily/weekly scale-ins and scale-outs."""
    if df.empty:
        summary = compute_summary([], [], initial_capital=initial_capital)
        return [], summary, [], build_buy_hold_equity_curve(df)

    daily_direction = daily_direction.reindex(df.index)
    weekly_direction = weekly_direction.reindex(df.index).ffill().bfill()

    trades = []
    open_lots = []
    equity_curve = []
    contributions = {}
    total_contributed = float(initial_capital)
    cash = float(initial_capital)
    dates = df.index
    open_prices = df["Open"]
    close_prices = df["Close"]

    _buy_lot(open_lots, dates[0], open_prices.iloc[0], initial_capital, sleeve="core")
    cash -= initial_capital

    prev_daily = (
        int(prior_daily_direction)
        if prior_daily_direction is not None and not pd.isna(prior_daily_direction)
        else _direction_at(daily_direction, 0, 0)
    )
    prev_weekly = (
        int(prior_weekly_direction)
        if prior_weekly_direction is not None and not pd.isna(prior_weekly_direction)
        else _direction_at(weekly_direction, 0, 0)
    )

    for i in range(len(df)):
        if i > 0:
            signal_idx = i - 1
            curr_daily = _direction_at(daily_direction, signal_idx, prev_daily)
            curr_weekly = _direction_at(weekly_direction, signal_idx, prev_weekly)
            execution_date = dates[i]
            execution_price = float(open_prices.iloc[i])

            if prev_daily != 1 and curr_daily == 1:
                buy_amount = _buy_budget(
                    open_lots,
                    execution_price,
                    cash,
                    total_contributed,
                    daily_add_capital,
                    max_capital,
                )
                external_add = max(0.0, buy_amount - cash)
                if external_add > 0:
                    total_contributed += external_add
                    cash += external_add
                    day = str(execution_date.date())
                    contributions[day] = contributions.get(day, 0.0) + external_add
                if buy_amount > 0:
                    cash -= buy_amount
                    _buy_lot(open_lots, execution_date, execution_price, buy_amount)

            if prev_weekly != 1 and curr_weekly == 1 and curr_daily == 1:
                buy_amount = _buy_budget(
                    open_lots,
                    execution_price,
                    cash,
                    total_contributed,
                    weekly_add_capital,
                    max_capital,
                )
                external_add = max(0.0, buy_amount - cash)
                if external_add > 0:
                    total_contributed += external_add
                    cash += external_add
                    day = str(execution_date.date())
                    contributions[day] = contributions.get(day, 0.0) + external_add
                if buy_amount > 0:
                    cash -= buy_amount
                    _buy_lot(open_lots, execution_date, execution_price, buy_amount)

            if prev_daily != -1 and curr_daily == -1:
                cash += _sell_fraction(
                    open_lots,
                    trades,
                    execution_date,
                    execution_price,
                    daily_sell_fraction,
                    sleeve="tactical",
                )

            if prev_weekly != -1 and curr_weekly == -1 and curr_daily == -1:
                cash += _sell_fraction(
                    open_lots,
                    trades,
                    execution_date,
                    execution_price,
                    weekly_sell_fraction,
                    sleeve="tactical",
                )

            prev_daily = curr_daily
            prev_weekly = curr_weekly

        market_value = _position_quantity(open_lots) * float(close_prices.iloc[i])
        equity_curve.append(
            {
                "time": int(dates[i].timestamp()),
                "value": round(cash + market_value, 2),
            }
        )

    if open_lots:
        trades.extend(
            _mark_open_lots_to_market(open_lots, dates[-1], close_prices.iloc[-1])
        )

    summary = compute_summary(
        trades,
        equity_curve,
        initial_capital=total_contributed,
    )
    buy_hold_equity_curve = build_buy_hold_equity_curve(df, contributions=contributions)
    return trades, summary, equity_curve, buy_hold_equity_curve
