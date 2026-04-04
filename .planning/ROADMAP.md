# Roadmap: TriedingView

## Overview

This milestone adds one new ribbon strategy variant to the existing TriedingView stack without replacing the current Trend Ribbon baseline. The work should first clarify strategy semantics, then implement backend signal/backtest support, wire the strategy into the chart and backtest UI, and finish by proving existing flows still work and the new strategy has regression coverage.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: New Ribbon Strategy Variant** - Define, implement, expose, and test the new ribbon strategy while preserving the existing baseline.

## Phase Details

### Phase 1: New Ribbon Strategy Variant
**Goal**: Add a second ribbon strategy variant end-to-end so it can be selected, visualized, and backtested in the existing app while the current Trend Ribbon remains available for comparison.
**Depends on**: Nothing (first phase)
**Requirements**: [RIB-01, RIB-02, RIB-03, RIB-04, COMP-01, COMP-02]
**Success Criteria** (what must be TRUE):
  1. User can select the new ribbon strategy in the backtest UI and receive a valid strategy report for a ticker/date range.
  2. User can still select the existing Trend Ribbon baseline and get the same kind of chart/backtest experience as before.
  3. `/api/chart` returns the new strategy's series/direction/backtest payload without breaking existing strategy keys or current consumers.
  4. Automated tests cover the new strategy's indicator output, route payload integration, and preservation of existing strategy/watchlist/chart behavior.
  5. Any new config/profile values follow the repo's current cache/path/serialization conventions and are documented in code/UI copy where needed.
**Plans**: 3 plans

Plans:
- [ ] 01-01: Decide the new ribbon strategy's exact signal semantics, parameters, and UI naming/overlay behavior, then capture those decisions before coding.
- [ ] 01-02: Implement backend indicator/profile/backtest support and extend `/api/chart` payloads while keeping the baseline Trend Ribbon intact.
- [ ] 01-03: Wire frontend selector/overlay/help copy, add automated tests, and run regression checks across chart/watchlist/backtest flows.

## Progress

**Execution Order:**
Phases execute in numeric order: 1

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. New Ribbon Strategy Variant | 0/3 | Not started | - |
