#!/usr/bin/env python3
"""Seed Polymarket probability history from CLOB price-history API."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.polymarket import seed_probability_history


def main():
    print("=== Seeding Polymarket Probability History ===\n")
    df = seed_probability_history()
    if df.empty:
        print("No historical data retrieved. Exiting.")
        return

    print(f"Generated {len(df)} daily snapshots")
    print(f"Skew ratio range: {df['skew_ratio'].min():.4f} - {df['skew_ratio'].max():.4f}")
    print(f"Mean skew: {df['skew_ratio'].mean():.4f}")

    print("\nRecent snapshots:")
    for date, row in df.tail(10).iterrows():
        signal = "LONG" if row["skew_ratio"] > 1.2 else ("FLAT" if row["skew_ratio"] < 0.8 else "NEUTRAL")
        spot = f"${row['spot_price']:>9,.0f}" if row.get("spot_price") else "      N/A"
        total_markets = int(row.get("total_markets", 0))
        print(
            f"  {date.strftime('%Y-%m-%d')} | BTC={spot} | "
            f"skew={row['skew_ratio']:6.4f} | "
            f"bull={row['bull_probability']:.4f} | "
            f"bear={row['bear_probability']:.4f} | "
            f"{total_markets:>2} mkts | {signal}"
        )


if __name__ == "__main__":
    main()
