import time
from datetime import timedelta

from flask import Blueprint, current_app, request, jsonify
import pandas as pd

from lib.settings import DAILY_WARMUP_DAYS, WEEKLY_WARMUP_DAYS
from lib.cache import (
    _cache_get,
    _cache_set,
    _get_cached_ticker_info_if_fresh,
    _warm_ticker_info_cache_async,
    _CHART_CACHE_TTL,
)
from lib.data_fetching import (
    cached_download,
    normalize_ticker,
    is_treasury_price_ticker,
    _TREASURY_PRICE_PROXIES,
    resolve_treasury_price_proxy_ticker,
)
from lib.technical_indicators import (
    ADX_PERIOD,
    ADX_THRESHOLD,
    BOLLINGER_PERIOD,
    BOLLINGER_STD_DEV,
    DONCHIAN_PERIOD,
    EMA_FAST_PERIOD,
    EMA_SLOW_PERIOD,
    MA_CONFIRM_BEAR_CANDLES,
    MA_CONFIRM_BULL_CANDLES,
    MA_CONFIRM_PERIOD,
    SUPERTREND_MULTIPLIER,
    SUPERTREND_PERIOD,
    compute_supertrend,
    compute_ema_crossover,
    compute_ma_confirmation,
    compute_macd_crossover,
    compute_donchian_breakout,
    compute_adx_trend,
    compute_bollinger_breakout,
    compute_keltner_breakout,
    compute_parabolic_sar,
    compute_cci_trend,
    compute_trend_ribbon,
    compute_regime_router,
)
from lib.backtesting import (
    backtest_direction,
    build_weekly_confirmed_ribbon_direction,
    build_buy_hold_equity_curve,
)
from lib.chart_serialization import (
    build_volume_profile,
    compute_all_trend_flips,
    last_trend_flip,
    series_to_json,
)
from lib.trend_ribbon_profile import (
    trend_ribbon_profile_signature,
    trend_ribbon_regime_kwargs,
    trend_ribbon_signal_kwargs,
)
from lib.support_resistance import compute_support_resistance

bp = Blueprint("chart", __name__)


def _elapsed_ms(started_at: float) -> int:
    return int(round((time.perf_counter() - started_at) * 1000))


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _parse_start_date(start):
    return pd.Timestamp(start).normalize()


def _parse_end_date(end):
    if not end:
        return None
    return pd.Timestamp(end).normalize()


