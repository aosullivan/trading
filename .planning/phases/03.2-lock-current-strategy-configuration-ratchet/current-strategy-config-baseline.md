# Current Strategy Configuration Baseline

## Purpose

Phase `03.2` freezes the current backtest configuration contract so later strategy work cannot silently change what the user can select today.

## Pinned Defaults

- Default strategy: `ribbon`
- Default ticker: `BTC-USD`
- Default interval: `1d`
- Default period: `10`
- Default multiplier: `2.5`
- Default sizing: `All-In`
- Default stop: `None`
- Default risk cap: `None`
- Default compounding: `Per Trade`
- Default stop input value: `3`

## Frozen Strategy Selector Order

1. `ribbon` — `Trend-Driven`
2. `corpus_trend` — `Corpus Trend (Donchian/ATR)`
3. `cb50` — `Channel Breakout 50`
4. `cb150` — `Channel Breakout 150`
5. `sma_10_100` — `SMA 10/100 Cross`
6. `sma_10_200` — `SMA 10/200 Cross`
7. `ema_trend` — `EMA Trend (5mo)`
8. `yearly_ma` — `1-Year MA Trend`
9. `supertrend` — `Supertrend (10/2.5)`
10. `ema_crossover` — `EMA 5/20 Cross`
11. `macd` — `MACD Signal (16/32/9)`
12. `donchian` — `Donchian Breakout (10)`
13. `bb_breakout` — `Bollinger Breakout (30/1.5)`
14. `keltner` — `Keltner Breakout (30/10/1.5)`
15. `parabolic_sar` — `Parabolic SAR (0.01/0.01/0.1)`
16. `cci_trend` — `CCI Trend (30/80)`
17. `red_day_dip` — `Red day dip (-5%)`
18. `regime_router` — `Regime Router`
19. `tone` — `Tone`
20. `polymarket` — `Polymarket Skew`

## Frozen Route Contract

The deterministic route request uses:

- OHLCV fixture: `tests/fixtures/btc_usd_1d_benchmark.csv`
- Polymarket history fixture: `tests/fixtures/polymarket_probability_history_benchmark.json`
- Route: `/api/chart`
- Request window: `BTC-USD`, `1d`, `2025-08-08` to `2026-04-04`

Pinned backend strategy inventory:

- `ribbon`
- `cb50`
- `cb150`
- `sma_10_100`
- `sma_10_200`
- `ema_trend`
- `yearly_ma`
- `supertrend`
- `ema_crossover`
- `macd`
- `donchian`
- `corpus_trend`
- `bb_breakout`
- `keltner`
- `parabolic_sar`
- `cci_trend`
- `regime_router`
- `tone`
- `red_day_dip`
- `polymarket`

Strategies with strategy-local `buy_hold_equity_curve`:

- `ribbon`
- `corpus_trend`

## Update Rule

If a later phase intentionally changes defaults, labels, option order, or the backend strategy inventory, update:

1. `tests/fixtures/strategy_config_ratchet.json`
2. `tests/test_strategy_config_ratchet.py`
3. `docs/current-strategy-config-ratchet.md`
4. This baseline file

in the same change.
