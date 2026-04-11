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


LEGACY_VOL_SCALE_FACTOR = 0.001
LEGACY_FIXED_FRACTION_RISK = 0.01
DEFAULT_VOL_LOOKBACK = 100
DEFAULT_POINT_VALUE = 1.0
DEFAULT_VOL_SCALE_FACTOR = 0.005
DEFAULT_FIXED_FRACTION_RISK = 0.02
MANAGED_SIZING_METHODS = frozenset({"vol", "fixed_fraction"})


def managed_sizing_defaults(sizing_method: Optional[str]) -> dict:
    if sizing_method == "vol":
        return {
            "vol_scale_factor": DEFAULT_VOL_SCALE_FACTOR,
            "vol_lookback": DEFAULT_VOL_LOOKBACK,
            "point_value": DEFAULT_POINT_VALUE,
        }
    if sizing_method == "fixed_fraction":
        return {
            "risk_fraction": DEFAULT_FIXED_FRACTION_RISK,
        }
    return {}


def apply_managed_sizing_defaults(kwargs: dict) -> dict:
    sizing_method = kwargs.get("sizing_method")
    if not sizing_method:
        return dict(kwargs)
    return {**managed_sizing_defaults(sizing_method), **kwargs}


@dataclass(frozen=True)
class MoneyManagementConfig:
    """Configurable money management for the backtesting engine.

    Default values reproduce backtest_direction() behavior:
    all-in/all-out with INITIAL_CAPITAL, no stops, no vol sizing.
    """

    initial_capital: float = INITIAL_CAPITAL

    # Sizing: None=all-in, "vol", "fixed_fraction"
    sizing_method: Optional[str] = None
    vol_scale_factor: float = DEFAULT_VOL_SCALE_FACTOR
    vol_lookback: int = DEFAULT_VOL_LOOKBACK
    point_value: float = DEFAULT_POINT_VALUE
    risk_fraction: float = DEFAULT_FIXED_FRACTION_RISK

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


def _resolve_fixed_fraction_risk_per_share(config, price, df, bar_idx, stop_dist):
    risk_per_share = stop_dist
    if risk_per_share is not None and risk_per_share > 0:
        return risk_per_share
    atr = _compute_atr(
        df["High"], df["Low"], df["Close"], bar_idx, config.stop_atr_period
    )
    if atr and atr > 0:
        return atr
    return price * 0.02


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
        risk_per_share = _resolve_fixed_fraction_risk_per_share(
            config, price, df, bar_idx, stop_dist
        )
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


def _infer_periods_per_year_from_equity_curve(equity_curve):
    """Estimate observation frequency from timestamps for Sharpe/Sortino scaling."""
    if len(equity_curve) < 2:
        return None
    times = [p.get("time") for p in equity_curve]
    if any(t is None for t in times):
        return None
    span_sec = float(times[-1]) - float(times[0])
    n_returns = len(equity_curve) - 1
    if span_sec <= 0 or n_returns <= 0:
        return None
    span_years = span_sec / (365.25 * 86400.0)
    if span_years <= 0:
        return None
    periods = n_returns / span_years
    return periods if periods > 0 else None


