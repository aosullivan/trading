---
phase: 02-implement-corpus-derived-strategy
plan: 02
subsystem: backend
tags:
  - corpus-trend
  - donchian
  - atr
  - flask
requires:
  - phase: 01-build-trend-following-knowledge-base
    provides: Source-cited trend-following principles and implementation constraints
provides:
  - Runtime corpus_trend signal/backtest implementation
  - /api/chart corpus_trend payload integration
  - Backtest UI strategy selector option and regression coverage
affects:
  - 02-implement-corpus-derived-strategy
tech-stack:
  added: []
  patterns:
    - Full-cash single-position backtests with ATR/Donchian exits and next-open fills
    - Additive strategy registration that preserves existing ribbon defaults
key-files:
  created:
    - .planning/phases/02-implement-corpus-derived-strategy/02-02-SUMMARY.md
  modified:
    - lib/technical_indicators.py
    - lib/backtesting.py
    - routes/chart.py
    - templates/partials/backtest_panel.html
    - tests/test_indicators.py
    - tests/test_backtest.py
    - tests/test_routes.py
    - tests/test_ui.py
key-decisions:
  - "Implemented corpus_trend as long/cash Donchian 55/20 breakout plus ATR(14) trailing stop with 2.0x stop distance and full-cash single-position entries."
  - "Kept ribbon first and BT_DEFAULT_STRATEGY='ribbon' unchanged while exposing corpus_trend as the second selector option."
  - "Marked tests/test_ui.py with pytest.mark.ui so the plan's targeted UI verification command selects the strategy selector test."
patterns-established:
  - "New strategy payloads should preserve existing strategy keys and add contract-specific assertions in route/UI tests."
  - "Environment-only Playwright skips should be documented explicitly rather than treated as implementation failure."
requirements-completed:
  - STRAT-02
  - STRAT-03
  - STRAT-04
  - COMP-01
  - COMP-02
duration: 13 min
completed: 2026-04-04
---

# Phase 02 Plan 02: Corpus-Trend Implementation Summary

**Corpus-derived Donchian/ATR strategy shipped through indicator, backtest, chart API, and selector UI while preserving ribbon defaults**

## Performance

- **Duration:** 13 min
- **Started:** 2026-04-04T11:29:00-07:00
- **Completed:** 2026-04-04T11:42:00-07:00
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Added `compute_corpus_trend_signal(...)` with asymmetric Donchian channels, Wilder ATR, ATR trailing stop, and long/flat direction output.
- Added `backtest_corpus_trend(...)` with next-open fills, full-cash long entries, ATR/Donchian exits, and final open-trade mark-to-last-close behavior.
- Exposed `payload["strategies"]["corpus_trend"]` from `/api/chart` and added the selector option immediately after `ribbon` while preserving `BT_DEFAULT_STRATEGY='ribbon'`.
- Extended indicator, backtest, route, and UI tests for the new strategy contract and legacy default ordering.

## Task Commits

1. **Task 1: Implement corpus-trend signal, ATR-sized backtest, and chart route payload** - `49427c0` (feat)
2. **Task 2: Expose corpus-trend in the backtest UI and protect default strategy ordering** - `04a9758` (feat)

**Plan metadata:** final summary/state commit

## Files Created/Modified

- `lib/technical_indicators.py` - Added corpus-trend signal generation and shared Wilder ATR helper.
- `lib/backtesting.py` - Added ATR-risk-sized corpus-trend backtester with long/cash accounting.
- `routes/chart.py` - Computed corpus-trend signals and added the strategy payload object.
- `templates/partials/backtest_panel.html` - Added `Corpus Trend (Donchian/ATR)` after `ribbon`.
- `tests/test_indicators.py` - Covered breakout, channel exit, ATR, and trailing stop behavior.
- `tests/test_backtest.py` - Covered ATR-sized entries, idle cash, and final open-trade marking.
- `tests/test_routes.py` - Verified `corpus_trend` appears in `/api/chart` with the expected payload contract.
- `tests/test_ui.py` - Verified selector ordering and tagged the module with `pytest.mark.ui`.

## Decisions Made

- Used Wilder-smoothed ATR for both Supertrend and corpus-trend so stop sizing and trailing logic share one ATR implementation.
- Switched entry sizing to deploy available cash in the current single-ticker report path after BTC weekly UAT showed 1% ATR risk-budget sizing produced a near-flat strategy curve.
- Preserved all existing strategy keys and left `ribbon` as the default strategy to avoid UI regression.

## Deviations from Plan

### Auto-fixed Issues

**1. [Test Harness] Added the missing module-level `ui` marker**
- **Found during:** Task 2 (`pytest -m ui tests/test_ui.py -k strategy_select_options`)
- **Issue:** The command selected zero tests because `tests/test_ui.py` had no `pytest.mark.ui` marker.
- **Fix:** Added `pytestmark = pytest.mark.ui` and reran the targeted command.
- **Files modified:** `tests/test_ui.py`
- **Verification:** `venv/bin/python -m pytest -m ui tests/test_ui.py -k strategy_select_options -rs` selected one test.
- **Committed in:** `04a9758`

---

**Total deviations:** 1 auto-fixed (test harness)
**Impact on plan:** No scope creep; the fix made the required verification command meaningful.

## Issues Encountered

- Bare `pytest` and `python3 -m pytest` were unavailable in this shell, so verification used `venv/bin/python -m pytest ...`.
- `venv/bin/python -m pytest -m ui tests/test_ui.py -k strategy_select_options -rs` selected the right test but skipped it because the Playwright Chromium binary is not installed at `/Users/adrianosullivan/Library/Caches/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-mac-arm64/chrome-headless-shell`. Backend/API/UI code changes still landed and backend tests passed.

## User Setup Required

None for backend/API. To run the skipped browser test locally, install Playwright browsers with `playwright install`.

## Next Phase Readiness

Phase 2 implementation is complete and ready for manual spot-checking of `corpus_trend` in the backtest UI once Playwright/browser tooling is available.

---
*Phase: 02-implement-corpus-derived-strategy*
*Completed: 2026-04-04*
