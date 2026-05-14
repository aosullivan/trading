# Backtesting Status

Last updated: 2026-04-26.

This is the durable overview for TriedingView backtesting. It replaces the
older split docs for strategy configuration, focus-basket benchmarks,
Polymarket benchmarks, portfolio backtesting, and portfolio campaigns. The
machine-readable ratchets still live in `tests/fixtures/`; this document
explains what they mean and what to do next.

## Current Read

TriedingView now has three connected backtesting surfaces:

- single-ticker chart and strategy evaluation through `/api/chart`
- portfolio-level backtesting through `/api/portfolio/backtest`
- saved portfolio campaigns for ranking many strategy, allocator, basket, and
  window combinations without rerunning everything by hand

The current retained single-ticker baseline is `cci_hysteresis` under the
`tiered_drawdown_v1` focus-basket promotion policy. The current product default
is still `ribbon`, because the chart and backtest UI default is a product
contract, not automatically the same thing as the promoted benchmark floor.

The current portfolio research posture is more cautious: portfolio campaigns,
allocator diagnostics, macro overlay tests, and synthetic-stress tests all
exist, but the latest macro-aware and synthetic-stress searches both closed
with explicit no-winner decisions. The strongest open direction is no longer
another single-ticker signal family. It is a position-level or sleeve-level
portfolio allocator that can use the already useful crash-guard signals to
de-risk more decisively without giving away too much upside.

Recent performance work added chart payload prewarming and disk-cache reuse for
known watchlist tickers. Warm ticker changes should feel close to instant, but
full cache baking across every ticker, interval, and strategy is expensive and
should be treated as an offline or carefully throttled operation.

## Source Of Truth

Use these files as the authoritative contract:

- `tests/fixtures/strategy_config_ratchet.json`: default strategy, selector
  order, money-management controls, and `/api/chart` strategy payload shape
- `tests/fixtures/focus_basket_benchmarks.json`: promoted single-ticker
  benchmark basket, score formula, and promotion gates
- `tests/fixtures/polymarket_benchmark_backtests.json`: BTC Polymarket route
  benchmark and relevance-weighted signal floor
- `tests/fixtures/portfolio_backtest_contract_ratchet.json`: portfolio route
  contract, supported portfolio strategies, allocators, baskets, diagnostics,
  and a deterministic expected response
- `tests/fixtures/portfolio_campaign_contract_ratchet.json`: campaign creation,
  scheduling, and progress defaults
- `tests/fixtures/portfolio_research_matrix_contract_ratchet.json`: canonical
  portfolio research-matrix shape
- `.planning/PROJECT.md`: local planning posture and latest milestone result
- `.planning/MILESTONES.md`: milestone history

Use this document for the human summary. Update the matching fixture and test
in the same change whenever a contract intentionally moves.

## Single-Ticker Surface

The chart page and `/backtest` page support a retained primary surface plus a
small experimental shelf.

Maintained product surface:

- `ribbon` - Trend-Driven
- `corpus_trend` - Corpus Trend (Donchian/ATR)
- `corpus_trend_layered` - Corpus Trend Layered
- `cci_hysteresis` - CCI Hysteresis (30/150/-40)
- `polymarket` - Polymarket Skew

Experimental shelf:

- `trend_sr_macro_v1` - Trend SR + Macro v1
- `weekly_core_overlay_v1` - Weekly Core + Daily Overlay
- `supertrend_i` - Supertrend-I
- `ema_9_26` - EMA 9/26 Cross
- `semis_persist_v1` - Semis Persist v1
- `bb_breakout` - BB Breakout (30/1.5)
- `ema_crossover` - EMA 5/20 Cross
- `cci_trend` - CCI Trend (30/80)

The current UI defaults are:

- default strategy: `ribbon`
- default ticker fixture for contract tests: `BTC-USD`
- default interval: `1d`
- Supertrend defaults: period `10`, multiplier `2.5`

Money-management controls currently expose:

