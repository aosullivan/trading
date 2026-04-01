#!/usr/bin/env python3
"""Generate backtest report data for all watchlist tickers.

Usage:
    python generate_report.py                          # default: 2024, 2025, YTD 2026
    python generate_report.py --years 2023 2024 2025   # custom years
    python generate_report.py --start 2022-06-01 --end 2023-06-01  # custom range
"""
import argparse
import json
import sys
import time
from datetime import date

import pandas as pd
import yfinance as yf

from app import STRATEGIES, backtest_direction, cached_download, load_watchlist


def build_periods(years=None, start=None, end=None):
    """Build period dict from args."""
    today = date.today().strftime("%Y-%m-%d")
    current_year = date.today().year

    if start and end:
        label = f"{start} to {end}"
        return {label: (start, end)}

    if years:
        year_list = [int(y) for y in years]
    else:
        year_list = [2024, 2025, 2026]

    periods = {}
    for y in year_list:
        if y == current_year:
            periods[f"YTD {y}"] = (f"{y}-01-01", today)
        else:
            periods[str(y)] = (f"{y}-01-01", f"{y}-12-31")
    return periods


def generate(periods):
    tickers = load_watchlist()
    if not tickers:
        print("Watchlist is empty!", file=sys.stderr)
        sys.exit(1)

    today = date.today().strftime("%Y-%m-%d")
    all_starts = [v[0] for v in periods.values()]
    earliest = min(all_starts)
    # Fetch 6 months before earliest for indicator warmup
    warmup_start = (pd.Timestamp(earliest) - pd.DateOffset(months=6)).strftime("%Y-%m-%d")

    results = {}
    total = len(tickers)
    for idx, ticker in enumerate(tickers, 1):
        sys.stderr.write(f"\r[{idx}/{total}] {ticker:<10}")
        sys.stderr.flush()
        if idx > 1:
            time.sleep(2)  # avoid Yahoo Finance rate limits
        try:
            df = cached_download(ticker, start=warmup_start, end=today, interval="1d", progress=False)
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
        except Exception:
            continue

        results[ticker] = {}
        for period_name, (p_start, p_end) in periods.items():
            mask = (df.index >= p_start) & (df.index <= p_end)
            df_period = df.loc[mask]
            if len(df_period) < 30:
                continue

            period_results = {}
            for strat_name, strat_fn in STRATEGIES.items():
                try:
                    direction = strat_fn(df_period)
                    trades, summary, _ec = backtest_direction(df_period, direction)
                    period_results[strat_name] = {
                        "summary": summary,
                        "trades": trades,
                    }
                except Exception:
                    continue
            results[ticker][period_name] = period_results

    sys.stderr.write("\n")

    output = {
        "generated": today,
        "tickers": tickers,
        "periods": list(periods.keys()),
        "strategies": list(STRATEGIES.keys()),
        "results": results,
    }

    with open("report_data.json", "w") as f:
        json.dump(output, f)

    n_tickers = len(results)
    n_strats = len(STRATEGIES)
    print(f"Done! {n_tickers} tickers x {n_strats} strategies x {len(periods)} periods")
    print(f"Saved to report_data.json ({len(open('report_data.json').read()) // 1024} KB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate backtest report")
    parser.add_argument("--years", nargs="+", help="Years to backtest (e.g. 2023 2024 2025)")
    parser.add_argument("--start", help="Custom start date (e.g. 2022-06-01)")
    parser.add_argument("--end", help="Custom end date (e.g. 2023-06-01)")
    args = parser.parse_args()

    periods = build_periods(years=args.years, start=args.start, end=args.end)
    print(f"Periods: {list(periods.keys())}")
    generate(periods)
