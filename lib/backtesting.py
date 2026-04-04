import pandas as pd

from lib.settings import (
    INITIAL_CAPITAL,
    RIBBON_DAILY_ADD_CAPITAL,
    RIBBON_DAILY_SELL_FRACTION,
    RIBBON_MAX_CAPITAL,
    RIBBON_WEEKLY_ADD_CAPITAL,
    RIBBON_WEEKLY_SELL_FRACTION,
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
