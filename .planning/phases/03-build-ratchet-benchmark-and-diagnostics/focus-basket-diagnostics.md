# Focus Basket Diagnostics

## Basket Scorecard

| Variant | Aggregate Score | Avg Net Profit % | Avg Max Drawdown % | Avg Buy-Hold Gap % | Avg Trades | Avg Entry Notional % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline_none | -479.94 | 270.35 | 26.25 | -720.36 | 22.71 | 233.93 |
| fixed_fraction_trade | -886.14 | 59.13 | 9.85 | -931.59 | 22.71 | 41.63 |
| fixed_fraction_monthly | -886.49 | 58.88 | 9.42 | -931.84 | 22.71 | 41.56 |
| fixed_fraction_atr_stop | -954.17 | 23.63 | 5.28 | -967.09 | 22.71 | 13.67 |
| vol_trade | -988.71 | 5.38 | 1.56 | -985.34 | 22.14 | 4.35 |
| vol_capped | -988.71 | 5.38 | 1.56 | -985.34 | 22.14 | 4.35 |
| vol_monthly | -988.72 | 5.38 | 1.56 | -985.34 | 22.14 | 4.35 |

## Why Vol Sizing Underperformed

Baseline `baseline_none` aggregate score: `-479.94`.

- `vol_trade` score delta `-508.77`, drawdown delta `-24.69`, trade-count delta `-0.57`, entry-notional delta `-229.58` versus `baseline_none`.
- `vol_monthly` score delta `-508.78`, drawdown delta `-24.69`, trade-count delta `-0.57`, entry-notional delta `-229.58` versus `baseline_none`.
- `vol_capped` score delta `-508.77`, drawdown delta `-24.69`, trade-count delta `-0.57`, entry-notional delta `-229.58` versus `baseline_none`.

## Why Fixed Fraction Underperformed

- `fixed_fraction_trade` score delta `-406.20`, drawdown delta `-16.40`, trade-count delta `+0.00`, entry-notional delta `-192.30` versus `baseline_none`.
- `fixed_fraction_monthly` score delta `-406.55`, drawdown delta `-16.83`, trade-count delta `+0.00`, entry-notional delta `-192.37` versus `baseline_none`.
- `fixed_fraction_atr_stop` score delta `-474.23`, drawdown delta `-20.97`, trade-count delta `+0.00`, entry-notional delta `-220.26` versus `baseline_none`.

## Other Knobs That Increased Churn

- Worst variant by aggregate_score: `vol_monthly`.
- `vol_monthly` worsened `buy_hold_gap_pct` on `7` of `7` tickers.
- Highest non-baseline average trade count came from `fixed_fraction_trade` at `22.71` trades per ticker, which shows the alternative knobs did not meaningfully reduce churn while still shrinking exposure.

## Implications For Phase 4

- Favor layered entries/exits so the strategy can stay invested through strong trends while reducing abrupt all-in timing risk.
- Preserve capital deployment on strong trends instead of shrinking exposure just because realized volatility rises on the basket winners.
- Avoid tiny risk-budget sizing that collapses exposure on high-volatility winners and widens the buy-and-hold gap.
