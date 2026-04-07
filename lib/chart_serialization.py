import pandas as pd

from lib.settings import VOLUME_PROFILE_BUCKETS
from lib.technical_indicators import (
    BOLLINGER_PERIOD,
    BOLLINGER_STD_DEV,
    CB50_PERIOD,
    CB150_PERIOD,
    DONCHIAN_PERIOD,
    EMA_FAST_PERIOD,
    EMA_SLOW_PERIOD,
    SMA_CROSS_FAST_10,
    SMA_CROSS_SLOW_100,
    SMA_CROSS_SLOW_200,
    compute_bollinger_breakout,
    compute_cci_trend,
    compute_channel_breakout_close,
    compute_donchian_breakout,
    compute_ema_crossover,
    compute_ema_trend_signal,
    compute_keltner_breakout,
    compute_macd_crossover,
    compute_parabolic_sar,
    compute_red_day_dip,
    compute_regime_router,
    compute_sma_crossover,
    compute_tone,
    compute_supertrend,
    compute_trend_ribbon,
    compute_yearly_ma_trend,
)


def series_to_json(series, view_index, decimals=2):
    """Convert a pandas Series to lightweight-charts JSON."""
    view = series.loc[view_index]
    out = []
    for i in range(len(view)):
        v = view.iloc[i]
        if pd.isna(v):
            continue
        out.append({"time": int(view_index[i].timestamp()), "value": round(float(v), decimals)})
    return out


def last_trend_flip(direction_series):
    """Find the most recent change in direction."""
    direction_values = direction_series.dropna()
    direction_values = direction_values[direction_values != 0]
    if len(direction_values) < 2:
        return None, None
    for i in range(len(direction_values) - 1, 0, -1):
        if direction_values.iloc[i] != direction_values.iloc[i - 1]:
            flip_date = direction_values.index[i].strftime("%Y-%m-%d")
            flip_dir = "bullish" if direction_values.iloc[i] == 1 else "bearish"
            return flip_date, flip_dir
    return None, None


def compute_all_trend_flips(
    src_df,
    period_val=10,
    multiplier_val=3,
    ribbon_kwargs=None,
):
    """Compute last flip date/dir for every indicator on a given dataframe."""
    ribbon_kwargs = ribbon_kwargs or {}
    flips = {}
    computations = [
        ("cb50", lambda d: compute_channel_breakout_close(d, CB50_PERIOD)[2]),
        ("cb150", lambda d: compute_channel_breakout_close(d, CB150_PERIOD)[2]),
        ("sma_10_100", lambda d: compute_sma_crossover(d, SMA_CROSS_FAST_10, SMA_CROSS_SLOW_100)[2]),
        ("sma_10_200", lambda d: compute_sma_crossover(d, SMA_CROSS_FAST_10, SMA_CROSS_SLOW_200)[2]),
        ("ema_trend", lambda d: compute_ema_trend_signal(d)[2]),
        ("yearly_ma", lambda d: compute_yearly_ma_trend(d)[1]),
        ("supertrend", lambda d: compute_supertrend(d, period_val, multiplier_val)[1]),
        (
            "ema_crossover",
            lambda d: compute_ema_crossover(d, EMA_FAST_PERIOD, EMA_SLOW_PERIOD)[2],
        ),
        ("macd", lambda d: compute_macd_crossover(d)[3]),
        (
            "donchian",
            lambda d: compute_donchian_breakout(d, DONCHIAN_PERIOD)[2],
        ),
        (
            "bb_breakout",
            lambda d: compute_bollinger_breakout(
                d,
                BOLLINGER_PERIOD,
                BOLLINGER_STD_DEV,
            )[3],
        ),
        ("keltner", lambda d: compute_keltner_breakout(d)[3]),
        ("parabolic_sar", lambda d: compute_parabolic_sar(d)[1]),
        ("cci_trend", lambda d: compute_cci_trend(d)[1]),
        ("red_day_dip", lambda d: compute_red_day_dip(d)),
        ("regime_router", lambda d: compute_regime_router(d)[1]),
        ("tone", lambda d: compute_tone(d)[2]),
        ("ribbon", lambda d: compute_trend_ribbon(d, **ribbon_kwargs)[4]),
    ]
    for key, compute_dir in computations:
        try:
            dir_series = compute_dir(src_df)
            date, direction = last_trend_flip(dir_series)
            flips[key] = {"date": date, "dir": direction}
        except Exception:
            flips[key] = {"date": None, "dir": None}
    return flips


def build_volume_profile(df_view, n_buckets=VOLUME_PROFILE_BUCKETS):
    """Aggregate volume by price bucket for the visible range."""
    vol_profile = []
    if df_view.empty:
        return vol_profile

    prices = df_view["Close"]
    vols = df_view["Volume"]
    price_min, price_max = float(prices.min()), float(prices.max())
    bucket_size = (price_max - price_min) / n_buckets if price_max > price_min else 1
    for b in range(n_buckets):
        lo_price = price_min + b * bucket_size
        hi_price = lo_price + bucket_size
        mask = (prices >= lo_price) & (prices < hi_price)
        if b == n_buckets - 1:
            mask = mask | (prices == price_max)
        bucket_vol = float(vols[mask].sum())
        up_mask = mask & (df_view["Close"] >= df_view["Open"])
        dn_mask = mask & (df_view["Close"] < df_view["Open"])
        buy_vol = float(vols[up_mask].sum())
        sell_vol = float(vols[dn_mask].sum())
        vol_profile.append(
            {
                "price": round((lo_price + hi_price) / 2, 2),
                "total": bucket_vol,
                "buy": buy_vol,
                "sell": sell_vol,
            }
        )

    return vol_profile
