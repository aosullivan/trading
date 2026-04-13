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
- `approved_policy`: the currently approved promotion contract
  - `min_tickers_improved`: the 5-of-7 promotion gate
  - `base_drawdown_regression_limit_pct`: the starting allowed per-ticker drawdown slippage
  - `moderate_overshoot_limit_pct`: how much overshoot still counts as a moderate blocker
  - `max_moderate_violations`: how many moderate blockers are tolerated
  - `max_severe_violations`: how many severe blockers are tolerated
  - `buy_hold_gap_regression_limit_pct`: allowed per-ticker buy-and-hold-relative slippage before the ratchet fails

## Why This Is A Ratchet

This guard is stricter than a single-ticker "beat HODL" test:

- it measures the same seven names every time instead of cherry-picking the one symbol that likes a change
- it requires the basket-average score to stay at or above the promoted floor
- it requires at least 5 of 7 tickers to match or improve their promoted score
- it still blocks major per-ticker regressions in drawdown and buy-and-hold-relative performance even if the basket average still looks okay
- it now distinguishes moderate drawdown drift from severe drawdown drift instead of treating every overshoot as the same kind of veto

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

## Latest Promotion Decision

The latest formal promotion decision evaluated `tsla_donchian_keltner_70_30_v1` on the same frozen basket under the approved policy `tiered_drawdown_v1`.

Outcome:

- it improved score on `6 of 7` tickers
- its aggregate candidate score was about `199.70` versus the promoted floor `-479.94`
- it had moderate drawdown blockers on `BTC-USD`, `AAPL`, and `NVDA`
- it still had one severe drawdown blocker on `ETH-USD`
- it also introduced a buy-and-hold gap violation on `TSLA`
- the approved policy still blocks promotion because severe blockers and buy-and-hold gap violations remain disallowed

So the ratchet outcome is currently:

- approved policy: `tiered_drawdown_v1`
- strongest comparison candidate: `tsla_donchian_keltner_70_30_v1`
- promoted floor still retained: `corpus_trend`
- current weekly-core/daily-overlay hardening line is exhausted under the fixed contract

That is exactly the kind of distinction this benchmark is meant to protect: a candidate can narrow one class of failure materially and still fail the approved floor contract because it simply shifts the regression into another disallowed dimension.

## Alternative Architecture Search

After the weekly-core/daily-overlay line was exhausted, the repo ran a v1.5 architecture scan across the currently supported built-in families on the same frozen basket.

That scan did **not** produce a promotion-ready successor yet, but it did narrow the next branch cleanly:

- best new alternative-family continuation candidate: `bb_breakout`
- family read: volatility-band breakout
- current blocker story:
  - buy-and-hold gap violation on `COIN`
  - severe drawdown blockers on `ETH-USD`, `COIN`, and `GOOG`

So the benchmark posture is now more specific:

- overall promoted baseline remains `corpus_trend`
- strongest historical non-promoted comparison candidate remains `tsla_donchian_keltner_70_30_v1`
- strongest new alternative-family continuation lead is `bb_breakout`

## Breakout Family Final Reduction

After `bb_breakout` and then `coin_goog_keltner_v1` narrowed the alternative-family search, the repo ran one final breakout-family reduction pass in v1.7.

That pass also did **not** produce a promotion-ready successor, but it finished the branch cleanly:

- strongest final breakout-family candidate: `coin_goog_keltner_coin_esc50_v1`
- basket read:
  - aggregate candidate score: `319.36`
  - improved tickers: `6 of 7`
  - buy-and-hold gap violation: `COIN`
  - moderate drawdown blockers: `NVDA`, `GOOG`
  - severe drawdown blocker: `ETH-USD`

The decisive result is what happened when the repo tried to remove the final `ETH-USD` severe blocker inside the same family:

- a same-family `ETH-USD` confirmation probe did remove the severe drawdown label
- but it also turned `ETH-USD` into a buy-and-hold-gap violation and pushed aggregate score below `0`
- the combined `COIN` + `ETH-USD` probe cleared the severe set entirely, but still failed badly on participation and score

So the benchmark posture is now:

- approved policy still fixed at `tiered_drawdown_v1`
- promoted baseline still retained at `corpus_trend`
- breakout-family line exhausted under the fixed contract
