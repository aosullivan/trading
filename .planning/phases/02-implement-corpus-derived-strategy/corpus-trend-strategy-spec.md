# Corpus Trend Strategy Specification

## Contract
- **Strategy key:** `corpus_trend`
- **UI label:** `Corpus Trend (Donchian/ATR)`
- **Backtest posture:** long/cash only for v1, not long/short
- **Signal inputs:** price-only OHLC data and ATR-derived volatility, with no macro/fundamental filters
- **Default strategy ordering:** keep `ribbon` first and `BT_DEFAULT_STRATEGY='ribbon'`; `corpus_trend` is additive, not a replacement

## Rule Defaults
- **Donchian entry lookback:** 55 bars
- **Donchian trailing exit lookback:** 20 bars
- **ATR period:** 14 bars
- **ATR stop multiple:** 2.0
- **Account risk budget per entry:** 1.0% of current equity
- **Direction convention:** `1` = long, `-1` = cash/flat, with no short entries

## Signal Formula
Implement `compute_corpus_trend_signal(...)` in `lib/technical_indicators.py` with these outputs:
- `entry_upper`: previous-bar Donchian upper channel from a 55-bar rolling high
- `exit_lower`: previous-bar Donchian lower channel from a 20-bar rolling low
- `atr`: Wilder-style ATR over 14 bars
- `stop_line`: `Close - (2.0 * atr)` while long, carried as a non-decreasing trailing stop
- `direction`: long/cash state machine derived from breakout, channel exit, and stop exit rules below

Entry rule:
1. Stay flat until there is enough warmup data for both Donchian windows and ATR.
2. Enter long when `Close[i] > entry_upper[i]`.
3. Fill the entry on the next bar's `Open`, matching the existing backtest convention in `backtest_direction(...)`.

Exit rule:
1. While long, compute a trailing stop candidate `Close[i] - (2.0 * atr[i])` and keep the running stop non-decreasing.
2. Exit to cash when `Close[i] < exit_lower[i]` or `Close[i] < trailing_stop[i]`.
3. Fill the exit on the next bar's `Open` and mark any final still-open position to the last close.

Warmup and initial-state behavior:
- Use `start = max(55, 20, 14)` before evaluating transitions.
- Return `-1` during warmup/flat periods so the route/backtest path stays compatible with the current long/cash strategy contract.
- When the visible chart window starts mid-trend, seed the first visible bar from the prior full-history `direction` value using the same route helper pattern already used for existing strategies.

## Backtest Formula
Implement `backtest_corpus_trend(...)` in `lib/backtesting.py` and preserve the existing `(trades, summary, equity_curve)` return shape.

Position sizing:
- On each long entry, compute stop distance as `max(entry_price - stop_price, 0.01)`, where `stop_price` comes from the latest valid `stop_line` value at the signal bar.
- Risk cash = `equity * 0.01`.
- Quantity = `min(cash / entry_price, risk_cash / stop_distance)`.
- Leave unused cash idle instead of forcing all-in exposure.

Trade object semantics:
- Use the existing trade dict fields: `entry_date`, `entry_price`, `exit_date`, `exit_price`, `quantity`, `type`, `pnl`, `pnl_pct`, and `open` for still-open trades.
- Add no new required top-level summary keys; rely on `compute_summary(...)` so existing report rendering continues to work.

Drawdown discipline:
- Do not adapt Donchian/ATR constants based on recent drawdown.
- Let `compute_summary(...)` continue to report max drawdown and open/realized P&L so the discipline cost is visible in the UI.

## Route and UI Contract
`routes/chart.py` should:
- Import `compute_corpus_trend_signal` and `backtest_corpus_trend`.
- Cache corpus-trend signal outputs in `_get_indicator_bundle(...)` alongside existing indicators.
- Compute `corpus_trend_trades`, `corpus_trend_summary`, and `corpus_trend_equity_curve` from the full-history signal and visible-window slice.
- Append `payload["strategies"]["corpus_trend"] = {"trades": ..., "summary": ..., "equity_curve": ..., "buy_hold_equity_curve": buy_hold_equity_curve}`.
- Preserve the existing `payload["strategies"]["ribbon"]` contract and all existing strategy keys.

