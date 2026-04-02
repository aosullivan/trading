from lib.settings import INITIAL_CAPITAL


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


def build_buy_hold_equity_curve(df):
    equity_curve = []
    if df.empty:
        return equity_curve

    entry_price = round(float(df["Open"].iloc[0]), 2)
    shares = INITIAL_CAPITAL / entry_price if entry_price else 0

    for date, row in df.iterrows():
        equity = shares * float(row["Close"]) if shares else INITIAL_CAPITAL
        equity_curve.append({"time": int(date.timestamp()), "value": round(equity, 2)})

    return equity_curve


def compute_summary(trades, equity_curve):
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
        "ending_equity": INITIAL_CAPITAL,
        "initial_capital": INITIAL_CAPITAL,
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

    peak = INITIAL_CAPITAL
    max_dd = 0
    max_dd_pct = 0
    ending_equity = INITIAL_CAPITAL
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
        "net_profit_pct": round(((ending_equity / INITIAL_CAPITAL) - 1) * 100, 2),
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
        "initial_capital": INITIAL_CAPITAL,
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
