# Focus Basket Baseline

This file mirrors the promoted baseline in [`tests/fixtures/focus_basket_benchmarks.json`](/Users/adrianosullivan/projects/trading/tests/fixtures/focus_basket_benchmarks.json) so future ratchet promotions are explainable in human-readable form.

## Promoted Basket

| Ticker | Net Profit % | Max Drawdown % | Buy-and-Hold Net Profit % | Score | Counts Toward 5-of-7 |
| --- | ---: | ---: | ---: | ---: | --- |
| BTC-USD | 215.63 | 41.54 | 835.25 | -418.53 | yes |
| ETH-USD | 594.16 | 19.03 | 1493.27 | -311.61 | yes |
| COIN | 90.16 | 23.93 | -55.00 | 81.78 | yes |
| TSLA | 440.72 | 34.89 | 1174.17 | -304.94 | yes |
| AAPL | 55.48 | 16.82 | 258.38 | -153.31 | yes |
| NVDA | 444.56 | 25.84 | 2886.36 | -2006.28 | yes |
| GOOG | 51.77 | 21.71 | 342.60 | -246.66 | yes |

## Aggregate Score Floor

- Aggregate score floor: `-479.94`
- Promotion rule: at least `5` of `7` tickers must match or improve their promoted score
- Drawdown regression guard: `5.0` percentage points
- Buy-and-hold gap regression guard: `10.0` percentage points
