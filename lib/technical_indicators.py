import numpy as np
import pandas as pd


SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 2.5
EMA_FAST_PERIOD = 5
EMA_SLOW_PERIOD = 20
MACD_FAST_PERIOD = 16
MACD_SLOW_PERIOD = 32
MACD_SIGNAL_PERIOD = 9
DONCHIAN_PERIOD = 10
CORPUS_TREND_ENTRY_PERIOD = 55
CORPUS_TREND_EXIT_PERIOD = 20
CORPUS_TREND_ATR_PERIOD = 14
CORPUS_TREND_STOP_MULTIPLIER = 2.0
RED_DAY_DIP_THRESHOLD = -0.05  # close-to-close, inclusive (≤ -5%)
# Week-over-week exit: require close > prior week's last close times (1 + eps).
RED_DAY_DIP_WEEK_EXIT_EPS = 0.0
BOLLINGER_PERIOD = 30
BOLLINGER_STD_DEV = 1.5
KELTNER_EMA_PERIOD = 30
KELTNER_ATR_PERIOD = 10
KELTNER_MULTIPLIER = 1.5
PSAR_AF_START = 0.01
PSAR_AF_INCREMENT = 0.01
PSAR_AF_MAX = 0.1
CCI_PERIOD = 30
CCI_THRESHOLD = 80
RIBBON_EMA_PERIOD = 34
RIBBON_ATR_PERIOD = 14
RIBBON_FAST_PERIOD = 8
RIBBON_SLOW_PERIOD = 34
RIBBON_SMOOTH_PERIOD = 5
RIBBON_COLLAPSE_THRESHOLD = 0.06
RIBBON_EXPAND_THRESHOLD = 0.16
RIBBON_MIN_WIDTH = 0.8
RIBBON_BULL_EXPAND_THRESHOLD = 0.22
RIBBON_BEAR_EXPAND_THRESHOLD = 0.15
RIBBON_BULL_CONFIRM_BARS = 3
RIBBON_BEAR_CONFIRM_BARS = 1
CB50_PERIOD = 50
CB150_PERIOD = 150
SMA_CROSS_FAST_10 = 10
SMA_CROSS_SLOW_100 = 100
SMA_CROSS_SLOW_200 = 200
EMA_TREND_DECAY_DAYS = 105  # ~5 months of trading days
# Long only when normalized signal exceeds this (0 = paper spec). Used by tests/CI benchmarks.
EMA_TREND_LONG_THRESHOLD = 0.0
YEARLY_MA_PERIOD = 252
# Tone: TD Sequential–style setup vs close[4]; confluence filters (not a commercial MRI clone).
TONE_TD_LOOKBACK = 4
TONE_TD_SETUP = 9
TONE_MA_PERIOD = 128
TONE_RSI_PERIOD = 14


