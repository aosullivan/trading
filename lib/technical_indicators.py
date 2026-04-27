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
CCI_HYSTERESIS_ENTRY_THRESHOLD = 150
CCI_HYSTERESIS_EXIT_THRESHOLD = -40
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


def compute_supertrend_i(
    df,
    period=SUPERTREND_PERIOD,
    multiplier=SUPERTREND_MULTIPLIER,
):
    """Compute an intrabar-touch Supertrend variant.

    The classic Supertrend flip waits for the close to cross the active band.
    Supertrend-I keeps the same ATR ratchet, but flips as soon as a candle's
    high/low touches the active stop line.
    """
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
            direction.iloc[i] = 1 if high.iloc[i] >= upper_band.iloc[i] else -1
        else:
            direction.iloc[i] = -1 if low.iloc[i] <= lower_band.iloc[i] else 1

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


def compute_cci_hysteresis(
    df,
    period=CCI_PERIOD,
    entry_threshold=CCI_HYSTERESIS_ENTRY_THRESHOLD,
    exit_threshold=CCI_HYSTERESIS_EXIT_THRESHOLD,
):
    """Compute a CCI trend with asymmetric entry and exit thresholds.

    This keeps long exposure sticky once CCI proves strong enough to enter,
    then exits only after momentum decays past a separate lower threshold.
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    tp = (high + low + close) / 3
    sma = tp.rolling(window=period).mean()
    mad = tp.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci = (tp - sma) / (0.015 * mad)

    direction = pd.Series(0, index=df.index)
    state = 0
    for i in range(period, len(df)):
        val = cci.iloc[i]
        if pd.isna(val):
            direction.iloc[i] = state
            continue
        if state != 1 and val > entry_threshold:
            state = 1
        elif state == 1 and val < exit_threshold:
            state = -1
        direction.iloc[i] = state
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


ORB_RANGE_PERIOD = 5
ORB_ATR_PERIOD = 14
ORB_VOLUME_AVG_PERIOD = 20
ORB_TREND_EMA_PERIOD = 50
ORB_MIN_BODY_PCT = 0.25
ORB_ATR_VOLATILITY_LOW = 0.5
ORB_ATR_VOLATILITY_HIGH = 3.0


def compute_orb_breakout(
    df,
    range_period=ORB_RANGE_PERIOD,
    atr_period=ORB_ATR_PERIOD,
    volume_avg_period=ORB_VOLUME_AVG_PERIOD,
    trend_ema_period=ORB_TREND_EMA_PERIOD,
    min_body_pct=ORB_MIN_BODY_PCT,
    use_volume_filter=True,
    use_atr_filter=True,
    use_trend_filter=True,
):
    """Opening Range Breakout adapted for daily bars.

    Establishes a range from the high/low over *range_period* bars, then
    enters when price breaks out with confirmation filters:
    - Volume spike above average
    - ATR volatility within normal bounds
    - EMA trend alignment
    - Minimum candle body relative to range size
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    open_ = df["Open"]
    volume = df["Volume"]

    range_high = high.rolling(window=range_period).max()
    range_low = low.rolling(window=range_period).min()
    range_mid = (range_high + range_low) / 2

    atr = _compute_wilder_atr(high, low, close, atr_period)
    avg_volume = volume.rolling(window=volume_avg_period).mean()
    trend_ema = close.ewm(span=trend_ema_period, adjust=False).mean()

    # Median ATR for volatility normalisation
    atr_median = atr.rolling(window=100, min_periods=20).median()

    direction = pd.Series(0, index=df.index)
    start = max(range_period, atr_period, volume_avg_period, trend_ema_period)

    for i in range(start, len(df)):
        prev_range_high = range_high.iloc[i - 1]
        prev_range_low = range_low.iloc[i - 1]

        if pd.isna(prev_range_high) or pd.isna(prev_range_low):
            direction.iloc[i] = direction.iloc[i - 1]
            continue

        orb_range = prev_range_high - prev_range_low
        if orb_range <= 0:
            direction.iloc[i] = direction.iloc[i - 1]
            continue

        cur_close = close.iloc[i]
        cur_open = open_.iloc[i]
        body = abs(cur_close - cur_open)
        body_pct = body / orb_range if orb_range > 0 else 0

        # Volume filter
        volume_ok = True
        if use_volume_filter and not pd.isna(avg_volume.iloc[i]):
            volume_ok = volume.iloc[i] > avg_volume.iloc[i]

        # ATR volatility filter
        atr_ok = True
        if use_atr_filter and not pd.isna(atr.iloc[i]) and not pd.isna(atr_median.iloc[i]):
            atr_ratio = atr.iloc[i] / atr_median.iloc[i] if atr_median.iloc[i] > 0 else 1.0
            atr_ok = ORB_ATR_VOLATILITY_LOW < atr_ratio < ORB_ATR_VOLATILITY_HIGH

        # Trend filter
        trend_long_ok = True
        trend_short_ok = True
        if use_trend_filter and not pd.isna(trend_ema.iloc[i]):
            trend_long_ok = cur_close > trend_ema.iloc[i]
            trend_short_ok = cur_close < trend_ema.iloc[i]

        body_ok = body_pct >= min_body_pct

        breakout_long = cur_close > prev_range_high
        breakout_short = cur_close < prev_range_low

        if breakout_long and body_ok and volume_ok and atr_ok and trend_long_ok:
            direction.iloc[i] = 1
        elif breakout_short and body_ok and volume_ok and atr_ok and trend_short_ok:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]

    return range_high, range_low, range_mid, trend_ema, direction


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
    "Polymarket Signal": lambda df: _polymarket_direction_for_df(df),
    "ORB Breakout (5)": lambda df: compute_orb_breakout(df)[4],
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
