from datetime import timedelta

from flask import Blueprint, request, jsonify
import pandas as pd

from lib.settings import DAILY_WARMUP_DAYS, WEEKLY_WARMUP_DAYS
from lib.cache import (
    _cache_get,
    _cache_set,
    _get_cached_ticker_info,
    _CHART_CACHE_TTL,
)
from lib.data_fetching import (
    cached_download,
    normalize_ticker,
    is_treasury_yield_ticker,
    _TREASURY_YIELD_SERIES,
    _fetch_treasury_yield_history,
)
from lib.technical_indicators import (
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
from lib.backtesting import backtest_direction, backtest_supertrend
from lib.chart_serialization import (
    build_volume_profile,
    compute_all_trend_flips,
    last_trend_flip,
    series_to_json,
)
from lib.support_resistance import compute_support_resistance

bp = Blueprint("chart", __name__)


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
    if len(view_index) == 0:
        return False
    first_visible_loc = full_index.get_loc(view_index[0])
    if first_visible_loc == 0:
        return False
    return direction.iloc[first_visible_loc - 1] == 1


# ---------------------------------------------------------------------------
# Chart API route
# ---------------------------------------------------------------------------

@bp.route("/api/chart")
def chart_data():
    ticker = normalize_ticker(request.args.get("ticker", "TSLA"))
    interval = request.args.get("interval", "1d")
    source_interval = _source_interval(interval)
    start = request.args.get("start", "2015-01-01")
    end = request.args.get("end", "")
    period_val = int(request.args.get("period", 10))
    multiplier_val = float(request.args.get("multiplier", 3))
    chart_cache_key = (
        f"chart:{ticker}:{interval}:{start}:{end}:{period_val}:{multiplier_val}"
    )
    cached_chart = _cache_get(chart_cache_key)
    if cached_chart is not None:
        return jsonify(cached_chart)

    # Fetch full name for display
    ticker_name = ""
    if is_treasury_yield_ticker(ticker):
        ticker_name = _TREASURY_YIELD_SERIES[ticker]["name"]
    else:
        try:
            info = _get_cached_ticker_info(ticker)
            ticker_name = info.get("shortName") or info.get("longName") or ""
        except Exception:
            pass

    try:
        warmup_start = _warmup_start(start, interval)
        if is_treasury_yield_ticker(ticker):
            source_df = _fetch_treasury_yield_history(ticker, start=warmup_start, end=end or None)
        else:
            kwargs = {
                "start": warmup_start,
                "interval": source_interval,
                "progress": False,
            }
            if end:
                kwargs["end"] = end
            source_df = cached_download(ticker, **kwargs)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if source_df.empty:
        return jsonify({"error": f"No data for {ticker}"}), 400

    if isinstance(source_df.columns, pd.MultiIndex):
        source_df.columns = source_df.columns.get_level_values(0)

    source_df = source_df[~source_df.index.duplicated(keep="last")]
    if is_treasury_yield_ticker(ticker):
        df = _derive_treasury_chart_frame(source_df, interval)
    else:
        df = _derive_chart_frame(source_df, interval)

    view_mask = _visible_mask(df.index, start, end)
    df_view = df.loc[view_mask].copy()
    if df_view.index.duplicated().any():
        df_view = df_view[~df_view.index.duplicated(keep="last")]
    if df_view.empty:
        return jsonify({"error": f"No data for {ticker} in selected range"}), 400

    # --- Compute all indicators ---
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

    ribbon_center, ribbon_upper, ribbon_lower, ribbon_strength, ribbon_dir = compute_trend_ribbon(df)

    # --- Daily flips ---
    if interval == "1d":
        daily_flips = {}
        for key, dir_series in [
            ("supertrend", direction), ("ema_crossover", ema_direction),
            ("macd", macd_direction), ("ma_confirm", ma_conf_direction),
            ("donchian", donch_direction), ("adx_trend", adx_direction),
            ("bb_breakout", bb_direction), ("keltner", kelt_direction),
            ("parabolic_sar", psar_direction), ("cci_trend", cci_direction),
            ("regime_router", rr_direction),
            ("ribbon", ribbon_dir.where(ribbon_dir != 0, 1)),
        ]:
            date, d = last_trend_flip(dir_series)
            daily_flips[key] = {"date": date, "dir": d}
    else:
        try:
            if is_treasury_yield_ticker(ticker):
                df_d = _fetch_treasury_yield_history(
                    ticker,
                    start=_warmup_start(start, "1d"),
                    end=end or None,
                )
            else:
                kwargs_d = {"start": _warmup_start(start, "1d"), "interval": "1d", "progress": False}
                if end:
                    kwargs_d["end"] = end
                df_d = cached_download(ticker, **kwargs_d)
            if isinstance(df_d.columns, pd.MultiIndex):
                df_d.columns = df_d.columns.get_level_values(0)
            if df_d.index.duplicated().any():
                df_d = df_d[~df_d.index.duplicated(keep="last")]
            daily_flips = compute_all_trend_flips(
                df_d, period_val=period_val, multiplier_val=multiplier_val
            )
        except Exception:
            daily_flips = {}

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
        else:
            st_down.append({"time": ts, "value": val, "mid": body_mid})

    # --- Supertrend backtest ---
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

    # --- SMAs ---
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

    # --- Weekly SMAs and flips ---
    sma_50w = []
    sma_200w = []
    weekly_flips = {}
    try:
        if is_treasury_yield_ticker(ticker):
            df_w = _derive_treasury_chart_frame(
                _fetch_treasury_yield_history(
                    ticker,
                    start=_warmup_start(start, "1wk"),
                    end=end or None,
                ),
                "1wk",
            )
        elif source_interval == "1wk":
            df_w = source_df.copy()
        else:
            kwargs_w = {"start": _warmup_start(start, "1wk"), "interval": "1wk", "progress": False}
            if end:
                kwargs_w["end"] = end
            df_w = cached_download(ticker, **kwargs_w)
        if not df_w.empty:
            if isinstance(df_w.columns, pd.MultiIndex):
                df_w.columns = df_w.columns.get_level_values(0)
            if df_w.index.duplicated().any():
                df_w = df_w[~df_w.index.duplicated(keep="last")]
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
            if interval == "1wk":
                for key, dir_series in [
                    ("supertrend", direction), ("ema_crossover", ema_direction),
                    ("macd", macd_direction), ("ma_confirm", ma_conf_direction),
                    ("donchian", donch_direction), ("adx_trend", adx_direction),
                    ("bb_breakout", bb_direction), ("keltner", kelt_direction),
                    ("parabolic_sar", psar_direction), ("cci_trend", cci_direction),
                    ("regime_router", rr_direction),
                    ("ribbon", ribbon_dir.where(ribbon_dir != 0, 1)),
                ]:
                    date, d = last_trend_flip(dir_series)
                    weekly_flips[key] = {"date": date, "dir": d}
            else:
                weekly_flips = compute_all_trend_flips(
                    df_w, period_val=period_val, multiplier_val=multiplier_val
                )
    except Exception:
        pass

    # --- Support / Resistance levels ---
    sr_levels = compute_support_resistance(df, max_levels=20)

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
            "ribbon": {"upper": ribbon_upper_data, "lower": ribbon_lower_data, "center": ribbon_center_data},
        },
        "vol_profile": vol_profile,
        "trend_flips": {"daily": daily_flips, "weekly": weekly_flips},
    }
    _cache_set(chart_cache_key, payload, ttl=_CHART_CACHE_TTL)
    return jsonify(payload)
