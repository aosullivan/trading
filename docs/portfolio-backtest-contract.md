# Portfolio Backtest Contract

This document describes the live portfolio backtesting surface added in milestone `v1.15 Portfolio-Level Strategy Backtesting`.

It explains the current product contract in repo terms:

- which strategies are supported
- which allocator posture is active
- which basket modes are supported
- how portfolio buy-and-hold is defined
- which comparison and order diagnostics the route and page now expose

For no-drift regression enforcement, see [portfolio_backtest_contract_ratchet.json](/Users/adrianosullivan/projects/trading/tests/fixtures/portfolio_backtest_contract_ratchet.json).

## Supported Strategies

The current retained portfolio strategy surface is:

- `ribbon`
- `corpus_trend`
- `cci_hysteresis`

These stay aligned with the retained single-ticker strategy inventory rather than creating a separate portfolio-only taxonomy.

The following are not part of the first portfolio selector:

- `corpus_trend_layered`
- `polymarket`

## Allocator Posture

The current engine now exposes an explicit allocator policy input, even though the first product surface still uses the default policy silently.

The currently supported allocator policies are:

- `signal_flip_v1`
  New exposure comes only from fresh bullish flips. This is the backwards-compatible baseline.
- `signal_equal_weight_redeploy_v1`
  Freed capital can redeploy into any currently bullish unheld names with equal cash budgets.
- `signal_top_n_strength_v1`
  Freed capital is limited to the strongest currently bullish names using a simple cross-sectional strength ranking.
- `core_plus_rotation_v1`
  Capital is split into a broad core sleeve plus a tactical overweight to the strongest currently bullish name.

These are the first portfolio-policy variants above the retained signal engines. They do not yet imply a full rebalance system, but they are enough to start testing whether allocator behavior helps at the portfolio level.

## Supported Basket Modes

The current portfolio route and page support three basket modes:

- `watchlist`
  Uses the current local watchlist.
- `manual`
  Uses a manual ticker list supplied by the user.
- `preset`
  Uses a deterministic built-in basket.

The built-in preset baskets are:

- `focus` / `focus_7`
  Reuses the mixed crypto and growth focus basket:
  `BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, `GOOG`
- `growth_5`
  Concentrated large-cap growth basket:
  `AAPL`, `MSFT`, `NVDA`, `AMZN`, `META`
- `diversified_10`
  Broader equity basket for lower concentration:
  `AAPL`, `MSFT`, `GOOG`, `AMZN`, `META`, `NVDA`, `JPM`, `XOM`, `COST`, `UNH`

## Benchmark Model

The active strategy run is compared against portfolio buy-and-hold on the same basket and same date range.

The first buy-and-hold model is intentionally simple:

- same included ticker set after skip filtering
- same requested visible window
- same initial capital
- equal-weight capital split across included tickers
- held without signal exits or rebalance research

This keeps the first portfolio question understandable:

- does the strategy help the whole basket versus simply holding it?

## Route Payload

`/api/portfolio/backtest` now exposes:

- `strategy`
- `basket`
- `basket_diagnostics`
- `comparison`
- `portfolio_diagnostics`
- `orders`
- `tickers`
- `skipped`
- `portfolio_equity_curve`
- `portfolio_buy_hold_curve`
- `portfolio_summary`
- `per_ticker`
- `heat_series`
- `config`

## Comparison Diagnostics

The `comparison` object is the portfolio-level answer to strategy vs buy-and-hold. It includes:

- strategy ending equity
- buy-and-hold ending equity
- strategy return percent
- buy-and-hold return percent
- buy-and-hold max drawdown percent
- drawdown gap percent
- upside capture percent on positive benchmark windows
- equity gap
- return gap percent
- winner (`strategy`, `buy_hold`, or `tie`)

## Portfolio Diagnostics

The route now also exposes `portfolio_diagnostics`, which is the first allocator-research surface above the basic return comparison.

It currently includes:

- `allocator_policy`
- `avg_invested_pct`
- `avg_cash_pct`
- `avg_active_positions`
- `max_active_positions`
- `max_single_name_weight_pct`
- `avg_top_3_weight_pct`
- `turnover_pct`
- `redeployment_opportunities`
- `redeployment_events`
- `avg_redeployment_lag_bars`
- `unfilled_redeployment_opportunities`

## Order And Participation Diagnostics

The route also exposes a basket-level order ledger and basket diagnostics so the user can inspect what happened inside the run.

`orders` includes:

- ticker
- entry and exit dates
- entry and exit prices
- quantity
- side
- open or closed status
- P&L and P&L percent

`basket_diagnostics` includes:

- basket count
- size bucket (`small`, `medium`, `large`)
- composition (`equity_only`, `crypto_only`, `mixed`)
- crypto and equity counts
- traded ticker count
- active ticker count
- skipped ticker count

## UI Surface

The existing portfolio page at `/portfolio` now exposes:

- retained strategy selector
- basket mode selector
- manual ticker input
- named research presets (`focus_7`, `growth_5`, `diversified_10`)
- strategy vs buy-and-hold comparison section
- basket diagnostics section
- order activity table
- per-ticker participation table

The route config payload now also records the active allocator policy so saved and compared runs can stay attributable as allocator research expands.

## Deterministic Guard

The deterministic mocked-route ratchet at [portfolio_backtest_contract_ratchet.json](/Users/adrianosullivan/projects/trading/tests/fixtures/portfolio_backtest_contract_ratchet.json) and its paired route test in [test_routes.py](/Users/adrianosullivan/projects/trading/tests/test_routes.py) are the source of truth for no-drift contract enforcement.
