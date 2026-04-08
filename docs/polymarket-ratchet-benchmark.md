# Polymarket ratchet benchmark

This benchmark protects the improved BTC Polymarket strategy from quietly getting worse again.

## Scope

- Ticker: `BTC-USD`
- Route under test: `/api/chart`
- Strategy key: `polymarket`
- Chart request window: `2025-08-08` to `2026-04-08`
- Frozen Polymarket history coverage: `2025-11-25` to `2026-04-08`

This setup is intentional. The route request still starts at `2025-08-08` so the visible chart window stays stable, but the committed Polymarket history fixture currently begins at `2025-11-25`. The strategy is therefore flat before the first saved Polymarket snapshot, and the ratchet benchmark freezes that real behavior instead of pretending earlier signal history exists.

## What is frozen

- OHLCV fixture: `tests/fixtures/btc_usd_polymarket_1d_benchmark.csv`
- Polymarket history fixture: `tests/fixtures/polymarket_probability_history_benchmark.json`
- Benchmark spec: `tests/fixtures/polymarket_benchmark_backtests.json`

The benchmark patches both the BTC OHLCV download path and the Polymarket history load path, so the route runs deterministically without depending on live Yahoo or live Polymarket responses.

## What is being protected

The benchmark protects the improved relevance-weighted Polymarket strategy path, not the older raw-skew-only behavior.

Pinned promoted floor:

- `ending_equity`: `9494.0`
- `total_pnl`: `-505.99`
- `net_profit_pct`: `-5.06`
- `max_drawdown_pct`: `8.89`
- `total_trades`: `3`

These numbers are not the final goal. They are the new floor after the relevance-weighted improvement. Future changes can improve on them, but should not slip below them silently.

## Regeneration

From the repo root:

```bash
python scripts/regen_polymarket_benchmark_fixtures.py
python scripts/regen_polymarket_benchmark_fixtures.py --check
```

After regeneration, rerun:

```bash
pytest -q tests/test_polymarket.py tests/test_polymarket_benchmark_backtests.py
```

If the new result is intentionally better and should become the new floor, update `tests/fixtures/polymarket_benchmark_backtests.json` and the baseline doc in the same change as the regenerated fixtures.
