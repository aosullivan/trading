import numpy as np
import pandas as pd


def compute_supertrend(df, period=10, multiplier=3):
    """Compute Supertrend indicator using TradingView's band and flip rules."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    hl = high - low
    hc = (high - close.shift(1)).abs()
    lc = (low - close.shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = pd.Series(np.nan, index=df.index)
    if len(df) >= period:
        atr.iloc[period - 1] = tr.iloc[:period].mean()
        for i in range(period, len(df)):
            atr.iloc[i] = ((atr.iloc[i - 1] * (period - 1)) + tr.iloc[i]) / period

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


def compute_ma_confirmation(df, ma_period=200, confirm_candles=3):
    """Compute MA confirmation direction."""
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
    """Compute EMA crossover direction."""
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


def compute_adx_trend(df, period=14, adx_threshold=25):
    """Compute ADX-based trend direction."""
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
    plus_di = 100 * (
        plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr
    )
    minus_di = 100 * (
        minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr
    )
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


def compute_keltner_breakout(df, ema_period=20, atr_period=10, multiplier=1.5):
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


def compute_parabolic_sar(df, af_start=0.02, af_increment=0.02, af_max=0.2):
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


def compute_cci_trend(df, period=20, threshold=100):
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
    ema_period=21,
    atr_period=14,
    fast_period=8,
    slow_period=34,
    smooth_period=5,
    max_width=3.0,
    min_width=0.5,
    adx_period=14,
):
    """Compute a trend-strength ribbon that tapers before flipping direction.

    Uses the normalized distance between fast and slow EMAs as a continuous
    trend score.  The ribbon width is proportional to ``|trend_score|``, so
    it naturally narrows to zero before the colour changes — the direction
    can only flip *after* the trend has weakened to nothing.
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

    # Direction only flips when trend_score crosses zero — cannot flip
    # while ribbon is still wide
    direction = pd.Series(0, index=df.index, dtype=int)
    direction[strength > 0] = 1
    direction[strength < 0] = -1

    # Ribbon width proportional to |strength| — tapers to zero at crossover
    abs_strength = strength.abs()
    width_mult = min_width + (max_width - min_width) * abs_strength
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
