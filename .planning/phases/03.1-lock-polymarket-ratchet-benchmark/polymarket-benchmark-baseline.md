# Polymarket benchmark baseline

## Promoted result

This inserted phase locks the improved BTC Polymarket strategy behavior as the current ratchet floor.

## Benchmark contract

- Ticker: `BTC-USD`
- Route: `/api/chart`
- Chart request window: `2025-08-08` to `2026-04-08`
- Frozen Polymarket history coverage: `2025-11-25` to `2026-04-08`
- Strategy path: `relevance-weighted`
- OHLCV fixture: `tests/fixtures/btc_usd_polymarket_1d_benchmark.csv`
- Probability-history fixture: `tests/fixtures/polymarket_probability_history_benchmark.json`
- Spec file: `tests/fixtures/polymarket_benchmark_backtests.json`

## Pinned floor

| Metric | Value |
|--------|-------|
| ending_equity | `9494.0` |
| total_pnl | `-505.99` |
| net_profit_pct | `-5.06` |
| max_drawdown_pct | `8.89` |
| total_trades | `3` |

## Why this matters

The benchmark preserves the current improvement where Polymarket strikes are weighted by relevance to current BTC spot. That keeps the strategy from drifting back toward the older raw aggregate skew behavior while Phase 4 and Phase 5 continue broader strategy work.
