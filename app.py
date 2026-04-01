import json
import os
import time as _time
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# In-memory TTL cache (for quotes and short-lived data)
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 300  # seconds (5 minutes)


def _cache_get(key: str):
    """Return cached value if still fresh, else None."""
    entry = _cache.get(key)
    if entry and (_time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value):
    _cache[key] = (_time.time(), value)


# ---------------------------------------------------------------------------
# Persistent local file cache for historical OHLCV data
# ---------------------------------------------------------------------------
_DATA_CACHE_DIR = os.path.join(os.path.dirname(__file__), "data_cache")
os.makedirs(_DATA_CACHE_DIR, exist_ok=True)

# Minimum seconds before re-fetching fresh data for a ticker+interval
_DISK_CACHE_FRESHNESS = 300  # 5 minutes


def _disk_cache_path(ticker: str, interval: str) -> str:
    """Return path to the cached CSV for a ticker+interval."""
    safe = f"{ticker}_{interval}".replace("/", "_")
    return os.path.join(_DATA_CACHE_DIR, f"{safe}.csv")


def _meta_path(ticker: str, interval: str) -> str:
    safe = f"{ticker}_{interval}".replace("/", "_")
    return os.path.join(_DATA_CACHE_DIR, f"{safe}.meta.json")


def cached_download(ticker: str, **kwargs) -> pd.DataFrame:
    """Download OHLCV data with persistent local file cache.

    On first call: fetches full history and saves to CSV.
    On subsequent calls: loads cached data, fetches only new rows since the
    last cached date, appends, and re-saves. Skips re-fetch if data was
    refreshed less than _DISK_CACHE_FRESHNESS seconds ago.
    """
    interval = kwargs.get("interval", "1d")
    start = kwargs.get("start")
    end = kwargs.get("end")

    # For non-standard calls (period-based, etc.), fall back to in-memory cache
    if start is None or "period" in kwargs:
        key = f"dl:{ticker}:{json.dumps(kwargs, sort_keys=True, default=str)}"
        cached = _cache_get(key)
        if cached is not None:
            return cached
        df = yf.download(ticker, **kwargs)
        _cache_set(key, df)
        return df

    csv_path = _disk_cache_path(ticker, interval)
    meta_path = _meta_path(ticker, interval)
    cached_df = None

    # Load existing cached data
    if os.path.exists(csv_path):
        try:
            cached_df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        except Exception:
            cached_df = None

    # Check if we fetched recently enough to skip the network call
    now = _time.time()
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            if (now - meta.get("last_fetch", 0)) < _DISK_CACHE_FRESHNESS and cached_df is not None:
                # Return slice matching the requested range
                return _slice_df(cached_df, start, end)
        except Exception:
            pass

    # Determine what to fetch
    if cached_df is not None and not cached_df.empty:
        # Only fetch from day after last cached row
        last_cached = cached_df.index.max()
        fetch_start = (last_cached + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        # If fetch_start is in the future, nothing new to get
        if pd.Timestamp(fetch_start) > pd.Timestamp.now():
            _write_meta(meta_path, now)
            return _slice_df(cached_df, start, end)
    else:
        fetch_start = start

    # Fetch new data
    fetch_kwargs = {k: v for k, v in kwargs.items() if k not in ("start", "end")}
    fetch_kwargs["start"] = fetch_start
    fetch_kwargs["progress"] = False
    try:
        new_df = yf.download(ticker, **fetch_kwargs)
    except Exception:
        # Network error — return whatever we have cached
        if cached_df is not None:
            return _slice_df(cached_df, start, end)
        return pd.DataFrame()

    if isinstance(new_df.columns, pd.MultiIndex):
        new_df.columns = new_df.columns.get_level_values(0)

    # Merge with cached data
    if cached_df is not None and not cached_df.empty and not new_df.empty:
        combined = pd.concat([cached_df, new_df])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.sort_index(inplace=True)
    elif not new_df.empty:
        combined = new_df
    else:
        combined = cached_df if cached_df is not None else pd.DataFrame()

    # Persist to disk
    if not combined.empty:
        try:
            combined.to_csv(csv_path)
        except Exception:
            pass

    _write_meta(meta_path, now)
    return _slice_df(combined, start, end)


def _write_meta(meta_path: str, now: float):
    try:
        with open(meta_path, "w") as f:
            json.dump({"last_fetch": now}, f)
    except Exception:
        pass


def _slice_df(df: pd.DataFrame, start, end) -> pd.DataFrame:
    """Return the subset of df within [start, end]."""
    if df.empty:
        return df
    mask = pd.Series(True, index=df.index)
    if start:
        mask &= df.index >= pd.Timestamp(start)
    if end:
        mask &= df.index <= pd.Timestamp(end)
    return df.loc[mask]


app = Flask(__name__)

WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watchlist.json")
INITIAL_CAPITAL = 10000.0
DAILY_WARMUP_DAYS = 500
WEEKLY_WARMUP_DAYS = 200 * 7 + 180


def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE) as f:
            return json.load(f)
    return []


