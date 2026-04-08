# Focus-Basket Ratchet Benchmark

Phase 3 promotes one shared regression benchmark for `BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, and `GOOG`. The benchmark uses the live app contract, not a second scoring engine: every assertion goes through `GET /api/chart` and reads `strategies.corpus_trend` plus the same `buy_hold_equity_curve` the UI compares against.

## Spec

The machine-readable source of truth is [`tests/fixtures/focus_basket_benchmarks.json`](/Users/adrianosullivan/projects/trading/tests/fixtures/focus_basket_benchmarks.json).

It pins:

- `tickers`: the seven-ticker basket in fixed order
- `chart_request`: `interval=1d`, `start=2020-01-01`, `end=2026-04-04`, `period=10`, `multiplier=2.5`
- `strategy_key`: `corpus_trend`
- `score_formula`: `score = net_profit_pct - 0.35 * max_drawdown_pct - max(0, buy_hold_net_profit_pct - net_profit_pct)`
- `aggregate_score_floor`: the promoted basket-average score floor
- `min_tickers_improved`: the 5-of-7 promotion gate
- `max_drawdown_regression_limit_pct`: allowed per-ticker drawdown slippage before the ratchet fails
- `buy_hold_gap_regression_limit_pct`: allowed per-ticker buy-and-hold-relative slippage before the ratchet fails

## Why This Is A Ratchet

This guard is stricter than a single-ticker "beat HODL" test:

- it measures the same seven names every time instead of cherry-picking the one symbol that likes a change
- it requires the basket-average score to stay at or above the promoted floor
- it requires at least 5 of 7 tickers to match or improve their promoted score
- it blocks major per-ticker regressions in drawdown and buy-and-hold-relative performance even if the basket average still looks okay

That combination makes it suitable for strategy promotion: future changes only become the new baseline when they improve the agreed scorecard instead of shifting risk into one or two lucky tickers.

## Frozen Fixtures

The committed CSV fixtures live under [`tests/fixtures/focus_basket`](/Users/adrianosullivan/projects/trading/tests/fixtures/focus_basket). They are downloaded with the same warmup rule as `/api/chart`: `DAILY_WARMUP_DAYS` before the requested `start` date, with an exclusive-end download one day past the chart `end`.

Regenerate them from the repo root:

```bash
python scripts/regen_focus_basket_benchmark_fixtures.py
```

Validate the committed set without downloading anything:

```bash
python scripts/regen_focus_basket_benchmark_fixtures.py --check
```

## Regression Test

[`tests/test_focus_basket_benchmark_backtests.py`](/Users/adrianosullivan/projects/trading/tests/test_focus_basket_benchmark_backtests.py) patches `routes.chart.cached_download` to read only the frozen CSVs, then requests `/api/chart` once per basket ticker. The test computes:

- `net_profit_pct` from `strategies["corpus_trend"]["summary"]`
- `max_drawdown_pct` from the same summary
- `buy_hold_net_profit_pct` from `strategies["corpus_trend"]["buy_hold_equity_curve"]`
- `score` using `score = net_profit_pct - 0.35 * max_drawdown_pct - max(0, buy_hold_net_profit_pct - net_profit_pct)`

Promotion workflow:

1. Regenerate fixtures if the market window intentionally changes.
2. Run `pytest tests/test_focus_basket_benchmark_backtests.py`.
3. Update the pinned metrics in the JSON and the promoted baseline summary in `.planning/` only when you intentionally accept a stronger baseline.
