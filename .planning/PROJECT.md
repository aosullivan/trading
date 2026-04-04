# TriedingView

## What This Is

TriedingView is a local charting and backtesting app for stocks, crypto, ETFs, indexes, and Treasury proxies. It combines Flask APIs, yfinance/FRED data, TradingView Lightweight Charts, a live watchlist, support/resistance overlays, financial snapshots, and multiple strategy backtests so new strategy ideas can be explored and compared quickly.

## Core Value

New trading strategy variants should be testable and visually comparable in the existing chart/backtest UI without breaking current indicators, watchlist flows, or data correctness.

## Requirements

### Validated

- ✓ Interactive charting with daily/weekly/monthly candles and multiple overlays — existing
- ✓ Strategy backtesting with trade history, summary metrics, and buy-and-hold comparison — existing
- ✓ Watchlist management with quote refresh, trend views, and click-to-load chart navigation — existing
- ✓ Company financials modal for supported equity tickers and explicit Treasury-proxy fallback copy — existing
- ✓ Support/resistance detection and chart rendering — existing
- ✓ Local data/watchlist persistence in a per-user app data directory with source and desktop-app path support — existing
- ✓ Trend Ribbon strategy/backtest infrastructure and optimizer tooling — existing

### Active

- [ ] Add a new ribbon strategy variant to the backend indicator/backtest stack and expose it through `/api/chart`
- [ ] Add the new ribbon strategy to the frontend strategy selector, overlay/signal display, and explanatory UI copy
- [ ] Preserve existing Trend Ribbon behavior and regression coverage while adding tests for the new variant

### Out of Scope

- Replacing Flask/Jinja or introducing a frontend build pipeline — this feature should fit the current architecture
- Shipping a hosted SaaS version or authentication — current app remains local-first
- Reworking every non-ribbon strategy — scope is a new ribbon variant plus safe integration
- Long-running optimizer redesign unless the new strategy requires a small, targeted extension

## Context

The existing codebase is a brownfield Flask app with substantial indicator and backtesting logic already in `lib/`, route orchestration in `routes/`, and global-script frontend behavior under `static/js/`. GSD codebase mapping is available in `.planning/codebase/`.

Important implementation context:
- `routes/chart.py` computes indicator bundles, backtests, and JSON payloads for the main chart endpoint.
- `lib/technical_indicators.py`, `lib/backtesting.py`, and `lib/trend_ribbon_profile.py` are the core strategy modules likely affected by a ribbon variant.
- `templates/partials/signal_chips.html`, `templates/partials/backtest_panel.html`, and `static/js/chart_*.js` define how strategies appear and toggle in the UI.
- Tests already exist for routes, backtesting, indicators, support/resistance, optimizer behavior, and Playwright UI flows.
- Current concerns documented in `.planning/codebase/CONCERNS.md` include dependency drift, broad exception handling, frontend globals, and duplicated interval/backtest logic.

## Constraints

- **Tech stack**: Stay within Flask, pandas, yfinance/FRED, Jinja templates, and plain browser JS/CSS — this repo has no JS bundler/module pipeline.
- **Compatibility**: Existing strategy keys, payload shape, and UI flows should continue working — users rely on current overlays/watchlist/backtest behavior.
- **Data correctness**: Respect warmup/lookback handling, ticker normalization, and interval resampling patterns already in use — chart and optimizer outputs should stay aligned.
- **Testability**: Add/adjust pytest and targeted frontend/UI coverage for the new strategy — current workflows depend on these tests for confidence.
- **Local-first storage**: Keep persistence under `lib.paths.get_user_data_path(...)` when new state or cache artifacts are needed — desktop/source runs must both work.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Keep this as a brownfield GSD project initialized from the existing codebase map | We need phase workflows to understand current architecture before changing strategy code | — Pending |
| Start with one implementation phase focused on the new ribbon strategy, then use `$gsd-discuss-phase 1` to clarify exact behavior/UI choices | The feature request is intentionally high-level and needs a discussion pass before detailed planning | — Pending |
| Preserve current Trend Ribbon behavior while introducing the new strategy as an additional variant unless discussion says otherwise | Safer for regression risk and easier A/B comparison in the UI | — Pending |
| Use existing Flask/Jinja/plain-JS architecture rather than adding a frontend build step | The current repo is intentionally lightweight and script-order based | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `$gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `$gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-04 after initialization*