- sizing: All-In, Vol-Normalised, Fixed Fraction
- stops: None, ATR Trail, percent Trail
- risk cap: None, 1 percent, 0.5 percent, 2 percent
- compounding: Per Trade, Monthly, Fixed

The strategy configuration ratchet exists to catch product drift: a changed
default, renamed option, reordered selector, missing strategy payload, or
frontend/backend mismatch should be deliberate and reviewed.

## Promoted Focus-Basket Benchmark

The main single-ticker strategy promotion benchmark uses the same `/api/chart`
route the app uses in the browser. It does not use a separate scoring engine.

Benchmark basket:

- `BTC-USD`
- `ETH-USD`
- `COIN`
- `TSLA`
- `AAPL`
- `NVDA`
- `GOOG`

Pinned request:

- interval: `1d`
- start: `2020-01-01`
- end: `2026-04-04`
- period: `10`
- multiplier: `2.5`
- promoted strategy key: `cci_hysteresis`

Score formula:

```text
score = net_profit_pct - 0.35 * max_drawdown_pct - max(0, buy_hold_net_profit_pct - net_profit_pct)
```

Current promoted read:

- approved policy: `tiered_drawdown_v1`
- promoted baseline: `cci_hysteresis`
- aggregate score floor: `311.52`
- improved tickers versus the previous floor: `7 of 7`
- buy-and-hold-gap violations: none
- moderate drawdown blockers: `ETH-USD`, `COIN`, `NVDA`
- severe drawdown blockers: none

The promotion gate requires the basket-average score to stay above the promoted
floor, at least five of seven tickers to match or improve, no severe drawdown
violations, no buy-and-hold gap regressions beyond policy limits, and no more
than three moderate drawdown violations.

Search history matters because several tempting branches were already
exhausted under this contract:

- weekly-core or daily-overlay hardening
- breakout-family hardening
- the current EMA confirmation line
- old route-supported CCI confirmation remixes

`weekly_core_overlay_v1` remains the strongest known failing comparison under
the current floor. New single-ticker research should start from the
`cci_hysteresis` floor and avoid reopening older exhausted branches unless the
contract itself changes.

## Polymarket Benchmark

The Polymarket benchmark protects the improved relevance-weighted BTC signal
path, not the older raw-skew-only behavior.

Scope:

- ticker: `BTC-USD`
- route under test: `/api/chart`
- strategy key: `polymarket`
- chart request window: `2025-08-08` through `2026-04-08`
- frozen Polymarket history: `2025-11-25` through `2026-04-08`

Pinned promoted floor:

- ending equity: `9494.0`
- total P&L: `-505.99`
- net profit: `-5.06%`
- max drawdown: `8.89%`
- total trades: `3`

Those numbers are not an aspirational target. They are a guardrail so the
relevance-weighted signal does not quietly regress while the rest of the app
changes.

## Portfolio Backtesting Surface

The `/portfolio` page and `/api/portfolio/backtest` route run retained
strategies across a basket with shared capital and compare the result against
equal-weight portfolio buy-and-hold on the same tickers and date window.

Supported portfolio strategies:

- `ribbon`
- `corpus_trend`
- `cci_hysteresis`
- `monthly_breadth_guard_v1`
- `monthly_breadth_guard_ladder_v1`

The first three align with retained single-ticker strategies. The monthly
breadth guard variants are portfolio-only regime filters. They are slow
month-end basket filters that try to avoid broad risk-off periods and keep
capital in the strongest names when risk is on. The ladder variant can start a
limited recovery re-entry after deep drawdowns before full trend recovery.

Supported allocator policies:

- `signal_flip_v1`: new exposure only comes from fresh bullish flips
- `signal_equal_weight_redeploy_v1`: freed capital can redeploy into currently
  bullish unheld names with equal cash budgets
- `signal_top_n_strength_v1`: freed capital is limited to the strongest
  currently bullish names
- `core_plus_rotation_v1`: broad core sleeve plus tactical overweight to the
  strongest currently bullish name

Supported basket sources:

- `watchlist`
- `manual`
- `preset`

Preset baskets:

- `focus` / `focus_7`: `BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`,
  `GOOG`
- `growth_5`: `AAPL`, `MSFT`, `NVDA`, `AMZN`, `META`
- `diversified_10`: `AAPL`, `MSFT`, `GOOG`, `AMZN`, `META`, `NVDA`, `JPM`,
  `XOM`, `COST`, `UNH`

The route response includes:

- selected strategy and config
- basket metadata and basket diagnostics
- strategy versus buy-and-hold comparison
- portfolio diagnostics
- order ledger
- included and skipped tickers
- portfolio strategy equity curve
- portfolio buy-and-hold curve
- portfolio summary
- per-ticker diagnostics
- heat series

Important comparison metrics:

- strategy return and ending equity
- buy-and-hold return and ending equity
- max drawdown and drawdown gap
- upside capture
- equity and return gap
- winner: `strategy`, `buy_hold`, or `tie`

Important allocator diagnostics:

- average invested and cash percentage
- average and maximum active positions
- maximum single-name weight
- average top-three weight
- turnover
- redeployment opportunities and events
- average redeployment lag
- unfilled redeployment opportunities

The current portfolio route contract test uses mocked data and mocked signals
so the response shape stays offline-safe and stable.

## Campaigns And Discovery

Portfolio campaigns make backtesting a planned batch process instead of a pile
of ad hoc requests.

Each campaign stores:

- name, goal, notes, and tags
- one or more run specs
- schedule definition
- run status
- latest lightweight summary for each completed run

Run specs store the replayable inputs:

- strategy
- allocator policy
- basket source and basket definition
- start and end dates
- heat limit
- money-management configuration
- optional research-matrix basket and regime labels

Run states:

- `planned`
- `queued`
- `running`
- `completed`
- `failed`
- `skipped`

Schedule modes:

- manual
- hourly
- weekly

Campaign comparison is read-only and uses saved completed-run results. It does
not fetch fresh market data or rerun portfolio backtests. Ranking currently
supports gap versus buy-and-hold, return, return over drawdown, and lowest
drawdown.

The canonical research matrix is:

- strategies: `ribbon`, `corpus_trend`, `cci_hysteresis`
- allocator policies: `signal_flip_v1`, `signal_equal_weight_redeploy_v1`,
  `signal_top_n_strength_v1`, `core_plus_rotation_v1`
- baskets: `focus_7`, `growth_5`, `diversified_10`
- windows: `crash_recovery_2020_2021`, `drawdown_chop_2022`,
  `bull_recovery_2023_2025`

Campaigns are stored locally under
`TRIEDINGVIEW_USER_DATA_DIR/portfolio_campaigns/`.

## Macro And Synthetic-Stress Research

The portfolio research program moved beyond single-ticker signals into
allocator and regime work.

Milestone `v1.18` added allocator diagnostics and canonical portfolio rotation
research. It closed with an explicit no-winner decision after the full matrix.

Milestone `v1.19` tested macro-aware regime overlays. The strongest balanced
near-miss was:

```text
ribbon + signal_top_n_strength_v1 + macro63_high_core
```

The closest raw-return near-miss was:

```text
ribbon + signal_top_n_strength_v1 + macro63_very_high_core
```

The milestone still closed with no winner against the buy-and-hold contract.

Milestone `v1.20` added deterministic synthetic-stress modeling and upside
retention analysis. The synthetic tests showed that benchmark-aware crash-guard
signals detect modeled hostile conditions earlier and improve downside metrics
somewhat, but not enough to clear the downside-protection plus upside-retention
contract.

Key v1.20 reads:

- best raw downside saver: old `v1.18` tactical baseline
- strongest macro stress compromise:
  `ribbon + signal_top_n_strength_v1 + macro63_crash_guard_balanced`
- best upside-retention profile:
  `ribbon + signal_top_n_strength_v1 + macro63_very_high_core`
- final result: no promoted winner

Interpretation:

- synthetic-stress modeling is worth keeping
- benchmark-aware crash-guard features are useful signals
- the blended overlay architecture is probably the limiter
- the next serious candidate should be a position-level or sleeve-level
  allocator that can actually cut exposure after detection