def _compute_risk_metrics(equity_curve, initial_capital, bars_per_year=None):
    """Derive Sharpe, Sortino, and return/max-drawdown from an equity curve.

    When ``bars_per_year`` is None, infer annualization from equity point timestamps
    (calendar span). If timestamps are missing, fall back to 252 (daily trading).
    """
    if len(equity_curve) < 2:
        return None, None, None

    values = [p["value"] for p in equity_curve]
    returns = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        returns.append((values[i] - prev) / prev if prev else 0.0)

    if not returns:
        return None, None, None

    mean_r = sum(returns) / len(returns)
    var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = var_r ** 0.5

    if bars_per_year is not None and bars_per_year > 0:
        annualize = bars_per_year ** 0.5
    else:
        inferred = _infer_periods_per_year_from_equity_curve(equity_curve)
        annualize = inferred ** 0.5 if inferred is not None else 252 ** 0.5

    sharpe = round(annualize * mean_r / std_r, 2) if std_r > 0 else None

    downside = [r for r in returns if r < 0]
    if downside:
        down_var = sum(r ** 2 for r in downside) / len(returns)
        down_std = down_var ** 0.5
        sortino = round(annualize * mean_r / down_std, 2) if down_std > 0 else None
    else:
        sortino = None

    peak = initial_capital
    max_dd_pct = 0.0
    for v in values:
        peak = max(peak, v)
        dd_pct = (peak - v) / peak * 100 if peak else 0
        max_dd_pct = max(max_dd_pct, dd_pct)

    net_pct = ((values[-1] / initial_capital) - 1) * 100 if initial_capital else 0
    return_over_dd = round(net_pct / max_dd_pct, 2) if max_dd_pct > 0 else None

    return sharpe, sortino, return_over_dd


def compute_summary(
    trades, equity_curve, initial_capital=INITIAL_CAPITAL, bars_per_year=None
):
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
        "sharpe_ratio": None,
        "sortino_ratio": None,
        "return_over_max_dd": None,
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

    sharpe, sortino, return_over_dd = _compute_risk_metrics(
        equity_curve, initial_capital, bars_per_year=bars_per_year
    )

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
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "return_over_max_dd": return_over_dd,
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


def backtest_corpus_trend(
    df,
    direction,
    stop_line,
    start_in_position=False,
    prior_direction=None,
    risk_fraction=0.01,
):
    """Backtest corpus-trend long/cash entries with ATR-guided exits."""
    if df.empty:
        summary = compute_summary([], [], initial_capital=INITIAL_CAPITAL)
        return [], summary, []

    direction = direction.reindex(df.index).ffill().fillna(-1).astype(int)
    stop_line = stop_line.reindex(df.index)
    open_prices = df["Open"]
    close_prices = df["Close"]
    dates = df.index
    trades = []
    equity_curve = []
    cash = float(INITIAL_CAPITAL)
    position = None

    initial_prev_dir = prior_direction
    if initial_prev_dir is None:
        initial_prev_dir = 1 if start_in_position else int(direction.iloc[0])

    if start_in_position:
        entry_price = round(float(open_prices.iloc[0]), 2)
        qty = cash / entry_price if entry_price else 0.0
        position = {
            "entry_date": str(dates[0].date()),
            "entry_price": entry_price,
            "type": "long",
            "quantity": round(qty, 8),
        }
        cash -= qty * entry_price

    for i in range(len(df)):
        close_price = float(close_prices.iloc[i])
        shares = position["quantity"] if position is not None else 0.0
        equity_curve.append(
            {
                "time": int(dates[i].timestamp()),
                "value": round(cash + (shares * close_price), 2),
            }
        )

        if i >= len(df) - 1:
            continue

        prev_dir = initial_prev_dir if i == 0 else int(direction.iloc[i - 1])
        curr_dir = int(direction.iloc[i])
        execution_price = round(float(open_prices.iloc[i + 1]), 2)
        execution_date = str(dates[i + 1].date())

        if prev_dir != 1 and curr_dir == 1 and position is None:
            qty = cash / execution_price if execution_price else 0.0
            qty = round(max(0.0, qty), 8)
            if qty > 0:
                position = {
                    "entry_date": execution_date,
                    "entry_price": execution_price,
                    "type": "long",
                    "quantity": qty,
                }
                cash -= qty * execution_price
        elif prev_dir == 1 and curr_dir != 1 and position is not None:
            pnl = (execution_price - position["entry_price"]) * position["quantity"]
            pnl_pct = (
                ((execution_price / position["entry_price"]) - 1) * 100
                if position["entry_price"]
                else 0
            )
            cash += execution_price * position["quantity"]
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
        last_close = round(float(close_prices.iloc[-1]), 2)
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

    summary = compute_summary(trades, equity_curve)
    return trades, summary, equity_curve