def _compute_wilder_atr(high, low, close, period):
    hl = high - low
    hc = (high - close.shift(1)).abs()
    lc = (low - close.shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = pd.Series(np.nan, index=close.index)
    if len(close) < period:
        return atr
    atr.iloc[period - 1] = tr.iloc[:period].mean()
    for i in range(period, len(close)):
        atr.iloc[i] = ((atr.iloc[i - 1] * (period - 1)) + tr.iloc[i]) / period
    return atr


def compute_supertrend(
    df,
    period=SUPERTREND_PERIOD,
    multiplier=SUPERTREND_MULTIPLIER,
):
    """Compute Supertrend indicator using TradingView's band and flip rules."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    atr = _compute_wilder_atr(high, low, close, period)

    hl2 = (high + low) / 2
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    upper_band = pd.Series(np.nan, index=df.index)
    lower_band = pd.Series(np.nan, index=df.index)
    supertrend = pd.Series(np.nan, index=df.index)
    direction = pd.Series(-1, index=df.index)

    if len(df) < period:
        return supertrend, direction

    start = period - 1
    upper_band.iloc[start] = upper_basic.iloc[start]
    lower_band.iloc[start] = lower_basic.iloc[start]
    supertrend.iloc[start] = upper_band.iloc[start]

    for i in range(start + 1, len(df)):
        upper_band.iloc[i] = (
            upper_basic.iloc[i]
            if (
                upper_basic.iloc[i] < upper_band.iloc[i - 1]
                or close.iloc[i - 1] > upper_band.iloc[i - 1]
            )
            else upper_band.iloc[i - 1]
        )
        lower_band.iloc[i] = (
            lower_basic.iloc[i]
            if (
                lower_basic.iloc[i] > lower_band.iloc[i - 1]
                or close.iloc[i - 1] < lower_band.iloc[i - 1]
            )
            else lower_band.iloc[i - 1]
        )

        if supertrend.iloc[i - 1] == upper_band.iloc[i - 1]:
            direction.iloc[i] = 1 if close.iloc[i] > upper_band.iloc[i] else -1
        else:
            direction.iloc[i] = -1 if close.iloc[i] < lower_band.iloc[i] else 1

        supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == 1 else upper_band.iloc[i]

    return supertrend, direction


def compute_channel_breakout_close(df, period=CB50_PERIOD):
    """Close-based channel breakout (Trend Following Ch.45).

    Long when today's close equals the highest close over *period* days,
    flat when it equals the lowest close.  Always-in reversal system.
    """
    close = df["Close"]
    hc = close.rolling(window=period).max()
    lc = close.rolling(window=period).min()
    direction = pd.Series(0, index=df.index)
    for i in range(period, len(df)):
        if close.iloc[i] >= hc.iloc[i]:
            direction.iloc[i] = 1
        elif close.iloc[i] <= lc.iloc[i]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
    return hc, lc, direction


def compute_sma_crossover(df, fast=SMA_CROSS_FAST_10, slow=SMA_CROSS_SLOW_100):
    """SMA crossover (Trend Following Ch.45).

    Long when SMA(fast) > SMA(slow), flat otherwise.
    """
    close = df["Close"]
    sma_fast = close.rolling(window=fast).mean()
    sma_slow = close.rolling(window=slow).mean()
    direction = pd.Series(0, index=df.index)
    for i in range(slow, len(df)):
        direction.iloc[i] = 1 if sma_fast.iloc[i] > sma_slow.iloc[i] else -1
    return sma_fast, sma_slow, direction


def compute_ema_trend_signal(df, decay_days=EMA_TREND_DECAY_DAYS):
    """EMA trend signal (Lemperiere et al., Ch.42).

    signal = (price - EMA_n) / vol_n
    where vol_n is EMA of absolute daily price changes.
    Long when signal > EMA_TREND_LONG_THRESHOLD, flat otherwise.
    """
    close = df["Close"]
    ema_ref = close.ewm(span=decay_days, adjust=False).mean()
    abs_change = close.diff().abs()
    vol = abs_change.ewm(span=decay_days, adjust=False).mean()
    signal = (close - ema_ref) / vol.replace(0, np.nan)
    direction = pd.Series(0, index=df.index)
    start = decay_days
    for i in range(start, len(df)):
        if pd.isna(signal.iloc[i]):
            direction.iloc[i] = direction.iloc[i - 1]
        else:
            direction.iloc[i] = (
                1 if signal.iloc[i] > EMA_TREND_LONG_THRESHOLD else -1
            )
    return ema_ref, signal, direction


def compute_yearly_ma_trend(df, period=YEARLY_MA_PERIOD):
    """1-Year MA trend filter (Koijen et al., Ch.49).

    Long when price > 252-day SMA (trend component of carry+trend).
    """
    close = df["Close"]
    ma = close.rolling(window=period).mean()
    direction = pd.Series(0, index=df.index)
    for i in range(period, len(df)):
        direction.iloc[i] = 1 if close.iloc[i] > ma.iloc[i] else -1
    return ma, direction


def compute_ema_crossover(df, fast=EMA_FAST_PERIOD, slow=EMA_SLOW_PERIOD):
    """Compute EMA crossover direction."""
    close = df["Close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    direction = pd.Series(0, index=df.index)
    for i in range(slow, len(df)):
        direction.iloc[i] = 1 if ema_fast.iloc[i] > ema_slow.iloc[i] else -1
    return ema_fast, ema_slow, direction


def compute_macd_crossover(
    df,
    fast=MACD_FAST_PERIOD,
    slow=MACD_SLOW_PERIOD,
    signal=MACD_SIGNAL_PERIOD,
):
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


def compute_donchian_breakout(df, period=DONCHIAN_PERIOD):
    """Compute Donchian breakout direction."""
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


def compute_corpus_trend_signal(
    df,
    entry_period=CORPUS_TREND_ENTRY_PERIOD,
    exit_period=CORPUS_TREND_EXIT_PERIOD,
    atr_period=CORPUS_TREND_ATR_PERIOD,
    stop_multiplier=CORPUS_TREND_STOP_MULTIPLIER,
):
    """Compute a long/cash Donchian breakout with trailing ATR stop discipline."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    entry_upper = high.rolling(window=entry_period).max().shift(1)
    exit_lower = low.rolling(window=exit_period).min().shift(1)
    atr = _compute_wilder_atr(high, low, close, atr_period)
    stop_line = pd.Series(np.nan, index=df.index, dtype=float)
    direction = pd.Series(-1, index=df.index, dtype=int)

    in_position = False
    trailing_stop = np.nan
    start = max(entry_period, exit_period, atr_period)
    for i in range(start, len(df)):
        price = float(close.iloc[i])
        upper = entry_upper.iloc[i]
        lower = exit_lower.iloc[i]
        atr_value = atr.iloc[i]

        if in_position and not pd.isna(atr_value):
            candidate_stop = price - (stop_multiplier * float(atr_value))
            trailing_stop = (
                candidate_stop
                if pd.isna(trailing_stop)
                else max(trailing_stop, candidate_stop)
            )

        if in_position and (
            (not pd.isna(lower) and price < float(lower))
            or (not pd.isna(trailing_stop) and price < float(trailing_stop))
        ):
            in_position = False
            trailing_stop = np.nan
        elif (
            not in_position
            and not pd.isna(upper)
            and not pd.isna(atr_value)
            and price > float(upper)
        ):
            in_position = True
            trailing_stop = price - (stop_multiplier * float(atr_value))

        direction.iloc[i] = 1 if in_position else -1
        if in_position:
            stop_line.iloc[i] = trailing_stop

    return entry_upper, exit_lower, atr, stop_line, direction


def _red_day_dip_prior_week_last_close(close: pd.Series) -> pd.Series:
    """Last close of the prior week (weeks end Friday) for each bar; NaN if unknown."""
    if close.empty:
        return pd.Series(dtype=float, index=close.index)
    period = close.index.to_period("W-FRI")
    week_last = close.groupby(period, sort=False).last()
    weeks_chrono = week_last.index.sort_values()
    prior_last_by_week: dict = {}
    for j in range(1, len(weeks_chrono)):
        prior_last_by_week[weeks_chrono[j]] = float(week_last.loc[weeks_chrono[j - 1]])
    vals = [prior_last_by_week.get(p, np.nan) for p in period]
    return pd.Series(vals, index=close.index, dtype=float)


def compute_red_day_dip(
    df,
    threshold=RED_DAY_DIP_THRESHOLD,
    week_exit_eps=RED_DAY_DIP_WEEK_EXIT_EPS,
):
    """Long when daily close-to-close return ≤ threshold (default −5%).

    Stays long across consecutive qualifying dip days until the first bar whose close
    is above the prior week's last close (week-over-week green), i.e. the first
    materially positive outcome vs the prior trading week. The first calendar week in
    the series has no prior reference, so weekly exit does not apply until a second
    week of data exists.

    Fills next-bar open via backtest_direction.
    """
    close = df["Close"]
    ret = close.pct_change()
    prior_wk_last = _red_day_dip_prior_week_last_close(close)
    direction = pd.Series(-1, index=df.index, dtype=int)
    in_long = False
    for i in range(len(df)):
        r = ret.iloc[i]
        c = float(close.iloc[i])
        pwl = prior_wk_last.iloc[i]

        exited_this_bar = False
        if in_long:
            need = float(pwl) * (1.0 + week_exit_eps) if not pd.isna(pwl) else float("nan")
            weekly_green = not pd.isna(pwl) and c > need
            if weekly_green:
                in_long = False
                exited_this_bar = True

        if not in_long and not exited_this_bar:
            if not pd.isna(r) and r <= threshold:
                in_long = True

        direction.iloc[i] = 1 if in_long else -1
    return direction


def compute_bollinger_breakout(
    df,
    period=BOLLINGER_PERIOD,
    std_dev=BOLLINGER_STD_DEV,
):
    """Compute Bollinger Band breakout direction."""
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


def compute_keltner_breakout(
    df,
    ema_period=KELTNER_EMA_PERIOD,
    atr_period=KELTNER_ATR_PERIOD,
    multiplier=KELTNER_MULTIPLIER,
):
    """Compute Keltner Channel breakout direction."""
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


def compute_parabolic_sar(
    df,
    af_start=PSAR_AF_START,
    af_increment=PSAR_AF_INCREMENT,
    af_max=PSAR_AF_MAX,
):
    """Compute Parabolic SAR trend direction."""
    high = df["High"]
    low = df["Low"]
    n = len(df)
    sar = pd.Series(np.nan, index=df.index)
    direction = pd.Series(0, index=df.index)

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


def _wilder_rsi(close: pd.Series, period: int = TONE_RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_g = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_g / avg_l.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _tone_is_doji(open_: float, high: float, low: float, close: float, body_frac: float = 0.1) -> bool:
    rng = high - low
    if rng <= 0:
        return False
    return abs(close - open_) / rng < body_frac


def _tone_is_hammer(open_: float, high: float, low: float, close: float) -> bool:
    body = abs(close - open_)
    rng = high - low
    if rng <= 0:
        return False
    upper = high - max(open_, close)
    lower = min(open_, close) - low
    if body < 1e-12:
        return lower >= 0.5 * rng and upper <= 0.15 * rng
    return lower >= 2.0 * body and upper <= body * 1.2


def _tone_is_shooting_star(open_: float, high: float, low: float, close: float) -> bool:
    body = abs(close - open_)
    rng = high - low
    if rng <= 0:
        return False
    upper = high - max(open_, close)
    lower = min(open_, close) - low
    b = max(body, 1e-12)
    return upper >= 2.0 * b and lower <= b * 1.2


def compute_tone(
    df,
    td_lookback: int = TONE_TD_LOOKBACK,
    td_setup: int = TONE_TD_SETUP,
    ma_period: int = TONE_MA_PERIOD,
    rsi_period: int = TONE_RSI_PERIOD,
):
    """Tone-style confluence: TD setup vs close[td_lookback], RSI, MACD histogram slope, candlesticks, 128 SMA.

    Approximates themes from sequential / exhaustion counting and popular oscillator confluence.
    This is not a replication of any proprietary MRI implementation.
    """
    close = df["Close"]
    open_ = df["Open"]
    high = df["High"]
    low = df["Low"]

    _macd, _sig, macd_hist, _ = compute_macd_crossover(df)
    rsi = _wilder_rsi(close, rsi_period)
    sma_long = close.rolling(window=ma_period).mean()

    direction = pd.Series(0, index=df.index, dtype=int)
    buy_streak = 0
    sell_streak = 0
    d = 0

    start = td_lookback
    for i in range(start, len(df)):
        c = float(close.iloc[i])
        c_ref = float(close.iloc[i - td_lookback])

        if c < c_ref:
            buy_streak += 1
        else:
            buy_streak = 0
        if c > c_ref:
            sell_streak += 1
        else:
            sell_streak = 0

        o = float(open_.iloc[i])
        h = float(high.iloc[i])
        l = float(low.iloc[i])
        cl = c

        r = float(rsi.iloc[i]) if not pd.isna(rsi.iloc[i]) else 50.0
        ma = sma_long.iloc[i]
        below_ma = not pd.isna(ma) and cl < float(ma)
        above_ma = not pd.isna(ma) and cl > float(ma)

        mh = macd_hist.iloc[i]
        mh1 = macd_hist.iloc[i - 1] if i >= 1 else np.nan
        mh2 = macd_hist.iloc[i - 2] if i >= 2 else np.nan
        macd_hist_rising = (
            not pd.isna(mh)
            and not pd.isna(mh1)
            and not pd.isna(mh2)
            and mh > mh1
            and mh1 > mh2
        )

        doji = _tone_is_doji(o, h, l, cl)
        hammer = _tone_is_hammer(o, h, l, cl)
        star = _tone_is_shooting_star(o, h, l, cl)

        if buy_streak == td_setup:
            long_ok = r < 55.0 or doji or hammer or macd_hist_rising
            if below_ma:
                long_ok = long_ok and (r < 45.0 or hammer or macd_hist_rising)
            if long_ok:
                d = 1
            buy_streak = 0

        if sell_streak == td_setup:
            short_ok = r > 45.0 or star
            if above_ma:
                short_ok = short_ok and (r > 58.0 or star)
            if short_ok:
                d = -1
            sell_streak = 0

        direction.iloc[i] = d

    return sma_long, rsi, direction


def compute_cci_trend(df, period=CCI_PERIOD, threshold=CCI_THRESHOLD):
    """Compute CCI trend direction."""
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


def compute_trend_ribbon(
    df,
    ema_period=RIBBON_EMA_PERIOD,
    atr_period=RIBBON_ATR_PERIOD,
    fast_period=RIBBON_FAST_PERIOD,
    slow_period=RIBBON_SLOW_PERIOD,
    smooth_period=RIBBON_SMOOTH_PERIOD,
    max_width=3.0,
    min_width=RIBBON_MIN_WIDTH,
    adx_period=14,
    collapse_threshold=RIBBON_COLLAPSE_THRESHOLD,
    expand_threshold=RIBBON_EXPAND_THRESHOLD,
    bull_expand_threshold=None,
    bear_expand_threshold=None,
    bull_confirm_bars=RIBBON_BULL_CONFIRM_BARS,
    bear_confirm_bars=RIBBON_BEAR_CONFIRM_BARS,
):
    """Compute a trend-strength ribbon with persistent bullish/bearish bands.

    Uses the normalized distance between fast and slow EMAs as a continuous
    trend score.  Direction flips only after the score reaches the opposite
    confirmation threshold, so bearish/bullish ribbons persist through weak
    counter-trend bounces instead of collapsing to a neutral zero-width line.
    Bullish re-entry can require stricter proof than bearish re-entry.
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    center = close.ewm(span=ema_period, adjust=False).mean()

    # ATR for normalisation and band sizing
    hl = high - low
    hc = (high - close.shift(1)).abs()
    lc = (low - close.shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / atr_period, min_periods=atr_period, adjust=False).mean()

    # Continuous trend score: normalized fast/slow EMA separation
    fast_ema = close.ewm(span=fast_period, adjust=False).mean()
    slow_ema = close.ewm(span=slow_period, adjust=False).mean()
    raw_trend = (fast_ema - slow_ema) / atr  # positive = bullish, negative = bearish

    # Smooth to prevent whipsaws — trend must genuinely reverse
    trend_score = raw_trend.ewm(span=smooth_period, adjust=False).mean()

    # Normalize to [-1, 1] using a rolling window of the max absolute value
    lookback = max(slow_period * 4, 100)
    rolling_max = trend_score.abs().rolling(window=lookback, min_periods=1).max()
    rolling_max = rolling_max.replace(0, 1)  # avoid division by zero
    strength = (trend_score / rolling_max).clip(-1, 1)

    if expand_threshold < collapse_threshold:
        raise ValueError("expand_threshold must be >= collapse_threshold")
    bull_expand_threshold = (
        expand_threshold if bull_expand_threshold is None else bull_expand_threshold
    )
    bear_expand_threshold = (
        expand_threshold if bear_expand_threshold is None else bear_expand_threshold
    )

    # Keep the prior trend state through same-side softening, but force flips
    # through a one-bar neutral bridge once the score crosses to the opposite
    # side. That preserves Larsson-style persistence during weak rebounds while
    # ensuring color changes only happen after visible band compression.
    direction = pd.Series(0, index=df.index, dtype=int)
    state = 0
    pending_flip = 0
    pending_count = 0
    for i in range(len(strength)):
        score = strength.iloc[i]
        close_value = close.iloc[i]
        center_value = center.iloc[i]
        if pd.isna(score):
            direction.iloc[i] = 0
            state = 0
            pending_flip = 0
            pending_count = 0
            continue

        bull_ready = score >= bull_expand_threshold and close_value >= center_value
        bear_ready = score <= -bear_expand_threshold and close_value <= center_value

        if state == 0 and pending_flip != 0:
            if pending_flip == 1:
                pending_count = pending_count + 1 if bull_ready else 0
                if pending_count >= bull_confirm_bars:
                    state = 1
                    pending_flip = 0
                    pending_count = 0
            elif pending_flip == -1:
                pending_count = pending_count + 1 if bear_ready else 0
                if pending_count >= bear_confirm_bars:
                    state = -1
                    pending_flip = 0
                    pending_count = 0
        elif state == 0:
            if bull_ready:
                pending_flip = 1
                pending_count = 1
                if pending_count >= bull_confirm_bars:
                    state = 1
                    pending_flip = 0
                    pending_count = 0
            elif bear_ready:
                pending_flip = -1
                pending_count = 1
                if pending_count >= bear_confirm_bars:
                    state = -1
                    pending_flip = 0
                    pending_count = 0
        elif state == 1:
            pending_count = 0
            if score <= -bear_expand_threshold:
                state = 0
                pending_flip = -1
                pending_count = 0
            elif -collapse_threshold <= score <= 0 and close_value <= center_value:
                state = 0
                pending_flip = 0
                pending_count = 0
        elif state == -1:
            pending_count = 0
            if score >= bull_expand_threshold:
                state = 0
                pending_flip = 1
                pending_count = 0
            elif 0 <= score <= collapse_threshold and close_value >= center_value:
                state = 0
                pending_flip = 0
                pending_count = 0

        direction.iloc[i] = state

    # Active trends keep a minimum band width and then expand with conviction.
    abs_strength = strength.abs().where(direction != 0, 0.0)
    width_mult = min_width + (max_width - min_width) * abs_strength
    width_mult = width_mult.where(direction != 0, 0.0)
    half_width = atr * width_mult / 2
    upper = center + half_width
    lower = center - half_width

    return center, upper, lower, abs_strength, direction


def detect_regime(df, ema_period=21, atr_period=10, adx_period=14, confirm_bars=3):
    """Classify market regime using fast leading indicators."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    ema = close.ewm(span=ema_period, adjust=False).mean()
    ema_slope = (ema - ema.shift(confirm_bars)) / ema.shift(confirm_bars) * 100

    hl = high - low
    hc = (high - close.shift(1)).abs()
    lc = (low - close.shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.rolling(window=atr_period).mean()
    atr_ma = atr.rolling(window=atr_period * 4).mean()
    atr_ratio = atr / atr_ma

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr_adx = tr.ewm(alpha=1 / adx_period, min_periods=adx_period, adjust=False).mean()
    plus_di = 100 * (
        plus_dm.ewm(alpha=1 / adx_period, min_periods=adx_period, adjust=False).mean()
        / atr_adx
    )
    minus_di = 100 * (
        minus_dm.ewm(alpha=1 / adx_period, min_periods=adx_period, adjust=False).mean()
        / atr_adx
    )
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.ewm(alpha=1 / adx_period, min_periods=adx_period, adjust=False).mean()

    regime = pd.Series("choppy", index=df.index)
    warmup = max(adx_period * 2, ema_period + confirm_bars, atr_period * 4)

    slope_strong = 1.5
    slope_trending = 0.4
    atr_expanding = 1.2
    atr_contracting = 0.8

    for i in range(warmup, len(df)):
        slope = abs(ema_slope.iloc[i]) if not pd.isna(ema_slope.iloc[i]) else 0
        atr_r = atr_ratio.iloc[i] if not pd.isna(atr_ratio.iloc[i]) else 1
        adx_val = adx.iloc[i] if not pd.isna(adx.iloc[i]) else 0

        if slope > slope_strong and atr_r > atr_expanding:
            regime.iloc[i] = "strong_trend"
        elif slope > slope_trending and adx_val > 25:
            regime.iloc[i] = "strong_trend"
        elif slope > slope_trending:
            regime.iloc[i] = "trending"
        elif atr_r < atr_contracting:
            regime.iloc[i] = "range_bound"
        else:
            regime.iloc[i] = "choppy"

    return regime, adx


_STRATEGY_FNS = {
    "Parabolic SAR": lambda df: compute_parabolic_sar(df)[1],
    "Supertrend": lambda df: compute_supertrend(df)[1],
}


def compute_regime_router(df):
    """Route between Supertrend and Parabolic SAR based on regime."""
    regime, _adx = detect_regime(df)
    sub_directions = {name: fn(df) for name, fn in _STRATEGY_FNS.items()}

    regime_to_strategy = {
        "strong_trend": "Parabolic SAR",
        "trending": "Parabolic SAR",
        "choppy": "Supertrend",
        "range_bound": "Supertrend",
    }

    direction = pd.Series(0, index=df.index)
    for i in range(len(df)):
        strat_name = regime_to_strategy[regime.iloc[i]]
        direction.iloc[i] = sub_directions[strat_name].iloc[i]

    return regime, direction


STRATEGIES = {
    "CB50 (50-day)": lambda df: compute_channel_breakout_close(df, CB50_PERIOD)[2],
    "CB150 (150-day)": lambda df: compute_channel_breakout_close(df, CB150_PERIOD)[2],
    "SMA 10/100 Cross": lambda df: compute_sma_crossover(df, SMA_CROSS_FAST_10, SMA_CROSS_SLOW_100)[2],
    "SMA 10/200 Cross": lambda df: compute_sma_crossover(df, SMA_CROSS_FAST_10, SMA_CROSS_SLOW_200)[2],
    "EMA Trend (5mo)": lambda df: compute_ema_trend_signal(df)[2],
    "1-Year MA Trend": lambda df: compute_yearly_ma_trend(df)[1],
    "Supertrend (10/2.5)": lambda df: compute_supertrend(df)[1],
    "EMA 5/20 Cross": lambda df: compute_ema_crossover(df)[2],
    "MACD Signal (16/32/9)": lambda df: compute_macd_crossover(df)[3],
    "Donchian (10)": lambda df: compute_donchian_breakout(df)[2],
    "Bollinger Breakout (30/1.5)": lambda df: compute_bollinger_breakout(df)[3],
    "Keltner Breakout (30/10/1.5)": lambda df: compute_keltner_breakout(df)[3],
    "Parabolic SAR (0.01/0.01/0.1)": lambda df: compute_parabolic_sar(df)[1],
    "CCI Trend (30/80)": lambda df: compute_cci_trend(df)[1],
    "Regime Router": lambda df: compute_regime_router(df)[1],
    "Tone (TD9 + confluence)": lambda df: compute_tone(df)[2],
    "Red day dip (-5%)": lambda df: compute_red_day_dip(df),
    "Polymarket Signal": lambda df: _polymarket_direction_for_df(df),
}


def _polymarket_direction_for_df(df):
    """Compute Polymarket-based direction for a given OHLCV DataFrame.

    Uses cached probability history if available, otherwise falls back
    to live Polymarket data. Only applicable to BTC-USD.
    """
    from lib.polymarket import (
        compute_polymarket_direction_series,
        load_probability_history,
    )
    prob_history = load_probability_history(auto_seed=True)
    return compute_polymarket_direction_series(
        df,
        probability_history_df=prob_history if not prob_history.empty else None,
    )
