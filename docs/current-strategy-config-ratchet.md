# Current Strategy Configuration Ratchet

This ratchet protects the current backtest product contract, not just strategy performance.

## What It Freezes

The machine-readable source of truth is [`tests/fixtures/strategy_config_ratchet.json`](/Users/adrianosullivan/projects/trading/tests/fixtures/strategy_config_ratchet.json).

It pins:

- the current backtest defaults, including `default_strategy: "ribbon"`
- the exact strategy selector order and labels exposed in `/backtest`
- the additive exposure of `corpus_trend_layered` as a comparison-only strategy
- the current money-management defaults and option lists
- the backend `/api/chart` strategy inventory and required payload fields
- the frozen deterministic fixture paths `tests/fixtures/btc_usd_1d_benchmark.csv` and `tests/fixtures/polymarket_probability_history_benchmark.json`

## Why This Exists

The milestone already had performance ratchets for the focus basket and for Polymarket. Those guards are important, but they do not stop a subtler regression where:

- the default strategy changes
- option ordering changes
- a visible config disappears or gets renamed
- the backend `strategies` payload drifts away from the selector surface

This ratchet makes those product-surface changes explicit and reviewable.

## Deterministic Test

[`tests/test_strategy_config_ratchet.py`](/Users/adrianosullivan/projects/trading/tests/test_strategy_config_ratchet.py) enforces the contract in three places:

1. `/backtest` must render the pinned `strategy-select` and money-management option sequences.
2. [`backtest_panel.js`](/Users/adrianosullivan/projects/trading/static/js/backtest_panel.js) must keep `BT_DEFAULT_STRATEGY` pinned to `ribbon`, and [`backtest_report.js`](/Users/adrianosullivan/projects/trading/static/js/backtest_report.js) must still fall back to that default.
3. `/api/chart` must expose the pinned backend strategy keys and required fields when run against frozen BTC OHLCV plus frozen Polymarket history.

The route test is deterministic because it patches:

- `routes.chart.cached_download` with `tests/fixtures/btc_usd_1d_benchmark.csv`
- `lib.polymarket.load_probability_history` with `tests/fixtures/polymarket_probability_history_benchmark.json`

## Update Workflow

If a later phase intentionally changes defaults, labels, option order, or the route strategy inventory:

1. update `tests/fixtures/strategy_config_ratchet.json`
2. update `docs/current-strategy-config-ratchet.md`
3. update `.planning/phases/03.2-lock-current-strategy-configuration-ratchet/current-strategy-config-baseline.md`
4. keep `tests/test_strategy_config_ratchet.py` aligned in the same change

That way the ratchet only moves when the repo accepts a deliberate new baseline.