def backtest_corpus_trend_layered(
    df,
    direction,
    stop_line,
    start_in_position=False,
    prior_direction=None,
):
    """Backtest a layered corpus-trend variant with staged entries and trims."""
    if df.empty:
        summary = compute_summary([], [], initial_capital=INITIAL_CAPITAL)
        return [], summary, []

    direction = direction.reindex(df.index).ffill().fillna(-1).astype(int)
    stop_line = stop_line.reindex(df.index)
    open_prices = df["Open"]
    close_prices = df["Close"]
    dates = df.index

    trades = []
    equity_curve = []
    cash = float(INITIAL_CAPITAL)
    open_lots = []
    core_weight = 0.50
    add1_weight = 0.25
    add2_weight = 0.25

    initial_prev_dir = prior_direction
    if initial_prev_dir is None:
        initial_prev_dir = 1 if start_in_position else int(direction.iloc[0])

    breakout_close = None
    add1_reference_close = None
    add1_reentry_anchor = None
    add2_reentry_anchor = None
    pullback_floor_close = None
    highest_close_since_entry = None
    pullback_seen_after_add1 = False

    def _reset_cycle_state():
        nonlocal breakout_close, add1_reference_close, highest_close_since_entry
        nonlocal add1_reentry_anchor, add2_reentry_anchor, pullback_floor_close
        nonlocal pullback_seen_after_add1
        breakout_close = None
        add1_reference_close = None
        add1_reentry_anchor = None
        add2_reentry_anchor = None
        pullback_floor_close = None
        highest_close_since_entry = None
        pullback_seen_after_add1 = False

    def _buy_target_weight(weight, execution_idx, sleeve):
        nonlocal cash, highest_close_since_entry
        execution_price = round(float(open_prices.iloc[execution_idx]), 2)
        if execution_price <= 0:
            return False
        budget = min(cash, INITIAL_CAPITAL * weight)
        if budget <= 0:
            return False
        _buy_lot(open_lots, dates[execution_idx], execution_price, budget, sleeve=sleeve)
        cash -= budget
        highest_close_since_entry = max(
            highest_close_since_entry or float(close_prices.iloc[execution_idx]),
            float(close_prices.iloc[execution_idx]),
        )
        return True

    def _sell_sleeve(sleeve, execution_idx):
        nonlocal cash
        execution_price = round(float(open_prices.iloc[execution_idx]), 2)
        if execution_price <= 0:
            return 0.0
        proceeds = _sell_fraction(
            open_lots,
            trades,
            dates[execution_idx],
            execution_price,
            1.0,
            sleeve=sleeve,
        )
        cash += proceeds
        return proceeds

    def _sell_all(execution_idx):
        nonlocal cash
        execution_price = round(float(open_prices.iloc[execution_idx]), 2)
        if execution_price <= 0:
            return 0.0
        proceeds = _sell_fraction(
            open_lots,
            trades,
            dates[execution_idx],
            execution_price,
            1.0,
        )
        cash += proceeds
        return proceeds

    if start_in_position:
        _buy_target_weight(core_weight, 0, "core")
        _buy_target_weight(add1_weight, 0, "add_1")
        _buy_target_weight(add2_weight, 0, "add_2")
        breakout_close = float(close_prices.iloc[0])
        add1_reference_close = float(close_prices.iloc[0])
        highest_close_since_entry = float(close_prices.iloc[0])

    for i in range(len(df)):
        close_price = float(close_prices.iloc[i])
        stop_value = stop_line.iloc[i]
        stop_value = float(stop_value) if pd.notna(stop_value) else None

        if open_lots:
            highest_close_since_entry = max(
                highest_close_since_entry or close_price,
                close_price,
            )
            if (
                _position_quantity(open_lots, sleeve="add_1") > 0
                and _position_quantity(open_lots, sleeve="add_2") == 0
                and stop_value is not None
                and close_price > stop_value * 1.04
                and highest_close_since_entry
                and close_price < highest_close_since_entry * 0.975
            ):
                pullback_seen_after_add1 = True
                pullback_floor_close = close_price

        market_value = sum(lot["quantity"] * close_price for lot in open_lots)
        equity_curve.append(
            {"time": int(dates[i].timestamp()), "value": round(cash + market_value, 2)}
        )

        if i >= len(df) - 1:
            continue

        prev_dir = initial_prev_dir if i == 0 else int(direction.iloc[i - 1])
        curr_dir = int(direction.iloc[i])
        next_idx = i + 1
        prev_close = float(close_prices.iloc[i - 1]) if i > 0 else close_price
        add2_active = _position_quantity(open_lots, sleeve="add_2") > 0
        add1_active = _position_quantity(open_lots, sleeve="add_1") > 0
        core_active = _position_quantity(open_lots, sleeve="core") > 0

        if prev_dir == 1 and curr_dir != 1 and open_lots:
            _sell_all(next_idx)
            _reset_cycle_state()
            continue

        if prev_dir != 1 and curr_dir == 1 and not open_lots:
            breakout_close = close_price
            highest_close_since_entry = close_price
            _buy_target_weight(core_weight, next_idx, "core")
            continue

        if not core_active:
            continue

        if add2_active:
            close_to_stop = (
                stop_value is not None
                and close_price <= stop_value * 1.005
                and close_price < prev_close
            )
            failed_extension = (
                highest_close_since_entry is not None
                and close_price <= highest_close_since_entry * 0.945
                and close_price < prev_close
            )
            if close_to_stop or failed_extension:
                _sell_sleeve("add_2", next_idx)
                add2_reentry_anchor = close_price
                pullback_seen_after_add1 = True
                pullback_floor_close = close_price
                continue

        if add1_active and not add2_active:
            close_to_stop = (
                stop_value is not None
                and close_price <= stop_value * 0.995
                and close_price < prev_close
            )
            channel_weakness = (
                breakout_close is not None
                and close_price <= breakout_close * 1.005
                and close_price < prev_close
            )
            if close_to_stop or channel_weakness:
                _sell_sleeve("add_1", next_idx)
                add1_reentry_anchor = close_price
                add2_reentry_anchor = close_price
                pullback_seen_after_add1 = False
                pullback_floor_close = None
                continue

        if not add1_active:
            add1_anchor = add1_reentry_anchor if add1_reentry_anchor is not None else breakout_close
            continuation_breakout = (
                add1_anchor is not None
                and close_price >= add1_anchor * 1.005
                and close_price > prev_close
            )
            constructive_recovery = (
                add1_reentry_anchor is not None
                and stop_value is not None
                and close_price > prev_close
                and close_price > stop_value * 1.03
            )
            if continuation_breakout or constructive_recovery:
                if _buy_target_weight(add1_weight, next_idx, "add_1"):
                    add1_reference_close = close_price
                    add1_reentry_anchor = None
                    if add2_reentry_anchor is None:
                        add2_reentry_anchor = close_price
                continue

        if add1_active and not add2_active:
            add2_anchor = add2_reentry_anchor if add2_reentry_anchor is not None else add1_reference_close
            continuation_breakout = (
                add2_anchor is not None
                and close_price >= add2_anchor * 1.01
                and close_price > prev_close
            )
            constructive_recovery = (
                pullback_seen_after_add1
                and stop_value is not None
                and close_price > prev_close
                and close_price > stop_value * 1.04
                and (
                    pullback_floor_close is None
                    or close_price >= pullback_floor_close * 1.03
                )
            )
            if continuation_breakout or constructive_recovery:
                if _buy_target_weight(add2_weight, next_idx, "add_2"):
                    add2_reentry_anchor = None
                    pullback_seen_after_add1 = False
                    pullback_floor_close = None
                continue

    if open_lots:
        trades.extend(
            _mark_open_lots_to_market(open_lots, dates[-1], close_prices.iloc[-1])
        )

    summary = compute_summary(trades, equity_curve)
    return trades, summary, equity_curve


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


