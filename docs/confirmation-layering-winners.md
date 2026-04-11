# Confirmation Layering Winners

Cached-data report generated from the current local OHLCV snapshots in `/tmp/tv_user/data_cache`, using the app's current strategy and backtest logic for the window `2020-01-01` through `2026-04-04`.

Qualification rule:
- confirmation mode must beat the same strategy in `Standard`
- confirmation mode must also beat buy and hold on the same window

Confirmation modes compared:
- `layered_30_70`
- `layered_50_50`

Drawdown-adjusted edge in this report means:
- `(confirmation net profit % / confirmation max drawdown %) - (standard net profit % / standard max drawdown %)`

## Raw Edge Leaders

Ranked by net profit edge over the better of `Standard` and buy and hold.

| Rank | Ticker | Strategy | Mode | Confirm | Standard | Buy & Hold | Max DD | Edge | URL |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | COIN | `parabolic_sar` | `layered_50_50` | `205.40%` | `86.99%` | `-47.77%` | `28.79%` | `118.41` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=parabolic_sar&confirm_mode=layered_50_50) |
| 2 | COIN | `donchian` | `layered_50_50` | `97.22%` | `6.68%` | `-47.77%` | `71.04%` | `90.54` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=donchian&confirm_mode=layered_50_50) |
| 3 | COIN | `supertrend` | `layered_30_70` | `58.78%` | `-20.85%` | `-47.77%` | `39.30%` | `79.63` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=supertrend&confirm_mode=layered_30_70) |
| 4 | META | `ribbon` | `layered_50_50` | `254.51%` | `175.34%` | `175.99%` | `27.19%` | `78.52` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=META&strategy=ribbon&confirm_mode=layered_50_50) |
| 5 | COIN | `supertrend` | `layered_50_50` | `55.58%` | `-20.85%` | `-47.77%` | `69.58%` | `76.43` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=supertrend&confirm_mode=layered_50_50) |
| 6 | META | `ema_crossover` | `layered_50_50` | `241.17%` | `148.81%` | `175.99%` | `19.41%` | `65.18` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=META&strategy=ema_crossover&confirm_mode=layered_50_50) |
| 7 | COIN | `sma_10_100` | `layered_50_50` | `39.46%` | `-23.10%` | `-47.77%` | `54.24%` | `62.56` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=sma_10_100&confirm_mode=layered_50_50) |
| 8 | COIN | `donchian` | `layered_30_70` | `68.08%` | `6.68%` | `-47.77%` | `67.35%` | `61.40` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=donchian&confirm_mode=layered_30_70) |
| 9 | COIN | `cb50` | `layered_50_50` | `38.97%` | `-19.46%` | `-47.77%` | `63.34%` | `58.43` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=cb50&confirm_mode=layered_50_50) |
| 10 | ADBE | `supertrend` | `layered_30_70` | `41.13%` | `-16.43%` | `-27.36%` | `23.23%` | `57.56` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=ADBE&strategy=supertrend&confirm_mode=layered_30_70) |

## Drawdown-Adjusted Leaders

Ranked by drawdown-adjusted edge versus `Standard`.

| Rank | Ticker | Strategy | Mode | Confirm | Standard | Max DD | Ratio Edge | URL |
|---|---|---|---|---:|---:|---:|---:|---|
| 1 | NFLX | `cci_trend` | `layered_50_50` | `222.98%` | `74.90%` | `16.43%` | `12.105` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=NFLX&strategy=cci_trend&confirm_mode=layered_50_50) |
| 2 | META | `keltner` | `layered_50_50` | `233.14%` | `137.89%` | `17.08%` | `10.416` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=META&strategy=keltner&confirm_mode=layered_50_50) |
| 3 | META | `supertrend` | `layered_50_50` | `254.04%` | `236.54%` | `13.54%` | `9.629` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=META&strategy=supertrend&confirm_mode=layered_50_50) |
| 4 | META | `donchian` | `layered_50_50` | `207.41%` | `189.46%` | `15.84%` | `7.313` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=META&strategy=donchian&confirm_mode=layered_50_50) |
| 5 | META | `ema_crossover` | `layered_50_50` | `241.17%` | `148.81%` | `19.41%` | `6.506` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=META&strategy=ema_crossover&confirm_mode=layered_50_50) |
| 6 | META | `ema_crossover` | `layered_30_70` | `188.13%` | `148.81%` | `16.75%` | `5.312` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=META&strategy=ema_crossover&confirm_mode=layered_30_70) |
| 7 | COIN | `parabolic_sar` | `layered_50_50` | `205.40%` | `86.99%` | `28.79%` | `4.836` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=parabolic_sar&confirm_mode=layered_50_50) |
| 8 | META | `ribbon` | `layered_50_50` | `254.51%` | `175.34%` | `27.19%` | `4.226` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=META&strategy=ribbon&confirm_mode=layered_50_50) |

## Focus Basket Only

These are the current beat-both winners inside the ratchet basket `BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, `GOOG`.

At the moment the wins are concentrated in `COIN`.

| Rank | Ticker | Strategy | Mode | Confirm | Standard | Buy & Hold | Edge | URL |
|---|---|---|---|---:|---:|---:|---:|---|
| 1 | COIN | `parabolic_sar` | `layered_50_50` | `205.40%` | `86.99%` | `-47.77%` | `118.41` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=parabolic_sar&confirm_mode=layered_50_50) |
| 2 | COIN | `donchian` | `layered_50_50` | `97.22%` | `6.68%` | `-47.77%` | `90.54` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=donchian&confirm_mode=layered_50_50) |
| 3 | COIN | `supertrend` | `layered_30_70` | `58.78%` | `-20.85%` | `-47.77%` | `79.63` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=supertrend&confirm_mode=layered_30_70) |
| 4 | COIN | `supertrend` | `layered_50_50` | `55.58%` | `-20.85%` | `-47.77%` | `76.43` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=supertrend&confirm_mode=layered_50_50) |
| 5 | COIN | `sma_10_100` | `layered_50_50` | `39.46%` | `-23.10%` | `-47.77%` | `62.56` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=sma_10_100&confirm_mode=layered_50_50) |
| 6 | COIN | `donchian` | `layered_30_70` | `68.08%` | `6.68%` | `-47.77%` | `61.40` | [Open](http://127.0.0.1:5050/backtest?interval=1d&start=2020-01-01&end=2026-04-04&domain_start=2015-01-01&domain_end=2026-04-04&period=10&multiplier=2.5&ticker=COIN&strategy=donchian&confirm_mode=layered_30_70) |

## Readout

- `layered_50_50` is the strongest recurring winner. It shows up more often in the top ranks than `layered_30_70`.
- The best beat-both cases tend to be names where weekly confirmation helps avoid destructive early full-size exposure while still letting the strategy compound once the higher timeframe agrees.
- The focus basket is not broadly solved by confirmation yet. The current wins are mostly `COIN`, not `BTC-USD`, `ETH-USD`, `TSLA`, `AAPL`, `NVDA`, or `GOOG`.
- `META` is the clearest mainstream-stock proof that confirmation layering can beat both the plain strategy and buy and hold on a strong secular winner.
