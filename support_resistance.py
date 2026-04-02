import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from scipy.stats import gaussian_kde


def body_extremes(df):
    """Return candle-body highs/lows, ignoring wick extremes."""
    opens = df["Open"].to_numpy(dtype=float)
    closes = df["Close"].to_numpy(dtype=float)
    return np.maximum(opens, closes), np.minimum(opens, closes)


def classify_level_type(level_price, current_price, zone_width, sup_bounces, res_bounces):
    """Classify a level relative to current price and recent bounce behavior."""
    if abs(level_price - current_price) <= zone_width:
        if len(sup_bounces) > len(res_bounces):
            return "support"
        if len(res_bounces) > len(sup_bounces):
            return "resistance"
        return "support" if level_price <= current_price else "resistance"
    return "support" if level_price < current_price else "resistance"


def compute_support_resistance(df, max_levels=8):
    """Detect support/resistance levels using KDE on candle-body swing pivots."""
    body_highs, body_lows = body_extremes(df)
    closes = df["Close"].values
    volumes = df["Volume"].values if "Volume" in df.columns else np.ones(len(df))
    timestamps = [int(t.timestamp()) for t in df.index]
    n = len(body_highs)
    if n < 30:
        return []

    current_price = float(closes[-1])

    body_range = pd.Series(body_highs - body_lows, index=df.index)
    atr_series = body_range.rolling(14).mean()
    atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0
    if atr == 0:
        atr = current_price * 0.02
    window = 3 if n < 400 else 5

    pivots = []
    pivot_details = []
    for i in range(window, n - window):
        if body_highs[i] == max(body_highs[i - window : i + window + 1]):
            pivots.append(body_highs[i])
            pivot_details.append((body_highs[i], i))
        if body_lows[i] == min(body_lows[i - window : i + window + 1]):
            pivots.append(body_lows[i])
            pivot_details.append((body_lows[i], i))

    if len(pivots) < 4:
        return []

    pivot_arr = np.array(pivots)
    kde = gaussian_kde(pivot_arr, bw_method=0.05)

    price_min, price_max = pivot_arr.min() * 0.95, pivot_arr.max() * 1.05
    grid = np.linspace(price_min, price_max, 500)
    density = kde(grid)

    peak_indices, _peak_props = find_peaks(density, height=density.max() * 0.05)
    if len(peak_indices) == 0:
        return []

    sr_prices = grid[peak_indices]

    zone_width = atr * 0.5
    levels = []
    avg_vol = float(np.mean(volumes)) if np.mean(volumes) > 0 else 1.0

    for level_price in sr_prices:
        sup_bounces = []
        res_bounces = []
        breaks = 0

        for i in range(1, n - 1):
            in_zone_low = abs(body_lows[i] - level_price) < zone_width
            in_zone_high = abs(body_highs[i] - level_price) < zone_width

            if not (in_zone_low or in_zone_high):
                continue

            if in_zone_low and closes[i] >= level_price - zone_width:
                next_reversed = closes[i + 1] >= closes[i] or body_lows[i + 1] > body_lows[i]
                if next_reversed:
                    sup_bounces.append(i)
                else:
                    breaks += 1

            if in_zone_high and closes[i] <= level_price + zone_width:
                next_reversed = closes[i + 1] <= closes[i] or body_highs[i + 1] < body_highs[i]
                if next_reversed:
                    res_bounces.append(i)
                else:
                    breaks += 1

        all_bounces = sorted(sup_bounces + res_bounces)
        n_bounces = len(all_bounces)
        if n_bounces < 2:
            continue

        level_type = classify_level_type(
            level_price, current_price, zone_width, sup_bounces, res_bounces
        )

        total_tests = n_bounces + breaks
        respect = n_bounces / total_tests if total_tests > 0 else 0
        if respect < 0.3:
            continue

        avg_recency = sum(b / n for b in all_bounces) / n_bounces
        vol_weight = sum(volumes[b] for b in all_bounces) / (n_bounces * avg_vol)
        vol_weight = min(vol_weight, 3.0)
        score = n_bounces * (0.3 + avg_recency) * vol_weight * respect

        pivot_bar_indices = sorted(
            [idx for p, idx in pivot_details if abs(p - level_price) < zone_width]
        )
        pivot_times = [timestamps[i] for i in pivot_bar_indices]
        bounce_times = sorted(set(timestamps[b] for b in all_bounces))

        levels.append(
            {
                "price": round(float(level_price), 2),
                "zone_low": round(float(level_price - zone_width), 2),
                "zone_high": round(float(level_price + zone_width), 2),
                "touches": n_bounces,
                "type": level_type,
                "touch_times": bounce_times,
                "pivot_times": pivot_times,
                "respect": round(respect, 2),
                "_score": score,
            }
        )

    levels.sort(key=lambda l: -l["_score"])
    for lv in levels:
        del lv["_score"]
    return levels[:max_levels]