def backtest_confirmation_layering(
    df,
    daily_direction,
    weekly_direction,
    prior_daily_direction=None,
    prior_weekly_direction=None,
    initial_capital=INITIAL_CAPITAL,
    starter_fraction=0.30,
    confirmed_fraction=0.70,
    semantics="generic_layered",
    weekly_nonbull_exit_bars=1,
):
    """Backtest staged exposure using daily starter and weekly confirmation."""
    if df.empty:
        summary = compute_summary([], [], initial_capital=initial_capital)
        return [], summary, []

    starter_fraction = max(0.0, float(starter_fraction))
    confirmed_fraction = max(0.0, float(confirmed_fraction))
    total_fraction = starter_fraction + confirmed_fraction
    if total_fraction <= 0:
        summary = compute_summary([], [], initial_capital=initial_capital)
        return [], summary, []
    if total_fraction > 1.0:
        starter_fraction /= total_fraction
        confirmed_fraction /= total_fraction

    daily_direction = daily_direction.reindex(df.index)
    weekly_direction = weekly_direction.reindex(df.index).ffill().fillna(0)
    open_prices = df["Open"]
    close_prices = df["Close"]
    dates = df.index
    week_periods = dates.to_period("W-FRI")

    trades = []
    equity_curve = []
    cash = float(initial_capital)
    open_lots = []
    weekly_nonbull_streak = 0
    last_week_period = None

    def _target_sleeves(daily_state, weekly_state):
        daily_bull = int(daily_state) == 1
        weekly_bull = int(weekly_state) == 1
        if semantics == "escalation_layered":
            if daily_bull and weekly_bull:
                return True, True
            if daily_bull:
                return True, False
            return False, False
        if daily_bull and weekly_bull:
            return True, True
        if daily_bull or weekly_bull:
            return True, False
        return False, False

    def _buy_weight(weight, execution_idx, sleeve):
        nonlocal cash
        execution_price = round(float(open_prices.iloc[execution_idx]), 2)
        if execution_price <= 0 or weight <= 0:
            return False
        budget = min(cash, initial_capital * weight)
        if budget <= 0:
            return False
        _buy_lot(open_lots, dates[execution_idx], execution_price, budget, sleeve=sleeve)
        cash -= budget
        return True

    def _sell_sleeve(sleeve, execution_idx):
        nonlocal cash
        execution_price = round(float(open_prices.iloc[execution_idx]), 2)
        if execution_price <= 0:
            return 0.0
        proceeds = _sell_fraction(
            open_lots,
            trades,
            dates[execution_idx],
            execution_price,
            1.0,
            sleeve=sleeve,
        )
        cash += proceeds
        return proceeds

    def _sync_target_sleeves(execution_idx, want_starter, want_confirmed):
        starter_active = _position_quantity(open_lots, sleeve="starter") > 0
        confirmed_active = _position_quantity(open_lots, sleeve="confirmed") > 0

        if confirmed_active and not want_confirmed:
            _sell_sleeve("confirmed", execution_idx)
        if starter_active and not want_starter:
            _sell_sleeve("starter", execution_idx)
        if want_starter and not starter_active:
            _buy_weight(starter_fraction, execution_idx, "starter")
        if want_confirmed and not confirmed_active:
            _buy_weight(confirmed_fraction, execution_idx, "confirmed")

    def _target_sleeves_with_state(
        daily_state,
        weekly_state,
        *,
        confirmed_active,
        weekly_nonbull_streak_value,
    ):
        daily_bull = int(daily_state) == 1
        weekly_bull = int(weekly_state) == 1
        if semantics == "family_scoped_slow_exit":
            if not daily_bull:
                return False, False
            if weekly_bull:
                return True, True
            if confirmed_active and weekly_nonbull_streak_value < max(
                1, int(weekly_nonbull_exit_bars)
            ):
                return True, True
            return True, False
        return _target_sleeves(daily_state, weekly_state)

    initial_daily = (
        int(prior_daily_direction)
        if prior_daily_direction is not None and not pd.isna(prior_daily_direction)
        else _direction_at(daily_direction, 0, 0)
    )
    initial_weekly = (
        int(prior_weekly_direction)
        if prior_weekly_direction is not None and not pd.isna(prior_weekly_direction)
        else _direction_at(weekly_direction, 0, 0)
    )
    want_starter, want_confirmed = _target_sleeves(initial_daily, initial_weekly)
    if want_starter:
        _buy_weight(starter_fraction, 0, "starter")
    if want_confirmed:
        _buy_weight(confirmed_fraction, 0, "confirmed")

    prev_daily = initial_daily
    prev_weekly = initial_weekly

    for i in range(len(df)):
        market_value = _position_quantity(open_lots) * float(close_prices.iloc[i])
        equity_curve.append(
            {
                "time": int(dates[i].timestamp()),
                "value": round(cash + market_value, 2),
            }
        )

        if i >= len(df) - 1:
            continue

        curr_daily = _direction_at(daily_direction, i, prev_daily)
        curr_weekly = _direction_at(weekly_direction, i, prev_weekly)
        if semantics == "family_scoped_slow_exit":
            current_week_period = week_periods[i]
            if last_week_period is None or current_week_period != last_week_period:
                weekly_nonbull_streak = (
                    weekly_nonbull_streak + 1 if curr_weekly != 1 else 0
                )
                last_week_period = current_week_period
            confirmed_active = _position_quantity(open_lots, sleeve="confirmed") > 0
            want_starter, want_confirmed = _target_sleeves_with_state(
                curr_daily,
                curr_weekly,
                confirmed_active=confirmed_active,
                weekly_nonbull_streak_value=weekly_nonbull_streak,
            )
        else:
            want_starter, want_confirmed = _target_sleeves(curr_daily, curr_weekly)
        _sync_target_sleeves(i + 1, want_starter, want_confirmed)
        prev_daily = curr_daily
        prev_weekly = curr_weekly

    if open_lots:
        trades.extend(
            _mark_open_lots_to_market(open_lots, dates[-1], close_prices.iloc[-1])
        )

    summary = compute_summary(trades, equity_curve, initial_capital=initial_capital)
    return trades, summary, equity_curve


