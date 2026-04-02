#!/usr/bin/env python3
"""Pre-warm the disk cache for all watchlist tickers back to 2015.

Fetches each ticker one at a time with a delay between calls to avoid
Yahoo Finance rate limiting.
"""
import json
import os
import time
import sys

# Bootstrap app imports
sys.path.insert(0, os.path.dirname(__file__))
from app import cached_download, normalize_ticker, load_watchlist

WATCHLIST = load_watchlist()
START = "2015-01-01"
DELAY = 2.0  # seconds between fetches

print(f"Pre-warming cache for {len(WATCHLIST)} tickers back to {START}")
print(f"Delay between fetches: {DELAY}s\n")

for i, ticker in enumerate(WATCHLIST, 1):
    yf_ticker = normalize_ticker(ticker)
    print(f"[{i}/{len(WATCHLIST)}] {ticker} ({yf_ticker})...", end=" ", flush=True)
    try:
        for interval in ["1d", "1wk"]:
            df = cached_download(yf_ticker, start=START, interval=interval, progress=False, threads=False)
            rows = len(df) if df is not None else 0
            print(f"{interval}:{rows}rows", end=" ", flush=True)
            time.sleep(DELAY)
        print("OK")
    except Exception as e:
        print(f"ERROR: {e}")
    time.sleep(DELAY)

print("\nDone! All tickers cached.")
