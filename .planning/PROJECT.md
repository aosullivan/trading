# TriedingView

## What This Is

TriedingView is a local charting/backtesting app. The current milestone is about improving the quality of strategy results by building a ratchet-style benchmark system, diagnosing why existing sizing/backtest knobs degrade performance, and evolving the corpus-derived strategy toward layered entries/exits that capture upside while avoiding major drawdowns across a fixed focus basket.

## Core Value

Strategy changes should stay grounded in the `audio/` transcripts' trend-following principles and only be promoted when they measurably improve the ratchet benchmark across the focus basket without introducing avoidable regressions.

## Requirements

### Validated

- ✓ Interactive charting with daily/weekly/monthly candles and multiple overlays — existing
- ✓ Strategy backtesting with trade history, summary metrics, and buy-and-hold comparison — existing
- ✓ Watchlist management with quote refresh, trend views, and click-to-load chart navigation — existing
- ✓ Company financials modal for supported equity tickers and explicit Treasury-proxy fallback copy — existing
- ✓ Support/resistance detection and chart rendering — existing
- ✓ Local data/watchlist persistence in a per-user app data directory with source and desktop-app path support — existing
- ✓ Trend Ribbon strategy/backtest infrastructure and optimizer tooling — existing
- ✓ Corpus-derived `corpus_trend` strategy available in backend/UI with regression coverage — shipped in milestone v1.0

### Active

## Current Milestone: v1.1 Strategy Ratchet Optimization

**Goal:** Build a repeatable ratchet benchmark and improve the strategy stack so promoted changes outperform the current baseline across the focus basket while reducing major drawdowns.

**Target features:**
- Fixed benchmark basket for `BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, and `GOOG`
- Ratchet workflow that compares candidate strategy changes against the current best baseline and blocks regressions
- Layered in/out position management instead of all-in/all-out behavior
- Diagnostics for why vol-normalized sizing, fixed-fraction sizing, and other backtest parameters have been degrading results
- Trend-following optimization focused on beating buy-and-hold with better drawdown control

- [ ] Establish a fixed cross-ticker benchmark harness and artifact for the focus basket
- [ ] Define a ratchet scorecard that prevents promoted strategy changes from making results worse versus the current best baseline
- [ ] Explain, with reproducible diagnostics, why current sizing and backtest parameter options often degrade results
- [ ] Derive and test layered entry/exit logic that better matches transcript-driven trend-following principles
- [ ] Implement improved strategy behavior and promotion rules in the existing backtest/chart stack without breaking current app behavior

### Out of Scope

- Replacing Flask/Jinja or introducing a frontend build pipeline — this feature should fit the current architecture
- Shipping a hosted SaaS version or authentication — current app remains local-first
- Live trading, broker integration, or intraday execution infrastructure — this milestone is still offline backtesting and analysis
- Global portfolio construction across arbitrary ticker universes — scope is the fixed focus basket plus the current strategy stack
- Treating the transcript text as verbatim UI copy — the corpus should remain distilled into structured knowledge and strategy rules

## Context

The existing codebase is a brownfield Flask app with substantial indicator and backtesting logic already in `lib/`, route orchestration in `routes/`, and global-script frontend behavior under `static/js/`. GSD codebase mapping is available in `.planning/codebase/`.

Important implementation context:
- `routes/chart.py` computes indicator bundles, backtests, and JSON payloads for the main chart endpoint.
- `lib/technical_indicators.py`, `lib/backtesting.py`, and `lib/trend_ribbon_profile.py` are the core strategy modules likely affected by a ribbon variant.
- `audio/` contains 75 transcript text files from *Trend Following, 5th Edition* that should be ingested/read in chapter order and distilled into a reusable knowledge base.
- `templates/partials/signal_chips.html`, `templates/partials/backtest_panel.html`, and `static/js/chart_*.js` define how strategies appear and toggle in the UI.
- Tests already exist for routes, backtesting, indicators, support/resistance, optimizer behavior, and Playwright UI flows.
- Current concerns documented in `.planning/codebase/CONCERNS.md` include dependency drift, broad exception handling, frontend globals, and duplicated interval/backtest logic.
- The milestone focus basket is `BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, and `GOOG`, and milestone success should be measured against that shared set rather than ticker-by-ticker anecdotes.

## Constraints

- **Tech stack**: Stay within Flask, pandas, yfinance/FRED, Jinja templates, and plain browser JS/CSS — this repo has no JS bundler/module pipeline.
- **Compatibility**: Existing strategy keys, payload shape, and UI flows should continue working — users rely on current overlays/watchlist/backtest behavior.
- **Data correctness**: Respect warmup/lookback handling, ticker normalization, and interval resampling patterns already in use — chart and optimizer outputs should stay aligned.
- **Testability**: Add/adjust pytest and targeted frontend/UI coverage for the new strategy — current workflows depend on these tests for confidence.
- **Local-first storage**: Keep persistence under `lib.paths.get_user_data_path(...)` when new state or cache artifacts are needed — desktop/source runs must both work.
- **Ratcheting**: New strategy variants should be compared against an explicit current-best baseline across the focus basket before being considered an improvement.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Keep this as a brownfield GSD project initialized from the existing codebase map | We need phase workflows to understand current architecture before changing strategy code | Validated in v1.0 |
| Make transcript ingestion and trend-following knowledge extraction the first phase before strategy implementation | The user clarified that the real output starts with learning from the `audio/` text corpus | Validated in v1.0 |
| Derive strategy rules from the extracted knowledge base before coding indicator/backtest changes | This keeps implementation tied to corpus-backed trend-following principles | Validated in v1.0 |
| Use existing Flask/Jinja/plain-JS architecture rather than adding a frontend build step | The current repo is intentionally lightweight and script-order based | Validated in v1.0 |
| Use a fixed focus basket (`BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, `GOOG`) for milestone-level strategy evaluation | Strategy changes need a shared benchmark set so "better" means the same thing every time | Active |
| Add a ratchet gate so strategy changes only become the new baseline if they improve the agreed benchmark scorecard | The user wants future strategy changes to stop backsliding after a genuine improvement is found | Active |
| Prioritize layered entries/exits and drawdown control over all-in/all-out behavior and sizing toggles that have historically worsened results | The current all-in behavior and naive sizing knobs are not meeting the desired trend-following behavior | Active |

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
*Last updated: 2026-04-07 for milestone v1.1 Strategy Ratchet Optimization*
