#!/usr/bin/env python3
"""Seed Polymarket probability history from CLOB price-history API.

This script fetches historical probability data for BTC price markets
from Polymarket's CLOB API and builds a time series that can be used
for backtesting the Polymarket Signal strategy.

Usage:
    python scripts/seed_polymarket_history.py

The script:
1. Fetches current BTC price markets from Polymarket
2. For key strike markets, pulls their probability history from CLOB
3. Computes daily skew ratios from the historical probabilities
4. Saves the result as probability_history.json for backtesting
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import pandas as pd

from lib.polymarket import (
    _CLOB_BASE,
    _POLYMARKET_DISK_CACHE_DIR,
    fetch_btc_price_markets,
    build_implied_distribution,
)


def fetch_token_price_history(token_id, interval="max", fidelity=1440):
    """Fetch full price history for a CLOB token.

    Returns list of {"t": unix_ts, "p": probability}.
    Uses max interval and daily fidelity for longest history.
    """
    try:
        resp = requests.get(
            f"{_CLOB_BASE}/prices-history",
            params={
                "market": token_id,
                "interval": interval,
                "fidelity": fidelity,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("history", [])
    except Exception as e:
        print(f"  Error fetching history for {token_id[:20]}...: {e}")
        return []


def main():
    print("=== Seeding Polymarket Probability History ===\n")

    # Fetch current markets
    print("Fetching BTC price markets...")
    from lib.cache import _cache
    _cache.clear()
    markets = fetch_btc_price_markets()
    print(f"Found {len(markets)} markets\n")

    # Focus on markets with clob token IDs and meaningful volume
    markets_with_tokens = [
        m for m in markets
        if m["clob_token_ids"] and m["volume"] and m["volume"] > 1000
        and m["strike_price"] and m["strike_price"] >= 1000
    ]
    print(f"Markets with CLOB tokens and volume > $1k: {len(markets_with_tokens)}\n")

    # Fetch history for each market's YES token
    all_histories = {}
    for i, m in enumerate(markets_with_tokens):
        token_id = m["clob_token_ids"][0]  # YES token
        label = f"{m['direction']}_{m['strike_price']:.0f}"
        print(f"  [{i+1}/{len(markets_with_tokens)}] {m['question'][:60]}...")

        history = fetch_token_price_history(token_id)
        if history:
            all_histories[label] = {
                "question": m["question"],
                "strike": m["strike_price"],
                "direction": m["direction"],
                "volume": m["volume"],
                "history": history,
            }
            print(f"    -> {len(history)} data points")
        else:
            print(f"    -> no history available")

        time.sleep(0.5)  # Rate limiting

    if not all_histories:
        print("\nNo historical data retrieved. Exiting.")
        return

    # Build daily skew ratio time series
    print(f"\n=== Building daily skew time series ===\n")

    # Collect all dates across all markets
    all_dates = set()
    for key, data in all_histories.items():
        for point in data["history"]:
            date = pd.Timestamp(point["t"], unit="s").normalize()
            all_dates.add(date)

    all_dates = sorted(all_dates)
    print(f"Date range: {all_dates[0].date()} to {all_dates[-1].date()} ({len(all_dates)} days)")

    # Prefetch BTC-USD spot prices for the date range
    print("Prefetching BTC-USD spot prices from Yahoo Finance...")
    from lib.data_fetching import cached_download
    start_str = all_dates[0].strftime("%Y-%m-%d")
    end_str = all_dates[-1].strftime("%Y-%m-%d")
    btc_df = cached_download("BTC-USD", interval="1d", start=start_str, end=end_str)
    spot_prices = {}
    if btc_df is not None and not btc_df.empty:
        for dt, row in btc_df.iterrows():
            spot_prices[dt.normalize()] = round(float(row["Close"]), 2)
        print(f"Got {len(spot_prices)} daily BTC prices")
    else:
        print("WARNING: Could not fetch BTC prices")

    # For each date, compute the skew ratio
    daily_snapshots = []
    for date in all_dates:
        date_ts = date.timestamp()

        upside_probs = []
        downside_probs = []
        strikes_snapshot = []

        for key, data in all_histories.items():
            # Find the closest data point to this date
            closest = None
            for point in data["history"]:
                pt = pd.Timestamp(point["t"], unit="s").normalize()
                if pt <= date:
                    closest = point
                elif closest is not None:
                    break

            if closest is None:
                continue

            prob = closest["p"]
            vol = data["volume"]

            strikes_snapshot.append({
                "strike": data["strike"],
                "direction": data["direction"],
                "probability": round(prob, 4),
                "volume": vol,
            })

            if data["direction"] == "above":
                upside_probs.append((prob, vol))
            else:
                downside_probs.append((prob, vol))

        if not upside_probs and not downside_probs:
            continue

        # Volume-weighted averages
        total_up_vol = sum(v for _, v in upside_probs) or 1
        total_down_vol = sum(v for _, v in downside_probs) or 1

        bull_prob = sum(p * v / total_up_vol for p, v in upside_probs) if upside_probs else 0
        bear_prob = sum(p * v / total_down_vol for p, v in downside_probs) if downside_probs else 0

        skew = bull_prob / bear_prob if bear_prob > 0 else float("inf")
        if skew == float("inf"):
            skew = 10.0  # Cap at 10

        # Look up spot price (try exact date, then previous trading day)
        spot = spot_prices.get(date)
        if spot is None:
            for offset in range(1, 5):
                spot = spot_prices.get(date - pd.Timedelta(days=offset))
                if spot is not None:
                    break

        daily_snapshots.append({
            "timestamp": date_ts,
            "date": date.strftime("%Y-%m-%d"),
            "spot_price": spot,
            "skew_ratio": round(skew, 4),
            "bull_probability": round(bull_prob, 4),
            "bear_probability": round(bear_prob, 4),
            "upside_count": len(upside_probs),
            "downside_count": len(downside_probs),
            "total_markets": len(strikes_snapshot),
            "strikes": strikes_snapshot,
        })

    print(f"Generated {len(daily_snapshots)} daily snapshots\n")

    # Save to disk
    history_file = os.path.join(_POLYMARKET_DISK_CACHE_DIR, "probability_history.json")
    os.makedirs(_POLYMARKET_DISK_CACHE_DIR, exist_ok=True)

    with open(history_file, "w") as f:
        json.dump(daily_snapshots, f, indent=2)

    print(f"Saved to {history_file}")

    # Print summary
    if daily_snapshots:
        skews = [s["skew_ratio"] for s in daily_snapshots]
        print(f"\nSkew ratio range: {min(skews):.4f} - {max(skews):.4f}")
        print(f"Mean skew: {sum(skews)/len(skews):.4f}")

        # Show a sample
        print("\nRecent snapshots:")
        for s in daily_snapshots[-10:]:
            signal = "LONG" if s["skew_ratio"] > 1.2 else ("FLAT" if s["skew_ratio"] < 0.8 else "NEUTRAL")
            spot = f"${s['spot_price']:>9,.0f}" if s.get("spot_price") else "      N/A"
            n_mkts = s.get("total_markets", "?")
            print(f"  {s['date']} | BTC={spot} | skew={s['skew_ratio']:6.4f} | bull={s['bull_probability']:.4f} | bear={s['bear_probability']:.4f} | {n_mkts:>2} mkts | {signal}")


if __name__ == "__main__":
    main()