def save_watchlist(tickers):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(sorted(set(t.upper() for t in tickers)), f)


def _parse_start_date(start):
    return pd.Timestamp(start).normalize()


def _parse_end_date(end):
    if not end:
        return None
    return pd.Timestamp(end).normalize()


def _warmup_start(start, interval):
    lookback_days = WEEKLY_WARMUP_DAYS if interval == "1wk" else DAILY_WARMUP_DAYS
    return (_parse_start_date(start) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")


def _visible_mask(index, start, end):
    start_ts = _parse_start_date(start)
    mask = index >= start_ts
    if end:
        end_ts = _parse_end_date(end) + timedelta(days=1) - timedelta(seconds=1)
        mask &= index <= end_ts
    return mask


def _starts_long(direction, full_index, view_index):
    if len(view_index) == 0:
        return False
    first_visible_loc = full_index.get_loc(view_index[0])
    if first_visible_loc == 0:
        return False
    return direction.iloc[first_visible_loc - 1] == 1


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


def compute_donchian_breakout(df, period=20):
    """Compute Donchian Channel breakout direction: long when close breaks above
    the highest high of the last N periods, exit when close breaks below the
    lowest low of the last N periods."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    upper = high.rolling(window=period).max()
    lower = low.rolling(window=period).min()
    direction = pd.Series(0, index=df.index)
    for i in range(period, len(df)):
        if close.iloc[i] > upper.iloc[i - 1]:
            direction.iloc[i] = 1
        elif close.iloc[i] < lower.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
    return upper, lower, direction


def compute_adx_trend(df, period=14, adx_threshold=25):
    """Compute ADX-based trend direction: long when +DI > -DI and ADX > threshold,
    short when -DI > +DI and ADX > threshold, flat otherwise."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    hl = high - low
    hc = (high - close.shift(1)).abs()
    lc = (low - close.shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    direction = pd.Series(0, index=df.index)
    start = period * 2
    for i in range(start, len(df)):
        if adx.iloc[i] > adx_threshold:
            direction.iloc[i] = 1 if plus_di.iloc[i] > minus_di.iloc[i] else -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
    return adx, plus_di, minus_di, direction


def compute_bollinger_breakout(df, period=20, std_dev=2):
    """Compute Bollinger Band breakout direction: long when close breaks above
    the upper band, exit when close falls below the middle band."""
    close = df["Close"]
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    direction = pd.Series(0, index=df.index)
    for i in range(period, len(df)):
        if close.iloc[i] > upper.iloc[i]:
            direction.iloc[i] = 1
        elif close.iloc[i] < middle.iloc[i]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
    return upper, middle, lower, direction


def compute_keltner_breakout(df, ema_period=20, atr_period=10, multiplier=1.5):
    """Compute Keltner Channel breakout: long when close breaks above upper channel,
    exit when close falls below middle line."""
    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    middle = close.ewm(span=ema_period, adjust=False).mean()
    hl = high - low
    hc = (high - close.shift(1)).abs()
    lc = (low - close.shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.rolling(window=atr_period).mean()
    upper = middle + multiplier * atr
    lower = middle - multiplier * atr

    direction = pd.Series(0, index=df.index)
    start = max(ema_period, atr_period)
    for i in range(start, len(df)):
        if close.iloc[i] > upper.iloc[i]:
            direction.iloc[i] = 1
        elif close.iloc[i] < middle.iloc[i]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
    return upper, middle, lower, direction


def compute_parabolic_sar(df, af_start=0.02, af_increment=0.02, af_max=0.2):
    """Compute Parabolic SAR trend direction."""
    high = df["High"]
    low = df["Low"]
    n = len(df)
    sar = pd.Series(np.nan, index=df.index)
    direction = pd.Series(0, index=df.index)

    # Initialize
    bull = True
    af = af_start
    ep = float(high.iloc[0])
    sar.iloc[0] = float(low.iloc[0])

    for i in range(1, n):
        prev_sar = float(sar.iloc[i - 1])
        if bull:
            sar_val = prev_sar + af * (ep - prev_sar)
            sar_val = min(sar_val, float(low.iloc[i - 1]))
            if i >= 2:
                sar_val = min(sar_val, float(low.iloc[i - 2]))
            if float(low.iloc[i]) < sar_val:
                bull = False
                sar_val = ep
                ep = float(low.iloc[i])
                af = af_start
            else:
                if float(high.iloc[i]) > ep:
                    ep = float(high.iloc[i])
                    af = min(af + af_increment, af_max)
        else:
            sar_val = prev_sar + af * (ep - prev_sar)
            sar_val = max(sar_val, float(high.iloc[i - 1]))
            if i >= 2:
                sar_val = max(sar_val, float(high.iloc[i - 2]))
            if float(high.iloc[i]) > sar_val:
                bull = True
                sar_val = ep
                ep = float(high.iloc[i])
                af = af_start
            else:
                if float(low.iloc[i]) < ep:
                    ep = float(low.iloc[i])
                    af = min(af + af_increment, af_max)

        sar.iloc[i] = sar_val
        direction.iloc[i] = 1 if bull else -1

    return sar, direction


def compute_cci_trend(df, period=20, threshold=100):
    """Compute CCI trend direction: long when CCI > threshold, short when CCI < -threshold."""
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    tp = (high + low + close) / 3
    sma = tp.rolling(window=period).mean()
    mad = tp.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci = (tp - sma) / (0.015 * mad)

    direction = pd.Series(0, index=df.index)
    for i in range(period, len(df)):
        if cci.iloc[i] > threshold:
            direction.iloc[i] = 1
        elif cci.iloc[i] < -threshold:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
    return cci, direction


def _build_equity_curve(df, trades):
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


def _compute_summary(trades, equity_curve):
    """Compute enhanced summary stats for a list of trades."""
    empty_summary = {
        "total_trades": 0,
        "winners": 0,
        "losers": 0,
        "win_rate": 0,
        "total_pnl": 0,
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

    total_pnl = sum(t["pnl"] for t in trades)
    winners = [t for t in trades if t["pnl"] > 0]
    losers = [t for t in trades if t["pnl"] <= 0]
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
        "total_trades": len(trades),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": round(len(winners) / len(trades) * 100, 1),
        "total_pnl": round(total_pnl, 2),
        "net_profit_pct": round(((ending_equity / INITIAL_CAPITAL) - 1) * 100, 2),
        "avg_pnl": round(total_pnl / len(trades), 2),
        "best_trade": round(max((t["pnl"] for t in trades), default=0), 2),
        "worst_trade": round(min((t["pnl"] for t in trades), default=0), 2),
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


def backtest_direction(df, direction, start_in_position=False):
    """Generic backtest: long when direction=1, flat otherwise, filled next bar open."""
    trades = []
    position = None
    open_prices = df["Open"]
    close = df["Close"]
    dates = df.index
    cash = INITIAL_CAPITAL

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

    for i in range(1, len(df) - 1):
        prev_dir = direction.iloc[i - 1]
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
            pnl_pct = ((execution_price / position["entry_price"]) - 1) * 100 if position["entry_price"] else 0
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
        pnl_pct = ((last_close / position["entry_price"]) - 1) * 100 if position["entry_price"] else 0
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

    equity_curve = _build_equity_curve(df, trades)
    summary = _compute_summary(trades, equity_curve)
    return trades, summary, equity_curve


def backtest_supertrend(df, direction, start_in_position=False):
    """Backtest a Supertrend strategy: long when bullish, flat when bearish."""
    return backtest_direction(df, direction, start_in_position=start_in_position)


def compute_support_resistance(df, window=5, cluster_pct=0.015, max_levels=8):
    """Detect support/resistance levels from swing highs/lows.

    Algorithm:
    1. Find swing highs (local maxima) and swing lows (local minima) using a
       rolling window.
    2. Cluster nearby price levels together (within cluster_pct of each other).
    3. Score each cluster by number of touches.
    4. Return the top levels sorted by proximity to current price.
    """
    import numpy as np

    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values

    pivots = []  # (price, type)

    # Swing highs: High[i] is the highest in a window around i
    for i in range(window, len(highs) - window):
        if highs[i] == max(highs[i - window : i + window + 1]):
            pivots.append(highs[i])
        if lows[i] == min(lows[i - window : i + window + 1]):
            pivots.append(lows[i])

    if not pivots:
        return []

    # Also consider prominent round-number levels near price range
    # (these often act as psychological S/R)

    # Cluster nearby pivots
    pivots.sort()
    clusters = []  # list of lists
    for p in pivots:
        merged = False
        for cluster in clusters:
            center = sum(cluster) / len(cluster)
            if abs(p - center) / center < cluster_pct:
                cluster.append(p)
                merged = True
                break
        if not merged:
            clusters.append([p])

    # Score clusters: more touches = stronger level
    current_price = float(closes[-1])
    levels = []
    for cluster in clusters:
        if len(cluster) < 2:
            continue  # require at least 2 touches
        avg_price = sum(cluster) / len(cluster)
        levels.append(
            {
                "price": round(avg_price, 2),
                "touches": len(cluster),
                "type": "support" if avg_price < current_price else "resistance",
            }
        )

    # Sort by proximity to current price and take the closest ones
    levels.sort(key=lambda l: abs(l["price"] - current_price))
    return levels[:max_levels]


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
        kwargs = {"start": _warmup_start(start, interval), "interval": interval, "progress": False}
        if end:
            kwargs["end"] = end
        df = cached_download(ticker, **kwargs)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if df.empty:
        return jsonify({"error": f"No data for {ticker}"}), 400

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    view_mask = _visible_mask(df.index, start, end)
    df_view = df.loc[view_mask].copy()
    if df_view.empty:
        return jsonify({"error": f"No data for {ticker} in selected range"}), 400

    supertrend, direction = compute_supertrend(df, period_val, multiplier_val)
    direction_view = direction.loc[df_view.index]
    supertrend_view = supertrend.loc[df_view.index]
    supertrend_start_long = _starts_long(direction, df.index, df_view.index)

    ema_fast, ema_slow, ema_direction = compute_ema_crossover(df, 9, 21)
    ema_direction_view = ema_direction.loc[df_view.index]
    ema_trades, ema_summary, ema_equity_curve = backtest_direction(
        df_view, ema_direction_view, start_in_position=_starts_long(ema_direction, df.index, df_view.index)
    )

    _ma_conf, ma_conf_direction = compute_ma_confirmation(df, 200, 3)
    ma_conf_direction_view = ma_conf_direction.loc[df_view.index]
    ma_conf_trades, ma_conf_summary, ma_conf_equity_curve = backtest_direction(
        df_view, ma_conf_direction_view, start_in_position=_starts_long(ma_conf_direction, df.index, df_view.index)
    )

    macd_line, signal_line, macd_hist, macd_direction = compute_macd_crossover(df)
    macd_direction_view = macd_direction.loc[df_view.index]
    macd_trades, macd_summary, macd_equity_curve = backtest_direction(
        df_view, macd_direction_view, start_in_position=_starts_long(macd_direction, df.index, df_view.index)
    )

    donch_upper, donch_lower, donch_direction = compute_donchian_breakout(df, 20)
    donch_direction_view = donch_direction.loc[df_view.index]
    donch_trades, donch_summary, donch_equity_curve = backtest_direction(
        df_view, donch_direction_view, start_in_position=_starts_long(donch_direction, df.index, df_view.index)
    )

    adx_val, plus_di, minus_di, adx_direction = compute_adx_trend(df, 14, 25)
    adx_direction_view = adx_direction.loc[df_view.index]
    adx_trades, adx_summary, adx_equity_curve = backtest_direction(
        df_view, adx_direction_view, start_in_position=_starts_long(adx_direction, df.index, df_view.index)
    )

    bb_upper, bb_mid, bb_lower, bb_direction = compute_bollinger_breakout(df, 20, 2)
    bb_direction_view = bb_direction.loc[df_view.index]
    bb_trades, bb_summary, bb_equity_curve = backtest_direction(
        df_view, bb_direction_view, start_in_position=_starts_long(bb_direction, df.index, df_view.index)
    )

    kelt_upper, kelt_mid, kelt_lower, kelt_direction = compute_keltner_breakout(df)
    kelt_direction_view = kelt_direction.loc[df_view.index]
    kelt_trades, kelt_summary, kelt_equity_curve = backtest_direction(
        df_view, kelt_direction_view, start_in_position=_starts_long(kelt_direction, df.index, df_view.index)
    )

    psar_line, psar_direction = compute_parabolic_sar(df)
    psar_direction_view = psar_direction.loc[df_view.index]
    psar_trades, psar_summary, psar_equity_curve = backtest_direction(
        df_view, psar_direction_view, start_in_position=_starts_long(psar_direction, df.index, df_view.index)
    )

    cci_val, cci_direction = compute_cci_trend(df)
    cci_direction_view = cci_direction.loc[df_view.index]
    cci_trades, cci_summary, cci_equity_curve = backtest_direction(
        df_view, cci_direction_view, start_in_position=_starts_long(cci_direction, df.index, df_view.index)
    )

    _regime, rr_direction = compute_regime_router(df)
    rr_direction_view = rr_direction.loc[df_view.index]
    rr_trades, rr_summary, rr_equity_curve = backtest_direction(
        df_view, rr_direction_view, start_in_position=_starts_long(rr_direction, df.index, df_view.index)
    )

    candles = []
    for i in range(len(df_view)):
        ts = int(df_view.index[i].timestamp())
        candles.append(
            {
                "time": ts,
                "open": round(float(df_view["Open"].iloc[i]), 2),
                "high": round(float(df_view["High"].iloc[i]), 2),
                "low": round(float(df_view["Low"].iloc[i]), 2),
                "close": round(float(df_view["Close"].iloc[i]), 2),
            }
        )

    st_up = []
    st_down = []
    for i in range(len(df_view)):
        if pd.isna(supertrend_view.iloc[i]):
            continue
        ts = int(df_view.index[i].timestamp())
        val = round(float(supertrend_view.iloc[i]), 2)
        if direction_view.iloc[i] == 1:
            st_up.append({"time": ts, "value": val})
        else:
            st_down.append({"time": ts, "value": val})

    trades, summary, equity_curve = backtest_supertrend(
        df_view, direction_view, start_in_position=supertrend_start_long
    )
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

    smas = {}
    for sma_period in [50, 100, 200]:
        sma = df["Close"].rolling(window=sma_period).mean()
        sma_view = sma.loc[df_view.index]
        sma_data = []
        for i in range(len(df_view)):
            if pd.isna(sma_view.iloc[i]):
                continue
            sma_data.append(
                {
                    "time": int(df_view.index[i].timestamp()),
                    "value": round(float(sma_view.iloc[i]), 2),
                }
            )
        smas[f"sma_{sma_period}"] = sma_data

    sma_50w = []
    sma_200w = []
    try:
        kwargs_w = {"start": _warmup_start(start, "1wk"), "interval": "1wk", "progress": False}
        if end:
            kwargs_w["end"] = end
        df_w = cached_download(ticker, **kwargs_w)
        if not df_w.empty:
            if isinstance(df_w.columns, pd.MultiIndex):
                df_w.columns = df_w.columns.get_level_values(0)
            df_w_view = df_w.loc[_visible_mask(df_w.index, start, end)]
            sma_w50 = df_w["Close"].rolling(window=50).mean()
            sma_w200 = df_w["Close"].rolling(window=200).mean()
            sma_w50_view = sma_w50.loc[df_w_view.index]
            sma_w200_view = sma_w200.loc[df_w_view.index]
            for i in range(len(df_w_view)):
                ts = int(df_w_view.index[i].timestamp())
                if not pd.isna(sma_w50_view.iloc[i]):
                    sma_50w.append({"time": ts, "value": round(float(sma_w50_view.iloc[i]), 2)})
                if not pd.isna(sma_w200_view.iloc[i]):
                    sma_200w.append({"time": ts, "value": round(float(sma_w200_view.iloc[i]), 2)})
    except Exception:
        pass

    # Support / Resistance levels
    sr_levels = compute_support_resistance(df)

    volumes = []
    for i in range(len(df_view)):
        ts = int(df_view.index[i].timestamp())
        c = df_view["Close"].iloc[i]
        o = df_view["Open"].iloc[i]
        volumes.append(
            {
                "time": ts,
                "value": int(df_view["Volume"].iloc[i]),
                "color": "rgba(38,166,154,0.5)" if c >= o else "rgba(239,83,80,0.5)",
            }
        )

    ema9_data = []
    ema21_data = []
    ema_fast_view = ema_fast.loc[df_view.index]
    ema_slow_view = ema_slow.loc[df_view.index]
    for i in range(len(df_view)):
        ts = int(df_view.index[i].timestamp())
        if not pd.isna(ema_fast_view.iloc[i]):
            ema9_data.append({"time": ts, "value": round(float(ema_fast_view.iloc[i]), 2)})
        if not pd.isna(ema_slow_view.iloc[i]):
            ema21_data.append({"time": ts, "value": round(float(ema_slow_view.iloc[i]), 2)})

    macd_line_data = []
    signal_line_data = []
    macd_hist_data = []
    macd_line_view = macd_line.loc[df_view.index]
    signal_line_view = signal_line.loc[df_view.index]
    macd_hist_view = macd_hist.loc[df_view.index]
    for i in range(len(df_view)):
        ts = int(df_view.index[i].timestamp())
        if not pd.isna(macd_line_view.iloc[i]):
            macd_line_data.append({"time": ts, "value": round(float(macd_line_view.iloc[i]), 2)})
        if not pd.isna(signal_line_view.iloc[i]):
            signal_line_data.append({"time": ts, "value": round(float(signal_line_view.iloc[i]), 2)})
        if not pd.isna(macd_hist_view.iloc[i]):
            macd_hist_data.append(
                {
                    "time": ts,
                    "value": round(float(macd_hist_view.iloc[i]), 2),
                    "color": "rgba(38,166,154,0.7)" if macd_hist_view.iloc[i] >= 0 else "rgba(239,83,80,0.7)",
                }
            )

    # --- Serialize indicator overlay data ---
    def _series_to_json(series, view_index, decimals=2):
        """Convert a pandas Series to [{time, value}, ...] for the view range."""
        view = series.loc[view_index]
        out = []
        for i in range(len(view)):
            v = view.iloc[i]
            if pd.isna(v):
                continue
            out.append({"time": int(view_index[i].timestamp()), "value": round(float(v), decimals)})
        return out

    # Donchian channels
    donch_upper_data = _series_to_json(donch_upper, df_view.index)
    donch_lower_data = _series_to_json(donch_lower, df_view.index)

    # Bollinger Bands
    bb_upper_data = _series_to_json(bb_upper, df_view.index)
    bb_mid_data = _series_to_json(bb_mid, df_view.index)
    bb_lower_data = _series_to_json(bb_lower, df_view.index)

    # Keltner Channels
    kelt_upper_data = _series_to_json(kelt_upper, df_view.index)
    kelt_mid_data = _series_to_json(kelt_mid, df_view.index)
    kelt_lower_data = _series_to_json(kelt_lower, df_view.index)

    # Parabolic SAR dots (split into bull/bear for color)
    psar_bull_data = []
    psar_bear_data = []
    psar_view = psar_line.loc[df_view.index]
    psar_dir_view = psar_direction.loc[df_view.index]
    for i in range(len(df_view)):
        v = psar_view.iloc[i]
        if pd.isna(v):
            continue
        pt = {"time": int(df_view.index[i].timestamp()), "value": round(float(v), 2)}
        if psar_dir_view.iloc[i] == 1:
            psar_bull_data.append(pt)
        else:
            psar_bear_data.append(pt)

    # ADX / +DI / -DI
    adx_data = _series_to_json(adx_val, df_view.index)
    plus_di_data = _series_to_json(plus_di, df_view.index)
    minus_di_data = _series_to_json(minus_di, df_view.index)

    # CCI
    cci_data = _series_to_json(cci_val, df_view.index)

    return jsonify(
        {
            "candles": candles,
            "supertrend_up": st_up,
            "supertrend_down": st_down,
            "volumes": volumes,
            "markers": markers,
            "trades": trades,
            "summary": summary,
            "equity_curve": equity_curve,
            **smas,
            "sma_50w": sma_50w,
            "sma_200w": sma_200w,
            "strategies": {
                "supertrend": {"trades": trades, "summary": summary, "equity_curve": equity_curve},
                "ema_crossover": {"trades": ema_trades, "summary": ema_summary, "equity_curve": ema_equity_curve},
                "macd": {"trades": macd_trades, "summary": macd_summary, "equity_curve": macd_equity_curve},
                "ma_confirm": {"trades": ma_conf_trades, "summary": ma_conf_summary, "equity_curve": ma_conf_equity_curve},
                "donchian": {"trades": donch_trades, "summary": donch_summary, "equity_curve": donch_equity_curve},
                "adx_trend": {"trades": adx_trades, "summary": adx_summary, "equity_curve": adx_equity_curve},
                "bb_breakout": {"trades": bb_trades, "summary": bb_summary, "equity_curve": bb_equity_curve},
                "keltner": {"trades": kelt_trades, "summary": kelt_summary, "equity_curve": kelt_equity_curve},
                "parabolic_sar": {"trades": psar_trades, "summary": psar_summary, "equity_curve": psar_equity_curve},
                "cci_trend": {"trades": cci_trades, "summary": cci_summary, "equity_curve": cci_equity_curve},
                "regime_router": {"trades": rr_trades, "summary": rr_summary, "equity_curve": rr_equity_curve},
            },
            "ema9": ema9_data,
            "ema21": ema21_data,
            "macd_line": macd_line_data,
            "signal_line": signal_line_data,
            "macd_hist": macd_hist_data,
            "sr_levels": sr_levels,
            "overlays": {
                "donchian": {"upper": donch_upper_data, "lower": donch_lower_data},
                "bb": {"upper": bb_upper_data, "mid": bb_mid_data, "lower": bb_lower_data},
                "keltner": {"upper": kelt_upper_data, "mid": kelt_mid_data, "lower": kelt_lower_data},
                "psar": {"bull": psar_bull_data, "bear": psar_bear_data},
                "adx": {"adx": adx_data, "plus_di": plus_di_data, "minus_di": minus_di_data},
                "cci": {"cci": cci_data},
            },
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
    """Get latest price, change, and change% for all watchlist tickers.

    Uses a single bulk yf.download() call instead of N individual Ticker
    requests to reduce Yahoo Finance API hits.
    """
    tickers = load_watchlist()
    if not tickers:
        return jsonify([])

    cache_key = f"quotes:{'|'.join(tickers)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    results = []
    try:
        # Bulk download last 5 trading days — enough to get prev close
        df = yf.download(tickers, period="5d", interval="1d", progress=False, group_by="ticker")
        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    tdf = df
                else:
                    tdf = df[ticker]
                if isinstance(tdf.columns, pd.MultiIndex):
                    tdf.columns = tdf.columns.get_level_values(0)
                tdf = tdf.dropna(subset=["Close"])
                if len(tdf) < 2:
                    raise ValueError("not enough data")
                last = round(float(tdf["Close"].iloc[-1]), 2)
                prev = round(float(tdf["Close"].iloc[-2]), 2)
                chg = round(last - prev, 2)
                chg_pct = round((chg / prev) * 100, 2) if prev else 0
                results.append({"ticker": ticker, "last": last, "chg": chg, "chg_pct": chg_pct})
            except Exception:
                results.append({"ticker": ticker, "last": None, "chg": None, "chg_pct": None})
    except Exception:
        # Fallback: return empty quotes rather than error
        results = [{"ticker": t, "last": None, "chg": None, "chg_pct": None} for t in tickers]

    # Only cache if all quotes succeeded
    if all(r["last"] is not None for r in results):
        _cache_set(cache_key, results)
    return jsonify(results)


@app.route("/api/watchlist/quote/<ticker>")
def watchlist_quote(ticker):
    """Get latest price for a single ticker."""
    cache_key = f"quote:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    try:
        df = yf.download(ticker, period="5d", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        if len(df) < 2:
            raise ValueError("not enough data")
        last = round(float(df["Close"].iloc[-1]), 2)
        prev = round(float(df["Close"].iloc[-2]), 2)
        chg = round(last - prev, 2)
        chg_pct = round((chg / prev) * 100, 2) if prev else 0
        result = {"ticker": ticker, "last": last, "chg": chg, "chg_pct": chg_pct}
    except Exception:
        result = {"ticker": ticker, "last": None, "chg": None, "chg_pct": None}

    # Only cache successful results
    if result["last"] is not None:
        _cache_set(cache_key, result)
    return jsonify(result)


def detect_regime(df, ema_period=21, atr_period=10, adx_period=14, confirm_bars=3):
    """Classify market regime using fast leading indicators.

    Uses EMA slope + ATR expansion as leading signals (detect trends early),
    with ADX as a lagging confirmation (upgrade to strong trend).

    Returns a Series with values:
        'strong_trend' - EMA slope strong AND ADX confirms (>25) OR ATR expanding fast
        'trending'     - EMA slope meaningful, ATR not contracting
        'choppy'       - EMA flat, normal volatility
        'range_bound'  - EMA flat AND ATR contracting (squeeze)
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    # --- EMA slope (fast leading indicator) ---
    ema = close.ewm(span=ema_period, adjust=False).mean()
    # Normalize slope as % change over lookback bars
    ema_slope = (ema - ema.shift(confirm_bars)) / ema.shift(confirm_bars) * 100

    # --- ATR expansion/contraction (leading indicator of breakouts) ---
    hl = high - low
    hc = (high - close.shift(1)).abs()
    lc = (low - close.shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.rolling(window=atr_period).mean()
    atr_ma = atr.rolling(window=atr_period * 4).mean()
    # ATR ratio: >1 means volatility expanding, <1 means contracting
    atr_ratio = atr / atr_ma

    # --- ADX (lagging confirmation) ---
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr_adx = tr.ewm(alpha=1 / adx_period, min_periods=adx_period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / adx_period, min_periods=adx_period, adjust=False).mean() / atr_adx)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / adx_period, min_periods=adx_period, adjust=False).mean() / atr_adx)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.ewm(alpha=1 / adx_period, min_periods=adx_period, adjust=False).mean()

    # --- Classify ---
    regime = pd.Series("choppy", index=df.index)
    warmup = max(adx_period * 2, ema_period + confirm_bars, atr_period * 4)

    # Thresholds
    slope_strong = 1.5    # EMA moved >1.5% in confirm_bars — strong directional move
    slope_trending = 0.4  # EMA moved >0.4% — mild trend
    atr_expanding = 1.2   # ATR 20% above its average — volatility breakout
    atr_contracting = 0.8 # ATR 20% below its average — squeeze

    for i in range(warmup, len(df)):
        slope = abs(ema_slope.iloc[i]) if not pd.isna(ema_slope.iloc[i]) else 0
        atr_r = atr_ratio.iloc[i] if not pd.isna(atr_ratio.iloc[i]) else 1
        adx_val = adx.iloc[i] if not pd.isna(adx.iloc[i]) else 0

        if slope > slope_strong and atr_r > atr_expanding:
            # Fast detection: big EMA move + volatility expanding = trend starting
            regime.iloc[i] = "strong_trend"
        elif slope > slope_trending and adx_val > 25:
            # Confirmed trend: moderate slope + ADX agrees
            regime.iloc[i] = "strong_trend"
        elif slope > slope_trending:
            # Mild trend: slope says yes, ADX hasn't confirmed yet
            regime.iloc[i] = "trending"
        elif atr_r < atr_contracting:
            # Squeeze: flat slope + volatility drying up
            regime.iloc[i] = "range_bound"
        else:
            regime.iloc[i] = "choppy"

    return regime, adx


# Pre-compute strategy directions keyed by name
_STRATEGY_FNS = {
    "Parabolic SAR": lambda df: compute_parabolic_sar(df)[1],
    "Supertrend": lambda df: compute_supertrend(df)[1],
}


def compute_regime_router(df):
    """Regime-based strategy router v2.

    Supertrend is the always-on base strategy. When a strong trend is
    detected (via EMA slope + ATR expansion), upgrades to Parabolic SAR
    which captures more of the move. In range-bound squeezes, goes flat
    to avoid whipsaw losses.

    Routing:
        strong_trend -> Parabolic SAR  (aggressive, captures big moves)
        trending     -> Parabolic SAR  (early upgrade, ride the trend)
        choppy       -> Supertrend     (conservative base, filters noise)
        range_bound  -> Supertrend     (stays in but Supertrend is sticky)

    Returns (regime, direction).
    """
    regime, adx = detect_regime(df)

    # Pre-compute sub-strategy directions
    sub_directions = {}
    for name, fn in _STRATEGY_FNS.items():
        sub_directions[name] = fn(df)

    # Route: Supertrend base, upgrade to Parabolic SAR in trends
    regime_to_strategy = {
        "strong_trend": "Parabolic SAR",
        "trending": "Parabolic SAR",
        "choppy": "Supertrend",
        "range_bound": "Supertrend",
    }

    direction = pd.Series(0, index=df.index)
    for i in range(len(df)):
        r = regime.iloc[i]
        strat_name = regime_to_strategy[r]
        direction.iloc[i] = sub_directions[strat_name].iloc[i]

    return regime, direction


STRATEGIES = {
    "Supertrend": lambda df: compute_supertrend(df)[1],
    "EMA 9/21 Cross": lambda df: compute_ema_crossover(df)[2],
    "MACD Signal": lambda df: compute_macd_crossover(df)[3],
    "MA Confirm (200/3)": lambda df: compute_ma_confirmation(df)[1],
    "Donchian (20)": lambda df: compute_donchian_breakout(df)[2],
    "ADX Trend (14/25)": lambda df: compute_adx_trend(df)[3],
    "Bollinger Breakout": lambda df: compute_bollinger_breakout(df)[3],
    "Keltner Breakout": lambda df: compute_keltner_breakout(df)[3],
    "Parabolic SAR": lambda df: compute_parabolic_sar(df)[1],
    "CCI Trend (20/100)": lambda df: compute_cci_trend(df)[1],
    "Regime Router": lambda df: compute_regime_router(df)[1],
}


@app.route("/report")
def report():
    return render_template("report.html")


REPORT_FILE = os.path.join(os.path.dirname(__file__), "report_data.json")


@app.route("/api/report")
def report_data():
    """Serve pre-generated report data."""
    if not os.path.exists(REPORT_FILE):
        return jsonify({"error": "No report data found. Generate it first."}), 404
    with open(REPORT_FILE) as f:
        return app.response_class(f.read(), mimetype="application/json")


if __name__ == "__main__":
    app.run(debug=True, port=5050)
