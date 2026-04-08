# 03-02 Summary

## Outcome

Wave 2 added a deterministic diagnostics runner for the focus basket and used it to explain why the current exposed money-management knobs make `corpus_trend` worse on the promoted benchmark.

Delivered artifacts:

- [`scripts/analyze_focus_basket_diagnostics.py`](/Users/adrianosullivan/projects/trading/scripts/analyze_focus_basket_diagnostics.py) runs the seven-variant matrix against the frozen basket and emits JSON/Markdown outputs
- [`tests/test_focus_basket_diagnostics.py`](/Users/adrianosullivan/projects/trading/tests/test_focus_basket_diagnostics.py) proves the expected variant IDs and top-level artifact keys are reproduced from fixture-backed inputs
- [`focus-basket-diagnostics.json`](/Users/adrianosullivan/projects/trading/.planning/phases/03-build-ratchet-benchmark-and-diagnostics/focus-basket-diagnostics.json) stores per-ticker and aggregate metrics for every variant
- [`focus-basket-diagnostics.md`](/Users/adrianosullivan/projects/trading/.planning/phases/03-build-ratchet-benchmark-and-diagnostics/focus-basket-diagnostics.md) translates those deltas into a Phase 4 handoff

## Key Findings

- `baseline_none` remains the best aggregate variant at `-479.94`; every exposed sizing variant is materially worse.
- Vol sizing (`vol_trade`, `vol_monthly`, `vol_capped`) cuts average entry notional from `233.93%` to `4.35%` of initial capital and drops aggregate score by about `-508.78`.
- Fixed fraction sizing improves on vol sizing but still cuts average entry notional to roughly `41.6%` and loses about `-406` aggregate score versus baseline.
- `fixed_fraction_atr_stop` is especially damaging for participation: average entry notional falls to `13.67%`, and aggregate score slips to `-954.17`.
- The worst basket result is `vol_monthly`, which worsens `buy_hold_gap_pct` on all `7` tickers.

## Phase 4 Constraints

- Prefer `layered entries/exits` over all-in timing.
- `Preserve capital deployment on strong trends` instead of shrinking risk budget when volatility rises.
- `Avoid tiny risk-budget sizing` because the current basket winners are exactly the names where reduced exposure does the most damage.

## Verification

- `python scripts/analyze_focus_basket_diagnostics.py --output-json .planning/phases/03-build-ratchet-benchmark-and-diagnostics/focus-basket-diagnostics.json --output-md .planning/phases/03-build-ratchet-benchmark-and-diagnostics/focus-basket-diagnostics.md`
- `pytest -q tests/test_focus_basket_diagnostics.py`
- `rg -n "vol_trade|vol_monthly|vol_capped|fixed_fraction_trade|fixed_fraction_monthly|fixed_fraction_atr_stop|## Basket Scorecard|## Why Vol Sizing Underperformed|## Why Fixed Fraction Underperformed|## Other Knobs That Increased Churn|## Implications For Phase 4" .planning/phases/03-build-ratchet-benchmark-and-diagnostics/focus-basket-diagnostics.json .planning/phases/03-build-ratchet-benchmark-and-diagnostics/focus-basket-diagnostics.md`