def _warmup_start(start, interval):
    lookback_days = WEEKLY_WARMUP_DAYS if interval in {"1wk", "1mo"} else DAILY_WARMUP_DAYS
    return (_parse_start_date(start) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")


def _source_interval(interval: str) -> str:
    return "1wk" if interval == "1mo" else interval


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    resampled = (
        df.sort_index()
        .resample(rule)
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
    )
    return resampled.dropna(subset=["Open", "High", "Low", "Close"])


def _derive_chart_frame(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if interval == "1mo":
        return _resample_ohlcv(df, "ME")
    return df


def _derive_treasury_chart_frame(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if interval == "1wk":
        return _resample_ohlcv(df, "W-FRI")
    if interval == "1mo":
        return _resample_ohlcv(df, "ME")
    return df


def _visible_mask(index, start, end):
    start_ts = _parse_start_date(start)
    mask = index >= start_ts
    if end:
        end_ts = _parse_end_date(end) + timedelta(days=1) - timedelta(seconds=1)
        mask &= index <= end_ts
    return mask


def _starts_long(direction, full_index, view_index):
    prior_direction = _prior_direction(direction, full_index, view_index)
    return prior_direction == 1


def _prior_direction(direction, full_index, view_index):
    if len(view_index) == 0:
        return None
    first_visible_loc = full_index.get_loc(view_index[0])
    if first_visible_loc == 0:
        return None
    return direction.iloc[first_visible_loc - 1]


def _run_direction_backtest(df_view, direction, full_index, view_index):
    prior_direction = _prior_direction(direction, full_index, view_index)
    return backtest_direction(
        df_view,
        direction.loc[view_index],
        start_in_position=prior_direction == 1,
        prior_direction=prior_direction,
    )


def _run_ribbon_regime_backtest(
    df_view,
    confirmed_direction,
    full_index,
    view_index,
):
    prior_direction = _prior_direction(confirmed_direction, full_index, view_index)
    return backtest_direction(
        df_view,
        confirmed_direction.loc[view_index],
        start_in_position=prior_direction == 1,
        prior_direction=prior_direction,
    )


def _carry_neutral_direction(direction: pd.Series) -> pd.Series:
    """Carry the prior non-zero state through neutral bridge bars."""
    return direction.replace(0, pd.NA).ffill().fillna(0).astype(int)


def _align_weekly_direction_to_daily(
    weekly_direction: pd.Series,
    daily_index: pd.Index,
) -> pd.Series:
    return weekly_direction.reindex(daily_index).ffill().bfill().fillna(0).astype(int)


def _trend_ribbon_kwargs(ticker: str, timeframe: str = "daily") -> dict:
    """Use the Trend Ribbon baseline profile for every ticker."""
    return trend_ribbon_signal_kwargs(ticker, timeframe=timeframe)


def _frame_signature(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "empty"
    first_ts = int(pd.Timestamp(df.index[0]).timestamp())
    last_ts = int(pd.Timestamp(df.index[-1]).timestamp())
    last_row = df.iloc[-1]
    tail_values = []
    for col in ("Open", "High", "Low", "Close", "Volume"):
        val = last_row.get(col)
        tail_values.append("nan" if pd.isna(val) else f"{float(val):.6f}")
    return f"{len(df)}:{first_ts}:{last_ts}:{':'.join(tail_values)}"


def _last_flips_from_directions(direction_map: dict[str, pd.Series]) -> dict:
    flips = {}
    for key, dir_series in direction_map.items():
        date, flip_dir = last_trend_flip(dir_series)
        flips[key] = {"date": date, "dir": flip_dir}
    return flips


def _get_indicator_bundle(
    ticker: str,
    interval: str,
    df: pd.DataFrame,
    period_val: int,
    multiplier_val: float,
) -> tuple[dict, bool]:
    cache_key = (
        f"indicator_bundle:{ticker}:{interval}:{period_val}:{multiplier_val}:"
        f"{trend_ribbon_profile_signature(ticker)}:{_frame_signature(df)}"
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached, True

    supertrend, direction = compute_supertrend(df, period_val, multiplier_val)
    ema_fast, ema_slow, ema_direction = compute_ema_crossover(
        df,
        EMA_FAST_PERIOD,
        EMA_SLOW_PERIOD,
    )
    ma_conf, ma_conf_direction = compute_ma_confirmation(
        df,
        MA_CONFIRM_PERIOD,
        MA_CONFIRM_BULL_CANDLES,
        MA_CONFIRM_BEAR_CANDLES,
    )
    macd_line, signal_line, macd_hist, macd_direction = compute_macd_crossover(df)
    donch_upper, donch_lower, donch_direction = compute_donchian_breakout(
        df,
        DONCHIAN_PERIOD,
    )
    adx_val, plus_di, minus_di, adx_direction = compute_adx_trend(
        df,
        ADX_PERIOD,
        ADX_THRESHOLD,
    )
    bb_upper, bb_mid, bb_lower, bb_direction = compute_bollinger_breakout(
        df,
        BOLLINGER_PERIOD,
        BOLLINGER_STD_DEV,
    )
    kelt_upper, kelt_mid, kelt_lower, kelt_direction = compute_keltner_breakout(df)
    psar_line, psar_direction = compute_parabolic_sar(df)
    cci_val, cci_direction = compute_cci_trend(df)
    regime, rr_direction = compute_regime_router(df)
    ribbon_center, ribbon_upper, ribbon_lower, ribbon_strength, ribbon_dir = compute_trend_ribbon(
        df,
        **_trend_ribbon_kwargs(ticker),
    )

    direction_map = {
        "ma_confirm": ma_conf_direction,
        "supertrend": direction,
        "ema_crossover": ema_direction,
        "macd": macd_direction,
        "donchian": donch_direction,
        "adx_trend": adx_direction,
        "bb_breakout": bb_direction,
        "keltner": kelt_direction,
        "parabolic_sar": psar_direction,
        "cci_trend": cci_direction,
        "regime_router": rr_direction,
        "ribbon": ribbon_dir,
    }
    bundle = {
        "supertrend": supertrend,
        "direction": direction,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "ema_direction": ema_direction,
        "ma_conf": ma_conf,
        "ma_conf_direction": ma_conf_direction,
        "macd_line": macd_line,
        "signal_line": signal_line,
        "macd_hist": macd_hist,
        "macd_direction": macd_direction,
        "donch_upper": donch_upper,
        "donch_lower": donch_lower,
        "donch_direction": donch_direction,
        "adx_val": adx_val,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "adx_direction": adx_direction,
        "bb_upper": bb_upper,
        "bb_mid": bb_mid,
        "bb_lower": bb_lower,
        "bb_direction": bb_direction,
        "kelt_upper": kelt_upper,
        "kelt_mid": kelt_mid,
        "kelt_lower": kelt_lower,
        "kelt_direction": kelt_direction,
        "psar_line": psar_line,
        "psar_direction": psar_direction,
        "cci_val": cci_val,
        "cci_direction": cci_direction,
        "regime": regime,
        "rr_direction": rr_direction,
        "ribbon_center": ribbon_center,
        "ribbon_upper": ribbon_upper,
        "ribbon_lower": ribbon_lower,
        "ribbon_strength": ribbon_strength,
        "ribbon_dir": ribbon_dir,
        "daily_flips": _last_flips_from_directions(direction_map),
    }
    _cache_set(cache_key, bundle, ttl=_CHART_CACHE_TTL)
    return bundle, False


def _get_weekly_bundle(
    ticker: str,
    df_w: pd.DataFrame,
    period_val: int,
    multiplier_val: float,
) -> tuple[dict, bool]:
    cache_key = (
        f"weekly_bundle:{ticker}:{period_val}:{multiplier_val}:"
        f"{trend_ribbon_profile_signature(ticker)}:{_frame_signature(df_w)}"
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached, True

    sma_w50 = df_w["Close"].rolling(window=50).mean()
    sma_w100 = df_w["Close"].rolling(window=100).mean()
    sma_w200 = df_w["Close"].rolling(window=200).mean()
    _ribbon_center, _ribbon_upper, _ribbon_lower, _ribbon_strength, ribbon_dir = compute_trend_ribbon(
        df_w,
        **_trend_ribbon_kwargs(ticker, timeframe="weekly"),
    )
    bundle = {
        "sma_w50": sma_w50,
        "sma_w100": sma_w100,
        "sma_w200": sma_w200,
        "ribbon_dir": ribbon_dir,
        "weekly_flips": compute_all_trend_flips(
            df_w,
            period_val=period_val,
            multiplier_val=multiplier_val,
            ribbon_kwargs=_trend_ribbon_kwargs(ticker, timeframe="weekly"),
        ),
    }
    _cache_set(cache_key, bundle, ttl=_CHART_CACHE_TTL)
    return bundle, False


def _resolve_cached_ticker_name(ticker: str) -> str:
    if is_treasury_price_ticker(ticker):
        return _TREASURY_PRICE_PROXIES[ticker]["name"]
    info = _get_cached_ticker_info_if_fresh(ticker)
    if info:
        return info.get("shortName") or info.get("longName") or ""
    _warm_ticker_info_cache_async(ticker)
    return ""


# ---------------------------------------------------------------------------
# Chart API route
# ---------------------------------------------------------------------------

@bp.route("/api/chart")
def chart_data():
    request_started_at = time.perf_counter()
    phase_started_at = request_started_at
    timings_ms = {}
    indicator_bundle_hit = False
    weekly_bundle_hit = False

    def mark_phase(name: str):
        nonlocal phase_started_at
        timings_ms[name] = _elapsed_ms(phase_started_at)
        phase_started_at = time.perf_counter()

    ticker = normalize_ticker(request.args.get("ticker", "TSLA"))
    data_ticker = normalize_ticker(resolve_treasury_price_proxy_ticker(ticker))
    interval = request.args.get("interval", "1d")
    source_interval = _source_interval(interval)
    start = request.args.get("start", "2015-01-01")
    end = request.args.get("end", "")
    period_val = int(request.args.get("period", SUPERTREND_PERIOD))
    multiplier_val = float(request.args.get("multiplier", SUPERTREND_MULTIPLIER))
    chart_cache_key = (
        f"chart:{ticker}:{interval}:{start}:{end}:{period_val}:{multiplier_val}:"
        f"{trend_ribbon_profile_signature(ticker)}"
    )
    cached_chart = _cache_get(chart_cache_key)
    if cached_chart is not None:
        if not cached_chart.get("ticker_name"):
            ticker_name = _resolve_cached_ticker_name(ticker)
            if ticker_name:
                cached_chart = {**cached_chart, "ticker_name": ticker_name}
                _cache_set(chart_cache_key, cached_chart, ttl=_CHART_CACHE_TTL)
        current_app.logger.info(
            "chart_data cache_hit ticker=%s interval=%s range=%s..%s total_ms=%s",
            ticker,
            interval,
            start,
            end or "latest",
            _elapsed_ms(request_started_at),
        )
        return jsonify(cached_chart)

    # Fetch full name for display
    ticker_name = _resolve_cached_ticker_name(ticker)
    mark_phase("metadata_ms")

    try:
        warmup_start = _warmup_start(start, interval)
        kwargs = {
            "start": warmup_start,
            "interval": source_interval,
            "progress": False,
        }
        if end:
            kwargs["end"] = end
        source_df = cached_download(data_ticker, **kwargs)
    except Exception as e:
        current_app.logger.info(
            "chart_data fetch_error ticker=%s interval=%s range=%s..%s metadata_ms=%s fetch_ms=%s total_ms=%s error=%s",
            ticker,
            interval,
            start,
            end or "latest",
            timings_ms.get("metadata_ms", 0),
            _elapsed_ms(phase_started_at),
            _elapsed_ms(request_started_at),
            str(e),
        )
        return jsonify({"error": str(e)}), 400
    mark_phase("fetch_ms")

    if source_df.empty:
        current_app.logger.info(
            "chart_data empty_source ticker=%s interval=%s range=%s..%s metadata_ms=%s fetch_ms=%s total_ms=%s",
            ticker,
            interval,
            start,
            end or "latest",
            timings_ms.get("metadata_ms", 0),
            timings_ms.get("fetch_ms", 0),
            _elapsed_ms(request_started_at),
        )
        return jsonify({"error": f"No data for {ticker}"}), 400

    if isinstance(source_df.columns, pd.MultiIndex):
        source_df.columns = source_df.columns.get_level_values(0)

    source_df = source_df[~source_df.index.duplicated(keep="last")]
    df = _derive_chart_frame(source_df, interval)

    view_mask = _visible_mask(df.index, start, end)
    df_view = df.loc[view_mask].copy()
    if df_view.index.duplicated().any():
        df_view = df_view[~df_view.index.duplicated(keep="last")]
    if df_view.empty:
        current_app.logger.info(
            "chart_data empty_view ticker=%s interval=%s range=%s..%s metadata_ms=%s fetch_ms=%s frame_ms=%s total_ms=%s",
            ticker,
            interval,
            start,
            end or "latest",
            timings_ms.get("metadata_ms", 0),
            timings_ms.get("fetch_ms", 0),
            _elapsed_ms(phase_started_at),
            _elapsed_ms(request_started_at),
        )
        return jsonify({"error": f"No data for {ticker} in selected range"}), 400
    mark_phase("frame_ms")

    # --- Compute all indicators ---
    indicator_bundle, indicator_bundle_hit = _get_indicator_bundle(
        ticker,
        interval,
        df,
        period_val,
        multiplier_val,
    )
    supertrend = indicator_bundle["supertrend"]
    direction = indicator_bundle["direction"]
    direction_view = direction.loc[df_view.index]
    supertrend_view = supertrend.loc[df_view.index]

    ema_fast = indicator_bundle["ema_fast"]
    ema_slow = indicator_bundle["ema_slow"]
    ema_direction = indicator_bundle["ema_direction"]
    ema_trades, ema_summary, ema_equity_curve = _run_direction_backtest(
        df_view, ema_direction, df.index, df_view.index
    )

    ma_conf_direction = indicator_bundle["ma_conf_direction"]
    ma_conf_trades, ma_conf_summary, ma_conf_equity_curve = _run_direction_backtest(
        df_view, ma_conf_direction, df.index, df_view.index
    )

    macd_line = indicator_bundle["macd_line"]
    signal_line = indicator_bundle["signal_line"]
    macd_hist = indicator_bundle["macd_hist"]
    macd_direction = indicator_bundle["macd_direction"]
    macd_trades, macd_summary, macd_equity_curve = _run_direction_backtest(
        df_view, macd_direction, df.index, df_view.index
    )

    donch_upper = indicator_bundle["donch_upper"]
    donch_lower = indicator_bundle["donch_lower"]
    donch_direction = indicator_bundle["donch_direction"]
    donch_trades, donch_summary, donch_equity_curve = _run_direction_backtest(
        df_view, donch_direction, df.index, df_view.index
    )

    adx_val = indicator_bundle["adx_val"]
    plus_di = indicator_bundle["plus_di"]
    minus_di = indicator_bundle["minus_di"]
    adx_direction = indicator_bundle["adx_direction"]
    adx_trades, adx_summary, adx_equity_curve = _run_direction_backtest(
        df_view, adx_direction, df.index, df_view.index
    )

    bb_upper = indicator_bundle["bb_upper"]
    bb_mid = indicator_bundle["bb_mid"]
    bb_lower = indicator_bundle["bb_lower"]
    bb_direction = indicator_bundle["bb_direction"]
    bb_trades, bb_summary, bb_equity_curve = _run_direction_backtest(
        df_view, bb_direction, df.index, df_view.index
    )

    kelt_upper = indicator_bundle["kelt_upper"]
    kelt_mid = indicator_bundle["kelt_mid"]
    kelt_lower = indicator_bundle["kelt_lower"]
    kelt_direction = indicator_bundle["kelt_direction"]
    kelt_trades, kelt_summary, kelt_equity_curve = _run_direction_backtest(
        df_view, kelt_direction, df.index, df_view.index
    )

    psar_line = indicator_bundle["psar_line"]
    psar_direction = indicator_bundle["psar_direction"]
    psar_trades, psar_summary, psar_equity_curve = _run_direction_backtest(
        df_view, psar_direction, df.index, df_view.index
    )

    cci_val = indicator_bundle["cci_val"]
    cci_direction = indicator_bundle["cci_direction"]
    cci_trades, cci_summary, cci_equity_curve = _run_direction_backtest(
        df_view, cci_direction, df.index, df_view.index
    )

    rr_direction = indicator_bundle["rr_direction"]
    rr_trades, rr_summary, rr_equity_curve = _run_direction_backtest(
        df_view, rr_direction, df.index, df_view.index
    )

    ribbon_center = indicator_bundle["ribbon_center"]
    ribbon_upper = indicator_bundle["ribbon_upper"]
    ribbon_lower = indicator_bundle["ribbon_lower"]
    ribbon_strength = indicator_bundle["ribbon_strength"]
    ribbon_dir = indicator_bundle["ribbon_dir"]
    ribbon_trades, ribbon_summary, ribbon_equity_curve = _run_direction_backtest(
        df_view, _carry_neutral_direction(ribbon_dir), df.index, df_view.index
    )
    ribbon_hold_equity_curve = None
    mark_phase("indicators_ms")

    # --- Daily flips ---
    if interval == "1d":
        daily_flips = indicator_bundle["daily_flips"]
    else:
        try:
            kwargs_d = {"start": _warmup_start(start, "1d"), "interval": "1d", "progress": False}
            if end:
                kwargs_d["end"] = end
            df_d = cached_download(data_ticker, **kwargs_d)
            if isinstance(df_d.columns, pd.MultiIndex):
                df_d.columns = df_d.columns.get_level_values(0)
            if df_d.index.duplicated().any():
                df_d = df_d[~df_d.index.duplicated(keep="last")]
            daily_flips = compute_all_trend_flips(
                df_d,
                period_val=period_val,
                multiplier_val=multiplier_val,
                ribbon_kwargs=_trend_ribbon_kwargs(ticker),
            )
        except Exception:
            daily_flips = {}
    mark_phase("daily_flips_ms")

    # --- Candles ---
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

    # --- Supertrend lines ---
    st_up = []
    st_down = []
    for i in range(len(df_view)):
        if pd.isna(supertrend_view.iloc[i]):
            continue
        ts = int(df_view.index[i].timestamp())
        val = round(float(supertrend_view.iloc[i]), 2)
        body_mid = round(float((df_view["Open"].iloc[i] + df_view["Close"].iloc[i]) / 2), 2)
        if direction_view.iloc[i] == 1:
            st_up.append({"time": ts, "value": val, "mid": body_mid})
            st_down.append({"time": ts})
        else:
            st_up.append({"time": ts})
            st_down.append({"time": ts, "value": val, "mid": body_mid})

    # --- Supertrend backtest ---
    trades, summary, equity_curve = _run_direction_backtest(
        df_view, direction, df.index, df_view.index
    )
    buy_hold_equity_curve = build_buy_hold_equity_curve(df_view)
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
        if not t.get("open"):
            markers.append(
                {
                    "time": exit_ts,
                    "position": "aboveBar",
                    "color": "#e91e63",
                    "shape": "arrowDown",
                    "text": f"SELL {t['exit_price']} ({t['pnl']:+.2f})",
                }
            )

    # --- SMAs ---
    smas = {}
    for sma_period in [50, 100, 180, 200]:
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

    # --- Weekly SMAs and flips ---
    sma_50w = []
    sma_100w = []
    sma_200w = []
    weekly_flips = {}
    try:
        if source_interval == "1wk":
            df_w = source_df.copy()
        else:
            df_w = _resample_ohlcv(source_df, "W-FRI")
        if not df_w.empty:
            if isinstance(df_w.columns, pd.MultiIndex):
                df_w.columns = df_w.columns.get_level_values(0)
            if df_w.index.duplicated().any():
                df_w = df_w[~df_w.index.duplicated(keep="last")]
            df_w_view = df_w.loc[_visible_mask(df_w.index, start, end)]
            weekly_bundle, weekly_bundle_hit = _get_weekly_bundle(
                ticker,
                df_w,
                period_val,
                multiplier_val,
            )
            sma_w50 = weekly_bundle["sma_w50"]
            sma_w100 = weekly_bundle["sma_w100"]
            sma_w200 = weekly_bundle["sma_w200"]
            sma_w50_view = sma_w50.loc[df_w_view.index]
            sma_w100_view = sma_w100.loc[df_w_view.index]
            sma_w200_view = sma_w200.loc[df_w_view.index]
            for i in range(len(df_w_view)):
                ts = int(df_w_view.index[i].timestamp())
                if not pd.isna(sma_w50_view.iloc[i]):
                    sma_50w.append({"time": ts, "value": round(float(sma_w50_view.iloc[i]), 2)})
                if not pd.isna(sma_w100_view.iloc[i]):
                    sma_100w.append({"time": ts, "value": round(float(sma_w100_view.iloc[i]), 2)})
                if not pd.isna(sma_w200_view.iloc[i]):
                    sma_200w.append({"time": ts, "value": round(float(sma_w200_view.iloc[i]), 2)})
            if interval == "1wk":
                weekly_flips = indicator_bundle["daily_flips"]
            else:
                weekly_flips = weekly_bundle["weekly_flips"]
            if interval == "1d":
                daily_ribbon_direction = _carry_neutral_direction(ribbon_dir)
                weekly_ribbon_direction = _align_weekly_direction_to_daily(
                    weekly_bundle["ribbon_dir"],
                    df.index,
                )
                ribbon_regime_kwargs = trend_ribbon_regime_kwargs(ticker)
                confirmed_ribbon_direction = build_weekly_confirmed_ribbon_direction(
                    daily_ribbon_direction,
                    weekly_ribbon_direction,
                    reentry_cooldown_bars=ribbon_regime_kwargs[
                        "reentry_cooldown_bars"
                    ],
                    reentry_cooldown_ratio=ribbon_regime_kwargs[
                        "reentry_cooldown_ratio"
                    ],
                    weekly_nonbull_confirm_bars=ribbon_regime_kwargs[
                        "weekly_nonbull_confirm_bars"
                    ],
                )
                (
                    ribbon_trades,
                    ribbon_summary,
                    ribbon_equity_curve,
                ) = _run_ribbon_regime_backtest(
                    df_view,
                    confirmed_ribbon_direction,
                    df.index,
                    df_view.index,
                )
                ribbon_hold_equity_curve = buy_hold_equity_curve
    except Exception:
        pass
    mark_phase("weekly_ms")

    # --- Support / Resistance levels ---
    sr_levels = compute_support_resistance(df, max_levels=20)
    mark_phase("support_resistance_ms")

    # --- Volumes ---
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

    # --- EMA lines ---
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

    # --- MACD ---
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

    # --- Channel overlays ---
    donch_upper_data = series_to_json(donch_upper, df_view.index)
    donch_lower_data = series_to_json(donch_lower, df_view.index)
    bb_upper_data = series_to_json(bb_upper, df_view.index)
    bb_mid_data = series_to_json(bb_mid, df_view.index)
    bb_lower_data = series_to_json(bb_lower, df_view.index)
    kelt_upper_data = series_to_json(kelt_upper, df_view.index)
    kelt_mid_data = series_to_json(kelt_mid, df_view.index)
    kelt_lower_data = series_to_json(kelt_lower, df_view.index)

    # --- Parabolic SAR ---
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

    # --- ADX / CCI ---
    adx_data = series_to_json(adx_val, df_view.index)
    plus_di_data = series_to_json(plus_di, df_view.index)
    minus_di_data = series_to_json(minus_di, df_view.index)
    cci_data = series_to_json(cci_val, df_view.index)

    # --- Trend ribbon ---
    ribbon_upper_data = []
    ribbon_lower_data = []
    r_upper_view = ribbon_upper.loc[df_view.index]
    r_lower_view = ribbon_lower.loc[df_view.index]
    r_dir_view = ribbon_dir.loc[df_view.index]
    r_strength_view = ribbon_strength.loc[df_view.index]
    for i in range(len(df_view)):
        ts = int(df_view.index[i].timestamp())
        u, lo, d, s = r_upper_view.iloc[i], r_lower_view.iloc[i], r_dir_view.iloc[i], r_strength_view.iloc[i]
        if pd.isna(u) or pd.isna(lo):
            continue
        alpha = max(0.15, min(0.6, float(s) * 0.7))
        if d >= 0:
            color = f"rgba(0,230,138,{alpha:.2f})"
            line_color = "rgba(0,230,138,0.8)"
        else:
            color = f"rgba(255,82,116,{alpha:.2f})"
            line_color = "rgba(255,82,116,0.8)"
        ribbon_upper_data.append({"time": ts, "value": round(float(u), 2), "color": color, "lineColor": line_color})
        ribbon_lower_data.append({"time": ts, "value": round(float(lo), 2), "color": color, "lineColor": line_color})

    ribbon_center_data = series_to_json(ribbon_center, df_view.index)
    vol_profile = build_volume_profile(df_view)

    # --- Build payload ---
    payload = {
        "ticker_name": ticker_name,
        "candles": candles,
        "supertrend_up": st_up,
        "supertrend_down": st_down,
        "volumes": volumes,
        "markers": markers,
        "trades": trades,
        "summary": summary,
        "equity_curve": equity_curve,
        "buy_hold_equity_curve": buy_hold_equity_curve,
        **smas,
        "sma_50w": sma_50w,
        "sma_100w": sma_100w,
        "sma_200w": sma_200w,
        "strategies": {
            "ribbon": {
                "trades": ribbon_trades,
                "summary": ribbon_summary,
                "equity_curve": ribbon_equity_curve,
                "buy_hold_equity_curve": ribbon_hold_equity_curve or buy_hold_equity_curve,
            },
            "ma_confirm": {"trades": ma_conf_trades, "summary": ma_conf_summary, "equity_curve": ma_conf_equity_curve},
            "supertrend": {"trades": trades, "summary": summary, "equity_curve": equity_curve},
            "ema_crossover": {"trades": ema_trades, "summary": ema_summary, "equity_curve": ema_equity_curve},
            "macd": {"trades": macd_trades, "summary": macd_summary, "equity_curve": macd_equity_curve},
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
            "ribbon": {"upper": ribbon_upper_data, "lower": ribbon_lower_data, "center": ribbon_center_data},
        },
        "vol_profile": vol_profile,
        "trend_flips": {"daily": daily_flips, "weekly": weekly_flips},
    }
    mark_phase("payload_ms")
    _cache_set(chart_cache_key, payload, ttl=_CHART_CACHE_TTL)
    current_app.logger.info(
        "chart_data timings ticker=%s interval=%s range=%s..%s rows=%s view_rows=%s indicator_bundle_hit=%s weekly_bundle_hit=%s metadata_ms=%s fetch_ms=%s frame_ms=%s indicators_ms=%s daily_flips_ms=%s weekly_ms=%s support_resistance_ms=%s payload_ms=%s total_ms=%s",
        ticker,
        interval,
        start,
        end or "latest",
        len(df),
        len(df_view),
        indicator_bundle_hit,
        weekly_bundle_hit,
        timings_ms.get("metadata_ms", 0),
        timings_ms.get("fetch_ms", 0),
        timings_ms.get("frame_ms", 0),
        timings_ms.get("indicators_ms", 0),
        timings_ms.get("daily_flips_ms", 0),
        timings_ms.get("weekly_ms", 0),
        timings_ms.get("support_resistance_ms", 0),
        timings_ms.get("payload_ms", 0),
        _elapsed_ms(request_started_at),
    )
    return jsonify(payload)
