# Roadmap: TriedingView

## Overview

This milestone starts by reading the transcript corpus in `audio/` and distilling it into a structured trend-following knowledge base, then uses that extracted knowledge to define and implement a concrete strategy in the existing TriedingView backtest/chart stack. The roadmap should preserve a clean separation between “learn from corpus” and “code the strategy from that learning.”

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Build Trend-Following Knowledge Base** - Read the transcript corpus and extract a reusable, source-cited set of trend-following rules and principles.
- [ ] **Phase 2: Implement Corpus-Derived Strategy** - Turn the extracted knowledge into a concrete strategy spec, implement it, expose it in the UI/API, and regression-test existing flows.

## Phase Details

### Phase 1: Build Trend-Following Knowledge Base
**Goal**: Read every transcript text file under `audio/`, extract the recurring trend-following concepts/rules/constraints, and write a structured knowledge-base artifact that cites source files/chapters and can drive strategy design.
**Depends on**: Nothing (first phase)
**Requirements**: [KB-01, KB-02, KB-03]
**Success Criteria** (what must be TRUE):
  1. All chapter transcript `.txt` files in `audio/` are processed in a repeatable order.
  2. A human-readable knowledge-base artifact exists and summarizes corpus-backed trend-following principles with source references.
  3. The artifact explicitly captures strategy-relevant decisions/constraints such as entries, exits, position sizing, drawdown/risk rules, and whipsaw handling.
  4. The output is structured enough to serve as direct input to the next phase's strategy specification.
**Plans**: 2 plans

Plans:
- [x] 01-01: Design the transcript ingestion and knowledge-base schema/output format, including source citation and chapter ordering.
- [x] 01-02: Read the `audio/` transcript files, extract the trend-following concepts into the knowledge base, and verify the artifact is complete enough for strategy synthesis.

### Phase 2: Implement Corpus-Derived Strategy
**Goal**: Use the Phase 1 knowledge base to define a concrete trend-following strategy and implement it in the existing backend/UI stack without breaking current app behavior.
**Depends on**: Phase 1
**Requirements**: [STRAT-01, STRAT-02, STRAT-03, STRAT-04, COMP-01, COMP-02]
**Success Criteria** (what must be TRUE):
  1. A strategy specification exists that ties entry/exit/risk rules back to the Phase 1 knowledge base.
  2. The new strategy is available through `/api/chart` and can be selected/backtested in the UI.
  3. Existing chart/watchlist/financials/current-strategy flows continue to work.
  4. Automated tests cover the new strategy and the corpus-driven artifacts it depends on.
**Plans**: 2 plans

Plans:
- [ ] 02-01: Derive a strategy spec from the knowledge base and map it onto indicator/backtesting code changes.
- [ ] 02-02: Implement backend/UI integration, add tests, and run regression checks.

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Build Trend-Following Knowledge Base | 2/2 | Complete | 2026-04-04 |
| 2. Implement Corpus-Derived Strategy | 0/2 | Not started | - |
