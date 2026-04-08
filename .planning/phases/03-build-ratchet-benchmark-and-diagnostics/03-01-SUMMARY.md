# 03-01 Summary

## Outcome

Wave 1 established the deterministic ratchet benchmark for the fixed focus basket: `BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, and `GOOG`.

Delivered artifacts:

- [`scripts/regen_focus_basket_benchmark_fixtures.py`](/Users/adrianosullivan/projects/trading/scripts/regen_focus_basket_benchmark_fixtures.py) regenerates or validates the frozen CSV fixture set
- [`tests/fixtures/focus_basket_benchmarks.json`](/Users/adrianosullivan/projects/trading/tests/fixtures/focus_basket_benchmarks.json) defines the basket, route request, ratchet rules, and promoted baseline metrics
- [`tests/test_focus_basket_benchmark_backtests.py`](/Users/adrianosullivan/projects/trading/tests/test_focus_basket_benchmark_backtests.py) enforces the baseline through `/api/chart`
- [`docs/focus-basket-ratchet-benchmark.md`](/Users/adrianosullivan/projects/trading/docs/focus-basket-ratchet-benchmark.md) documents the benchmark contract
- [`focus-basket-baseline.md`](/Users/adrianosullivan/projects/trading/.planning/phases/03-build-ratchet-benchmark-and-diagnostics/focus-basket-baseline.md) records the promoted metrics in human-readable form

## Promoted Baseline

- Aggregate score floor: `-479.94`
- Minimum tickers that must match or improve promoted score: `5 of 7`
- Drawdown regression limit: `5.0` percentage points
- Buy-and-hold gap regression limit: `10.0` percentage points

Notable baseline signal: the current `corpus_trend` implementation is profitable on most basket names, but it still trails buy-and-hold badly on `BTC-USD`, `ETH-USD`, `TSLA`, `AAPL`, `NVDA`, and `GOOG`. `COIN` is the only name where the promoted baseline currently beats buy-and-hold.

## Verification

- `python scripts/regen_focus_basket_benchmark_fixtures.py --check`
- `pytest -q tests/test_focus_basket_benchmark_backtests.py`
- `rg -n "BTC-USD|ETH-USD|COIN|TSLA|AAPL|NVDA|GOOG|aggregate_score_floor|min_tickers_improved|buy_hold_gap_regression_limit_pct" tests/fixtures/focus_basket_benchmarks.json docs/focus-basket-ratchet-benchmark.md .planning/phases/03-build-ratchet-benchmark-and-diagnostics/focus-basket-baseline.md`
