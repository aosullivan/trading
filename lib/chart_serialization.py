import pandas as pd

from lib.settings import VOLUME_PROFILE_BUCKETS
from lib.technical_indicators import (
    BOLLINGER_PERIOD,
    BOLLINGER_STD_DEV,
    CB150_PERIOD,
    DONCHIAN_PERIOD,
    EMA_FAST_PERIOD,
    EMA_SLOW_PERIOD,
    compute_bollinger_breakout,
    compute_cci_hysteresis,
    compute_cci_trend,
    compute_channel_breakout_close,
    compute_donchian_breakout,
    compute_ema_crossover,
    compute_keltner_breakout,
    compute_macd_crossover,
    compute_corpus_trend_signal,
    compute_trend_ribbon,
)
from lib.specialized_strategies import (
    EMA_9_26_KEY,
    SEMIS_PERSIST_KEY,
    compute_semis_persist_strategy,
)


_DEFAULT_CORE_OVERLAY_PROFILE = {
    "core": "cb150",
    "overlay": "donchian",
}

_CORE_OVERLAY_STRATEGY_PROFILES = {
    "BTC-USD": {"core": "donchian", "overlay": "donchian"},
    "ETH-USD": {"core": "donchian", "overlay": "donchian"},
    "COIN": {"core": "macd", "overlay": "keltner"},
}


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


def summarize_direction_state(direction_series):
    """Summarize the live regime plus the most recent real flip, if any."""
    direction_values = direction_series.dropna()
    direction_values = direction_values[direction_values != 0]
    if direction_values.empty:
        return {
            "current_dir": None,
            "current_state_date": None,
            "regime_start_date": None,
            "last_flip_date": None,
            "last_flip_dir": None,
        }

    current_value = int(direction_values.iloc[-1])
    current_dir = "bullish" if current_value == 1 else "bearish"
    current_state_date = direction_values.index[-1].strftime("%Y-%m-%d")

    regime_start_idx = len(direction_values) - 1
    while regime_start_idx > 0 and int(direction_values.iloc[regime_start_idx - 1]) == current_value:
        regime_start_idx -= 1
    regime_start_date = direction_values.index[regime_start_idx].strftime("%Y-%m-%d")

    last_flip_date = None
    last_flip_dir = None
    for i in range(len(direction_values) - 1, 0, -1):
        if direction_values.iloc[i] != direction_values.iloc[i - 1]:
            last_flip_date = direction_values.index[i].strftime("%Y-%m-%d")
            last_flip_dir = "bullish" if int(direction_values.iloc[i]) == 1 else "bearish"
            break

    return {
        "current_dir": current_dir,
        "current_state_date": current_state_date,
        "regime_start_date": regime_start_date,
        "last_flip_date": last_flip_date,
        "last_flip_dir": last_flip_dir,
    }


def last_trend_flip(direction_series):
    """Find the most recent change in direction."""
    state = summarize_direction_state(direction_series)
    return state["last_flip_date"], state["last_flip_dir"]


def _core_overlay_profile(ticker: str | None) -> dict[str, str]:
    profile = dict(_DEFAULT_CORE_OVERLAY_PROFILE)
    if ticker:
        profile.update(_CORE_OVERLAY_STRATEGY_PROFILES.get(ticker.upper(), {}))
    return profile


def _weekly_core_overlay_direction(
    src_df,
    ticker: str | None,
):
    close_index = src_df.index
    core_overlay = _core_overlay_profile(ticker)
    _cb150_hc, _cb150_lc, cb150_direction = compute_channel_breakout_close(src_df, CB150_PERIOD)
    _donch_upper, _donch_lower, donch_direction = compute_donchian_breakout(src_df, DONCHIAN_PERIOD)
    _macd_line, _signal_line, _hist, macd_direction = compute_macd_crossover(src_df)
    _kelt_upper, _kelt_mid, _kelt_lower, kelt_direction = compute_keltner_breakout(src_df)

    core_direction = {
        "cb150": cb150_direction,
        "donchian": donch_direction,
        "macd": macd_direction,
    }.get(core_overlay["core"], cb150_direction)
    overlay_direction = {
        "donchian": donch_direction,
        "keltner": kelt_direction,
    }.get(core_overlay["overlay"], donch_direction)

    composite = pd.Series(-1, index=close_index, dtype=int)
    composite[(core_direction > 0) | (overlay_direction > 0)] = 1
    return composite


def _polymarket_direction(src_df, ticker: str | None):
    if (ticker or "").upper() != "BTC-USD":
        return pd.Series(0, index=src_df.index, dtype=int)
    from lib.polymarket import compute_polymarket_direction_series, load_probability_history

    return compute_polymarket_direction_series(
        src_df,
        probability_history_df=load_probability_history(auto_seed=True),
    )


def compute_all_trend_flips(
    src_df,
    period_val=10,
    multiplier_val=3,
    ribbon_kwargs=None,
    ticker: str | None = None,
):
    """Compute current regime state for the retained backtest strategy set."""
    ribbon_kwargs = ribbon_kwargs or {}
    flips = {}
    computations = [
        ("ribbon", lambda d: compute_trend_ribbon(d, **ribbon_kwargs)[4]),
        ("corpus_trend", lambda d: compute_corpus_trend_signal(d)[4]),
        ("corpus_trend_layered", lambda d: compute_corpus_trend_signal(d)[4]),
        ("weekly_core_overlay_v1", lambda d: _weekly_core_overlay_direction(d, ticker)),
        (
            "bb_breakout",
            lambda d: compute_bollinger_breakout(d, BOLLINGER_PERIOD, BOLLINGER_STD_DEV)[3],
        ),
        ("ema_crossover", lambda d: compute_ema_crossover(d, EMA_FAST_PERIOD, EMA_SLOW_PERIOD)[2]),
        (EMA_9_26_KEY, lambda d: compute_ema_crossover(d, 9, 26)[2]),
        ("cci_trend", lambda d: compute_cci_trend(d)[1]),
        ("cci_hysteresis", lambda d: compute_cci_hysteresis(d)[1]),
        (SEMIS_PERSIST_KEY, lambda d: compute_semis_persist_strategy(d)["daily_direction"]),
    ]
    if (ticker or "").upper() == "BTC-USD":
        computations.append(("polymarket", lambda d: _polymarket_direction(d, ticker)))
    for key, compute_dir in computations:
        try:
            dir_series = compute_dir(src_df)
            state = summarize_direction_state(dir_series)
            flips[key] = {
                "date": state["regime_start_date"],
                "dir": state["current_dir"],
                "current_dir": state["current_dir"],
                "current_state_date": state["current_state_date"],
                "regime_start_date": state["regime_start_date"],
                "last_flip_date": state["last_flip_date"],
                "last_flip_dir": state["last_flip_dir"],
            }
        except Exception:
            flips[key] = {
                "date": None,
                "dir": None,
                "current_dir": None,
                "current_state_date": None,
                "regime_start_date": None,
                "last_flip_date": None,
                "last_flip_dir": None,
            }
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
