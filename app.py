import json
import os
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import pandas as pd
import numpy as np

app = Flask(__name__)

WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watchlist.json")


def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE) as f:
            return json.load(f)
    return []


def save_watchlist(tickers):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(sorted(set(t.upper() for t in tickers)), f)


def compute_supertrend(df, period=10, multiplier=3):
    """Compute Supertrend indicator."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    # ATR calculation
    hl = high - low
    hc = (high - close.shift(1)).abs()
    lc = (low - close.shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()

    # Basic bands
    hl2 = (high + low) / 2
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    upper_band = pd.Series(np.nan, index=df.index)
    lower_band = pd.Series(np.nan, index=df.index)
    supertrend = pd.Series(np.nan, index=df.index)
    direction = pd.Series(1, index=df.index)  # 1 = up (bullish), -1 = down (bearish)

    for i in range(period, len(df)):
        # Upper band
        if pd.isna(upper_band.iloc[i - 1]):
            upper_band.iloc[i] = upper_basic.iloc[i]
        else:
            upper_band.iloc[i] = (
                min(upper_basic.iloc[i], upper_band.iloc[i - 1])
                if close.iloc[i - 1] <= upper_band.iloc[i - 1]
                else upper_basic.iloc[i]
            )

        # Lower band
        if pd.isna(lower_band.iloc[i - 1]):
            lower_band.iloc[i] = lower_basic.iloc[i]
        else:
            lower_band.iloc[i] = (
                max(lower_basic.iloc[i], lower_band.iloc[i - 1])
                if close.iloc[i - 1] >= lower_band.iloc[i - 1]
                else lower_basic.iloc[i]
            )

        # Direction and supertrend value
        if i == period:
            direction.iloc[i] = 1 if close.iloc[i] > upper_band.iloc[i] else -1
        else:
            prev_dir = direction.iloc[i - 1]
            if prev_dir == -1 and close.iloc[i] > upper_band.iloc[i]:
                direction.iloc[i] = 1
            elif prev_dir == 1 and close.iloc[i] < lower_band.iloc[i]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = prev_dir

        supertrend.iloc[i] = (
            lower_band.iloc[i] if direction.iloc[i] == 1 else upper_band.iloc[i]
        )

    return supertrend, direction


def compute_ma_confirmation(df, ma_period=200, confirm_candles=3):
    """Compute MA Confirmation direction: 1 when close is above MA for N consecutive candles."""
    close = df["Close"]
    ma = close.rolling(window=ma_period).mean()
    above = (close > ma).astype(int)
    direction = pd.Series(0, index=df.index)
    for i in range(ma_period + confirm_candles - 1, len(df)):
        if all(above.iloc[i - j] == 1 for j in range(confirm_candles)):
            direction.iloc[i] = 1
        elif all(above.iloc[i - j] == 0 for j in range(confirm_candles)):
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
    return ma, direction


def compute_ema_crossover(df, fast=9, slow=21):
    """Compute EMA crossover direction: 1 when fast > slow, -1 otherwise."""
    close = df["Close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    direction = pd.Series(0, index=df.index)
    for i in range(slow, len(df)):
        direction.iloc[i] = 1 if ema_fast.iloc[i] > ema_slow.iloc[i] else -1
    return ema_fast, ema_slow, direction


def compute_macd_crossover(df, fast=12, slow=26, signal=9):
    """Compute MACD signal line crossover direction."""
    close = df["Close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    direction = pd.Series(0, index=df.index)
    min_period = slow + signal
    for i in range(min_period, len(df)):
        direction.iloc[i] = 1 if macd_line.iloc[i] > signal_line.iloc[i] else -1
    return macd_line, signal_line, histogram, direction


def backtest_direction(df, direction):
    """Generic backtest: long when direction=1, flat when direction=-1."""
    trades = []
    position = None
    close = df["Close"]
    dates = df.index

    for i in range(1, len(df)):
        prev_dir = direction.iloc[i - 1]
        curr_dir = direction.iloc[i]

        if prev_dir != 1 and curr_dir == 1 and position is None:
            position = {
                "entry_date": str(dates[i].date()),
                "entry_price": round(float(close.iloc[i]), 2),
                "type": "long",
            }
        elif prev_dir == 1 and curr_dir != 1 and position is not None:
            pnl = float(close.iloc[i]) - position["entry_price"]
            pnl_pct = (pnl / position["entry_price"]) * 100
            trades.append({
                **position,
                "exit_date": str(dates[i].date()),
                "exit_price": round(float(close.iloc[i]), 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
            })
            position = None

    if position is not None:
        pnl = float(close.iloc[-1]) - position["entry_price"]
        pnl_pct = (pnl / position["entry_price"]) * 100
        trades.append({
            **position,
            "exit_date": str(dates[-1].date()),
            "exit_price": round(float(close.iloc[-1]), 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "open": True,
        })

    summary = _compute_summary(trades)
    return trades, summary


def _compute_summary(trades):
    """Compute enhanced summary stats for a list of trades."""
    if not trades:
        return {
            "total_trades": 0, "winners": 0, "losers": 0, "win_rate": 0,
            "total_pnl": 0, "avg_pnl": 0, "best_trade": 0, "worst_trade": 0,
            "gross_profit": 0, "gross_loss": 0, "profit_factor": 0,
            "max_drawdown": 0, "max_drawdown_pct": 0, "avg_winner": 0, "avg_loser": 0,
        }
    total_pnl = sum(t["pnl"] for t in trades)
    winners = [t for t in trades if t["pnl"] > 0]
    losers = [t for t in trades if t["pnl"] <= 0]
    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss = abs(sum(t["pnl"] for t in losers))

    # Max drawdown from cumulative P&L
    cum = 0
    peak = 0
    max_dd = 0
    for t in trades:
        cum += t["pnl"]
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    return {
        "total_trades": len(trades),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": round(len(winners) / len(trades) * 100, 1),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(total_pnl / len(trades), 2),
        "best_trade": round(max((t["pnl"] for t in trades), default=0), 2),
        "worst_trade": round(min((t["pnl"] for t in trades), default=0), 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else 999,
        "max_drawdown": round(max_dd, 2),
        "avg_winner": round(gross_profit / len(winners), 2) if winners else 0,
        "avg_loser": round(gross_loss / len(losers), 2) if losers else 0,
    }


def backtest_supertrend(df, direction):
    """Backtest a Supertrend strategy: long when bullish, flat when bearish."""
    trades = []
    position = None  # None = flat, dict = open trade

    close = df["Close"]
    dates = df.index

    for i in range(1, len(df)):
        prev_dir = direction.iloc[i - 1]
        curr_dir = direction.iloc[i]

        # Direction changed from bearish to bullish -> buy
        if prev_dir == -1 and curr_dir == 1 and position is None:
            position = {
                "entry_date": str(dates[i].date()),
                "entry_price": round(float(close.iloc[i]), 2),
                "type": "long",
            }

        # Direction changed from bullish to bearish -> sell
        elif prev_dir == 1 and curr_dir == -1 and position is not None:
            pnl = float(close.iloc[i]) - position["entry_price"]
            pnl_pct = (pnl / position["entry_price"]) * 100
            trades.append(
                {
                    **position,
                    "exit_date": str(dates[i].date()),
                    "exit_price": round(float(close.iloc[i]), 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                }
            )
            position = None

    # Close any open position at last bar
    if position is not None:
        pnl = float(close.iloc[-1]) - position["entry_price"]
        pnl_pct = (pnl / position["entry_price"]) * 100
        trades.append(
            {
                **position,
                "exit_date": str(dates[-1].date()),
                "exit_price": round(float(close.iloc[-1]), 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "open": True,
            }
        )

    summary = _compute_summary(trades)
    return trades, summary


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/chart")
def chart_data():
    ticker = request.args.get("ticker", "TSLA")
    interval = request.args.get("interval", "1d")
    start = request.args.get("start", "2023-01-01")
    end = request.args.get("end", "")
    period_val = int(request.args.get("period", 10))
    multiplier_val = float(request.args.get("multiplier", 3))

    try:
        kwargs = {"start": start, "interval": interval, "progress": False}
        if end:
            kwargs["end"] = end
        df = yf.download(ticker, **kwargs)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if df.empty:
        return jsonify({"error": f"No data for {ticker}"}), 400

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    supertrend, direction = compute_supertrend(df, period_val, multiplier_val)

    # EMA Crossover strategy
    ema_fast, ema_slow, ema_direction = compute_ema_crossover(df, 9, 21)
    ema_trades, ema_summary = backtest_direction(df, ema_direction)

    # MA Confirmation strategy (close above 200 SMA for 3 consecutive candles)
    _ma_conf, ma_conf_direction = compute_ma_confirmation(df, 200, 3)
    ma_conf_trades, ma_conf_summary = backtest_direction(df, ma_conf_direction)

    # MACD strategy
    macd_line, signal_line, macd_hist, macd_direction = compute_macd_crossover(df)
    macd_trades, macd_summary = backtest_direction(df, macd_direction)

    # Build candle data
    candles = []
    for i in range(len(df)):
        ts = int(df.index[i].timestamp())
        candles.append(
            {
                "time": ts,
                "open": round(float(df["Open"].iloc[i]), 2),
                "high": round(float(df["High"].iloc[i]), 2),
                "low": round(float(df["Low"].iloc[i]), 2),
                "close": round(float(df["Close"].iloc[i]), 2),
            }
        )

    # Supertrend line data (split into green/red segments)
    st_up = []
    st_down = []
    for i in range(len(df)):
        if pd.isna(supertrend.iloc[i]):
            continue
        ts = int(df.index[i].timestamp())
        val = round(float(supertrend.iloc[i]), 2)
        if direction.iloc[i] == 1:
            st_up.append({"time": ts, "value": val})
        else:
            st_down.append({"time": ts, "value": val})

    # Markers for trade entries/exits
    trades, summary = backtest_supertrend(df, direction)
    markers = []
    for t in trades:
        entry_ts = int(pd.Timestamp(t["entry_date"]).timestamp())
        exit_ts = int(pd.Timestamp(t["exit_date"]).timestamp())
        markers.append(
            {
                "time": entry_ts,
                "position": "belowBar",
                "color": "#2196F3",
                "shape": "arrowUp",
                "text": f"BUY {t['entry_price']}",
            }
        )
        markers.append(
            {
                "time": exit_ts,
                "position": "aboveBar",
                "color": "#e91e63",
                "shape": "arrowDown",
                "text": f"SELL {t['exit_price']} ({t['pnl']:+.2f})",
            }
        )

    # SMA calculations
    smas = {}
    for sma_period in [50, 100, 200]:
        sma = df["Close"].rolling(window=sma_period).mean()
        sma_data = []
        for i in range(len(df)):
            if pd.isna(sma.iloc[i]):
                continue
            sma_data.append({
                "time": int(df.index[i].timestamp()),
                "value": round(float(sma.iloc[i]), 2),
            })
        smas[f"sma_{sma_period}"] = sma_data

    # 200-week SMA: fetch weekly data separately
    sma_200w = []
    try:
        kwargs_w = {"start": start, "interval": "1wk", "progress": False}
        if end:
            kwargs_w["end"] = end
        df_w = yf.download(ticker, **kwargs_w)
        if not df_w.empty:
            if isinstance(df_w.columns, pd.MultiIndex):
                df_w.columns = df_w.columns.get_level_values(0)
            sma_w = df_w["Close"].rolling(window=200).mean()
            for i in range(len(df_w)):
                if pd.isna(sma_w.iloc[i]):
                    continue
                sma_200w.append({
                    "time": int(df_w.index[i].timestamp()),
                    "value": round(float(sma_w.iloc[i]), 2),
                })
    except Exception:
        pass

    # Volume data
    volumes = []
    for i in range(len(df)):
        ts = int(df.index[i].timestamp())
        c = df["Close"].iloc[i]
        o = df["Open"].iloc[i]
        volumes.append(
            {
                "time": ts,
                "value": int(df["Volume"].iloc[i]),
                "color": "rgba(38,166,154,0.5)"
                if c >= o
                else "rgba(239,83,80,0.5)",
            }
        )

    # EMA crossover line data
    ema9_data = []
    ema21_data = []
    for i in range(len(df)):
        ts = int(df.index[i].timestamp())
        if not pd.isna(ema_fast.iloc[i]):
            ema9_data.append({"time": ts, "value": round(float(ema_fast.iloc[i]), 2)})
        if not pd.isna(ema_slow.iloc[i]):
            ema21_data.append({"time": ts, "value": round(float(ema_slow.iloc[i]), 2)})

    # MACD line data
    macd_line_data = []
    signal_line_data = []
    macd_hist_data = []
    for i in range(len(df)):
        ts = int(df.index[i].timestamp())
        if not pd.isna(macd_line.iloc[i]):
            macd_line_data.append({"time": ts, "value": round(float(macd_line.iloc[i]), 2)})
        if not pd.isna(signal_line.iloc[i]):
            signal_line_data.append({"time": ts, "value": round(float(signal_line.iloc[i]), 2)})
        if not pd.isna(macd_hist.iloc[i]):
            macd_hist_data.append({
                "time": ts,
                "value": round(float(macd_hist.iloc[i]), 2),
                "color": "rgba(38,166,154,0.7)" if macd_hist.iloc[i] >= 0 else "rgba(239,83,80,0.7)",
            })

    return jsonify(
        {
            "candles": candles,
            "supertrend_up": st_up,
            "supertrend_down": st_down,
            "volumes": volumes,
            "markers": markers,
            "trades": trades,
            "summary": summary,
            **smas,
            "sma_200w": sma_200w,
            "strategies": {
                "supertrend": {"trades": trades, "summary": summary},
                "ema_crossover": {"trades": ema_trades, "summary": ema_summary},
                "macd": {"trades": macd_trades, "summary": macd_summary},
                "ma_confirm": {"trades": ma_conf_trades, "summary": ma_conf_summary},
            },
            "ema9": ema9_data,
            "ema21": ema21_data,
            "macd_line": macd_line_data,
            "signal_line": signal_line_data,
            "macd_hist": macd_hist_data,
        }
    )


@app.route("/api/watchlist")
def get_watchlist():
    return jsonify(load_watchlist())


@app.route("/api/watchlist", methods=["POST"])
def add_to_watchlist():
    ticker = request.json.get("ticker", "").upper().strip()
    if not ticker:
        return jsonify({"error": "No ticker provided"}), 400
    wl = load_watchlist()
    if ticker not in wl:
        wl.append(ticker)
        save_watchlist(wl)
    return jsonify(load_watchlist())


@app.route("/api/watchlist", methods=["DELETE"])
def remove_from_watchlist():
    ticker = request.json.get("ticker", "").upper().strip()
    wl = load_watchlist()
    wl = [t for t in wl if t != ticker]
    save_watchlist(wl)
    return jsonify(load_watchlist())


@app.route("/api/watchlist/quotes")
def watchlist_quotes():
    """Get latest price, change, and change% for all watchlist tickers."""
    tickers = load_watchlist()
    if not tickers:
        return jsonify([])

    results = []
    for ticker in tickers:
        try:
            tk = yf.Ticker(ticker)
            info = tk.fast_info
            last = round(float(info.last_price), 2)
            prev = round(float(info.previous_close), 2)
            chg = round(last - prev, 2)
            chg_pct = round((chg / prev) * 100, 2) if prev else 0
            results.append({
                "ticker": ticker,
                "last": last,
                "chg": chg,
                "chg_pct": chg_pct,
            })
        except Exception:
            results.append({
                "ticker": ticker,
                "last": None,
                "chg": None,
                "chg_pct": None,
            })
    return jsonify(results)


if __name__ == "__main__":
    app.run(debug=True, port=5050)