## Performance And Caching Status

The app only has roughly 50 known tickers, and historical prices are immutable
after each trading day. That makes caching the correct architectural direction.

Current state:

- yfinance download cache protects raw OHLCV fetches
- `/api/chart` has payload caching for candle and strategy responses
- strategy shared-cache reuse lets plain strategy requests reuse computed
  shared artifacts
- `lib/chart_prewarmer.py` can prewarm watchlist chart artifacts by calling the
  same `/api/chart` route paths the browser uses
- `app.py --build-chart-cache` builds watchlist artifacts before starting the
  server
- `app.py --build-chart-cache-only` builds them and exits
- the background prewarmer waits after startup and yields between requests
- the Flask dev server runs threaded so prewarming does not queue behind user
  requests

The intended user experience is:

- candles should paint immediately from a candles-only response
- the selected strategy or overlay should hydrate from cache when warm
- cold, never-seen tickers may still be slower
- full all-ticker/all-strategy cache building is allowed to take time if it is
  explicit and offline

Recommended performance direction:

- prefer stale-while-revalidate for known ticker/day combinations
- key cached artifacts by ticker, interval, start/end, strategy, strategy
  params, and last available market date
- preserve immutable historical indicator windows and append only the newest
  bar when a new day arrives
- keep heavy campaign or full-cache builds out of the interactive request path
- expose cache status in the UI so slow loads are explainable

## Recommendations

1. Make warm ticker switching the hard product standard.

   For any ticker already in the watchlist or known universe, loading should be
   limited by local cache read plus chart rendering. The app should not perform
   fresh multi-strategy backtesting on the critical path unless the cache is
   missing or stale for the latest market date.

2. Separate chart rendering from strategy research.

   The chart route should always be able to return candles first. Strategy
   payloads can arrive independently, with cached selected strategy first and
   non-selected strategies treated as background research data.

3. Build a real artifact store for computed strategy outputs.

   The current cache is directionally right. The next level is a versioned
   artifact model:

   - raw OHLCV bars
   - indicators
   - signal series
   - backtest trades and metrics
   - chart payload fragments

   Historical artifacts should be invalidated only by code/config version
   changes or a new market day, not by app restart.

4. Add cache observability.

   Add a lightweight diagnostics endpoint and UI badge showing whether the
   current chart used memory cache, disk cache, stale cache, or fresh compute.
   This will make performance failures obvious and measurable.

5. Promote strategy discovery through saved campaigns, not one-off clicks.

   The strategy-discovery surface should be campaign-first:

   - choose baskets and windows
   - choose strategy families and allocator policies
   - run a saved matrix
   - compare completed runs without rerunning
   - promote only when a candidate clears a deterministic contract

6. Stop investing heavily in new single-ticker families for now.

   The focus-basket single-ticker loop already promoted `cci_hysteresis` and
   exhausted several branches. The highest-signal research is portfolio
   allocation, crash response, and upside retention.

7. Make the next portfolio research step allocator-first.

   The crash-guard signal detects trouble earlier, but the current blended
   overlay does not act strongly enough. Build a position-level or sleeve-level
   allocator that can:

   - shrink or exit specific positions when benchmark risk turns hostile
   - preserve a core sleeve only when upside-retention evidence supports it
   - re-enter through a ladder when breadth and trend recover
   - report exactly which names were de-risked and why

8. Add transaction-cost and slippage modeling before trusting close calls.

   Current results are useful for relative research, but tight strategy versus
   buy-and-hold gaps should not be promoted without cost assumptions.

9. Add an explicit "known universe" cache builder.

   Since the known universe is small, provide an intentional command that bakes
   every known ticker overnight or on demand. Keep the background prewarmer
   conservative so it never makes the interactive app feel stuck.

10. Keep no-winner decisions.

   The no-winner closeouts are valuable. They prevent the app from promoting
   fragile variants just because the search invested time in them.

## Recommended Next Steps

Near term:

1. Add a cache diagnostics endpoint for `/api/chart`.
2. Add visible cache/load timing instrumentation around ticker switches.
3. Make the prewarmer configurable by mode: off, selected strategy only, all
   visible strategies, full universe.
4. Ensure full-universe builds are explicit CLI jobs, not aggressive startup
   work.
5. Add tests proving warm ticker changes use cached candle and strategy
   payloads.

Strategy discovery:

1. Make the campaign comparison page the main research dashboard.
2. Add saved "candidate promotion reports" that explain why a run did or did
   not clear the contract.
3. Add filters for regime, basket, allocator, drawdown gap, upside capture,
   turnover, and max single-name concentration.
4. Add a benchmark-delta view that shows whether improvement came from signal,
   allocator, or basket composition.

Portfolio research:

1. Design a position-level crash allocator using the existing
   benchmark-aware crash-guard feature.
2. Test it first against the existing synthetic-stress harness.
3. Require both downside savings and upside retention before promotion.
4. Compare against equal-weight buy-and-hold, the `v1.18` tactical baseline,
   and the `v1.19` high-core near-miss.

Data and correctness:

1. Add a daily cache rollover model keyed by last available market date.
2. Store immutable historical indicator and signal artifacts once.
3. Recompute only the trailing windows that can actually change.
4. Add fixture regeneration docs directly to this file when benchmark windows
   intentionally move.

## Update And Verification Commands

Run the main deterministic suite:

```bash
source venv/bin/activate
TRIEDINGVIEW_USER_DATA_DIR=/tmp/tv_user pytest -q
```

Run the strategy/product contract tests:

```bash
source venv/bin/activate
TRIEDINGVIEW_USER_DATA_DIR=/tmp/tv_user pytest -q tests/test_strategy_config_ratchet.py tests/test_focus_basket_benchmark_backtests.py tests/test_polymarket.py tests/test_polymarket_benchmark_backtests.py
```

Run the portfolio contract and campaign tests:

```bash
source venv/bin/activate
TRIEDINGVIEW_USER_DATA_DIR=/tmp/tv_user pytest -q tests/test_routes.py tests/test_portfolio_campaigns.py tests/test_portfolio_research.py
```

Run synthetic-stress checks:

```bash
source venv/bin/activate
TRIEDINGVIEW_USER_DATA_DIR=/tmp/tv_user pytest -q tests/test_synthetic_stress.py tests/test_synthetic_stress_matrix.py tests/test_portfolio_macro_overlay.py
```

Regenerate focus-basket fixtures when the benchmark window intentionally
changes:

```bash
python scripts/regen_focus_basket_benchmark_fixtures.py
python scripts/regen_focus_basket_benchmark_fixtures.py --check
```

Regenerate Polymarket fixtures when the BTC or probability-history benchmark
intentionally changes:

```bash
python scripts/regen_polymarket_benchmark_fixtures.py
python scripts/regen_polymarket_benchmark_fixtures.py --check
```

Build chart cache artifacts for the current watchlist:

```bash
source venv/bin/activate
TRIEDINGVIEW_USER_DATA_DIR=/tmp/tv_user python3 app.py --build-chart-cache-only
```

## Maintenance Rule

When backtesting behavior changes, update the smallest matching set:

- product surface change: update `tests/fixtures/strategy_config_ratchet.json`,
  `tests/test_strategy_config_ratchet.py`, and this document
- focus-basket promotion change: update
  `tests/fixtures/focus_basket_benchmarks.json`,
  `tests/test_focus_basket_benchmark_backtests.py`, and this document
- Polymarket change: update
  `tests/fixtures/polymarket_benchmark_backtests.json`,
  `tests/test_polymarket_benchmark_backtests.py`, and this document
- portfolio route contract change: update
  `tests/fixtures/portfolio_backtest_contract_ratchet.json`,
  route tests, and this document
- campaign or research-matrix change: update the campaign or matrix fixture,
  campaign/research tests, and this document
- performance/cache behavior change: update cache/prewarmer tests and the
  Performance And Caching Status section