`templates/partials/backtest_panel.html` should:
- Keep `<option value="ribbon">Trend-Driven</option>` first.
- Append `<option value="corpus_trend">Corpus Trend (Donchian/ATR)</option>` as a non-default strategy choice.

No changes are required to `static/js/backtest_panel.js` for default selection behavior, because it already reads the selected `<option>` value and keeps `BT_DEFAULT_STRATEGY='ribbon'`.

## Phase 1 Traceability

| Spec decision | Phase 1 principle IDs | Source artifact |
|---------------|-----------------------|-----------------|
| Price-only breakout entries over prediction-driven entries | `entry-001`, `trend-001`, `regime-001` | `.planning/phases/01-build-trend-following-knowledge-base/trend-following-knowledge-base.md` |
| Systematic trailing/channel exits and ATR stops | `exit-001`, `whipsaw-001`, `drawdown-001` | `.planning/phases/01-build-trend-following-knowledge-base/trend-following-knowledge-base.md` |
| 1.0% risk-budget sizing with ATR-scaled quantities and idle cash allowed | `sizing-001`, `risk-001`, `portfolio-001` | `.planning/phases/01-build-trend-following-knowledge-base/trend-following-knowledge-base.json` |
| Fixed 55/20/14/2.0 defaults with no drawdown-triggered parameter adaptation | `drawdown-001`, `trend-001`, `whipsaw-001` | `.planning/phases/01-build-trend-following-knowledge-base/01-02-SUMMARY.md` |
| Single-ticker long/cash implementation in v1, reusable across tickers but not yet a true basket allocator | `portfolio-001`, `risk-001` | `.planning/phases/02-implement-corpus-derived-strategy/02-CONTEXT.md` |

## Implementation File Map for 02-02

| File | Contract to implement |
|------|-----------------------|
| `lib/technical_indicators.py` | Add `compute_corpus_trend_signal(...)` and constants for Donchian entry/exit lookbacks, ATR period, stop multiple, and risk budget defaults. |
| `lib/backtesting.py` | Add `backtest_corpus_trend(...)` with ATR-sized long/cash entries, next-open fills, channel/stop exits, open-trade marking, and `compute_summary(...)` compatibility. |
| `routes/chart.py` | Compute corpus-trend signal outputs in `_get_indicator_bundle(...)`, run the new backtest over `df_view`, and expose `payload["strategies"]["corpus_trend"]`. |
| `templates/partials/backtest_panel.html` | Add `<option value="corpus_trend">Corpus Trend (Donchian/ATR)</option>` after the existing `ribbon` option without changing the first/default strategy. |
| `tests/test_indicators.py` | Cover warmup behavior, breakout entries, channel/stop exits, and non-decreasing trailing stops for `compute_corpus_trend_signal(...)`. |
| `tests/test_backtest.py` | Cover ATR-sized quantity math, idle cash behavior, closed/open trade semantics, empty-frame handling, and summary compatibility for `backtest_corpus_trend(...)`. |
| `tests/test_routes.py` | Verify `corpus_trend` appears in `payload["strategies"]` with `trades`, `summary`, `equity_curve`, and `buy_hold_equity_curve`, while existing strategy keys remain present. |
| `tests/test_ui.py` | Verify the strategy select still has `ribbon` first and now includes `corpus_trend` with the expected display label. |

## Caveat from Phase 1 Extraction

The Phase 1 KB is a deterministic first pass built from curated `PRINCIPLE_BLUEPRINTS` plus substring term matching in `scripts/build_trend_following_kb.py`, not a sentence-level semantic parser over every transcript line. Phase 2 should preserve the principle IDs and citations above for traceability, but treat the exact 55/20/14/2.0/1.0% defaults as an implementation starting point derived from the KB's directionally consistent rules, not as book-proven optimal parameters.
