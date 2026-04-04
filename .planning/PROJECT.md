# TriedingView

## What This Is

TriedingView is a local charting/backtesting app, and this milestone is about turning the trend-following transcript corpus in `audio/` into a practical knowledge base that can drive a strategy design. The main output should be: read all text transcripts, extract trend-following principles/rules/constraints, structure that into reusable knowledge, then build a trading strategy from what the corpus teaches.

## Core Value

The strategy should be grounded in what the `audio/` transcripts actually say about trend following, not just manually invented indicator tweaks.

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

- [ ] Read every transcript text file in `audio/` and extract a structured trend-following knowledge base
- [ ] Use that knowledge base to derive a concrete strategy specification: entry rules, exit rules, risk management, position sizing, and market regime assumptions
- [ ] Implement the resulting trend-following strategy in the existing backtest/chart stack and preserve current app behavior

### Out of Scope

- Replacing Flask/Jinja or introducing a frontend build pipeline — this feature should fit the current architecture
- Shipping a hosted SaaS version or authentication — current app remains local-first
- Reworking every non-ribbon strategy — scope is corpus-driven trend-following research plus one implemented strategy
- Treating the transcript text as verbatim UI copy — the corpus should be distilled into a structured knowledge artifact and strategy rules

## Context

The existing codebase is a brownfield Flask app with substantial indicator and backtesting logic already in `lib/`, route orchestration in `routes/`, and global-script frontend behavior under `static/js/`. GSD codebase mapping is available in `.planning/codebase/`.

Important implementation context:
- `routes/chart.py` computes indicator bundles, backtests, and JSON payloads for the main chart endpoint.
- `lib/technical_indicators.py`, `lib/backtesting.py`, and `lib/trend_ribbon_profile.py` are the core strategy modules likely affected by a ribbon variant.
- `audio/` contains 75 transcript text files from *Trend Following, 5th Edition* that should be ingested/read in chapter order and distilled into a reusable knowledge base.
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
| Make transcript ingestion and trend-following knowledge extraction the first phase before strategy implementation | The user clarified that the real output starts with learning from the `audio/` text corpus | — Pending |
| Derive strategy rules from the extracted knowledge base before coding indicator/backtest changes | This keeps implementation tied to corpus-backed trend-following principles | — Pending |
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