def backtest_weekly_core_daily_overlay(
    df,
    core_direction,
    overlay_direction,
    *,
    prior_core_direction=None,
    prior_overlay_direction=None,
    initial_capital=INITIAL_CAPITAL,
    core_fraction=0.70,
    overlay_fraction=0.30,
):
    """Backtest a two-speed architecture with weekly core and daily overlay.

    The core sleeve stays invested while the slower regime remains bullish.
    The overlay sleeve adds only when the faster regime is also bullish.
    """
    if df.empty:
        summary = compute_summary([], [], initial_capital=initial_capital)
        return [], summary, []

    core_fraction = max(0.0, float(core_fraction))
    overlay_fraction = max(0.0, float(overlay_fraction))
    total_fraction = core_fraction + overlay_fraction
    if total_fraction <= 0:
        summary = compute_summary([], [], initial_capital=initial_capital)
        return [], summary, []
    if total_fraction > 1.0:
        core_fraction /= total_fraction
        overlay_fraction /= total_fraction

    core_direction = core_direction.reindex(df.index).ffill().fillna(0)
    overlay_direction = overlay_direction.reindex(df.index).ffill().fillna(0)
    open_prices = df["Open"]
    close_prices = df["Close"]
    dates = df.index

    trades = []
    equity_curve = []
    cash = float(initial_capital)
    open_lots = []

    def _buy_weight(weight, execution_idx, sleeve):
        nonlocal cash
        execution_price = round(float(open_prices.iloc[execution_idx]), 2)
        if execution_price <= 0 or weight <= 0:
            return False
        budget = min(cash, initial_capital * weight)
        if budget <= 0:
            return False
        _buy_lot(open_lots, dates[execution_idx], execution_price, budget, sleeve=sleeve)
        cash -= budget
        return True

    def _sell_sleeve(sleeve, execution_idx):
        nonlocal cash
        execution_price = round(float(open_prices.iloc[execution_idx]), 2)
        if execution_price <= 0:
            return 0.0
        proceeds = _sell_fraction(
            open_lots,
            trades,
            dates[execution_idx],
            execution_price,
            1.0,
            sleeve=sleeve,
        )
        cash += proceeds
        return proceeds

    def _sync_target(execution_idx, want_core, want_overlay):
        core_active = _position_quantity(open_lots, sleeve="core") > 0
        overlay_active = _position_quantity(open_lots, sleeve="overlay") > 0

        if overlay_active and not want_overlay:
            _sell_sleeve("overlay", execution_idx)
        if core_active and not want_core:
            _sell_sleeve("core", execution_idx)

        core_active = _position_quantity(open_lots, sleeve="core") > 0
        overlay_active = _position_quantity(open_lots, sleeve="overlay") > 0
        if want_core and not core_active:
            _buy_weight(core_fraction, execution_idx, "core")
        if want_overlay and not overlay_active:
            _buy_weight(overlay_fraction, execution_idx, "overlay")

    initial_core = (
        int(prior_core_direction)
        if prior_core_direction is not None and not pd.isna(prior_core_direction)
        else _direction_at(core_direction, 0, 0)
    )
    initial_overlay = (
        int(prior_overlay_direction)
        if prior_overlay_direction is not None and not pd.isna(prior_overlay_direction)
        else _direction_at(overlay_direction, 0, 0)
    )
    want_core = initial_core == 1
    want_overlay = want_core and initial_overlay == 1
    if want_core:
        _buy_weight(core_fraction, 0, "core")
    if want_overlay:
        _buy_weight(overlay_fraction, 0, "overlay")

    prev_core = initial_core
    prev_overlay = initial_overlay

    for i in range(len(df)):
        market_value = _position_quantity(open_lots) * float(close_prices.iloc[i])
        equity_curve.append(
            {
                "time": int(dates[i].timestamp()),
                "value": round(cash + market_value, 2),
            }
        )

        if i >= len(df) - 1:
            continue

        curr_core = _direction_at(core_direction, i, prev_core)
        curr_overlay = _direction_at(overlay_direction, i, prev_overlay)
        want_core = curr_core == 1
        want_overlay = want_core and curr_overlay == 1
        _sync_target(i + 1, want_core, want_overlay)
        prev_core = curr_core
        prev_overlay = curr_overlay

    if open_lots:
        trades.extend(
            _mark_open_lots_to_market(open_lots, dates[-1], close_prices.iloc[-1])
        )

    summary = compute_summary(trades, equity_curve, initial_capital=initial_capital)
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
    asymmetric_exit: bool = False,
) -> pd.Series:
    """Build a cycle-level ribbon regime from daily flips and weekly confirmation.

    Bull entries require daily bull + weekly carried bull. Bear exits trigger on a
    daily bear flip once the raw weekly ribbon has been non-bull for enough bars.
    After each exit, re-entry can be locked out for either a fixed number of bars
    or a fraction of the just-completed bull regime's duration.

    When *asymmetric_exit* is True, exits fire on a daily bear flip alone —
    the weekly non-bull confirmation is skipped. Entries still require weekly
    agreement, giving fast crash protection with filtered entries.
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

        exit_triggered = (
            state == 1
            and daily_value == -1
            and (asymmetric_exit or weekly_nonbull_streak >= nonbull_confirm_bars)
        )

        if exit_triggered:
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
    asymmetric_exit=False,
):
    """Backtest a weekly-confirmed bull/bear ribbon regime: long in bull, cash in bear."""
    confirmed_direction = build_weekly_confirmed_ribbon_direction(
        daily_direction,
        weekly_direction,
        initial_direction=prior_direction or 0,
        reentry_cooldown_bars=reentry_cooldown_bars,
        reentry_cooldown_ratio=reentry_cooldown_ratio,
        weekly_nonbull_confirm_bars=weekly_nonbull_confirm_bars,
        asymmetric_exit=asymmetric_exit,
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
