# Roadmap: TriedingView

## Overview

This milestone focuses on strategy quality rather than first-time strategy implementation. It should establish a fixed benchmark basket, build a ratchet system so real improvements become the new floor, explain why current sizing/backtest knobs degrade results, and implement more trend-following-consistent layered entries/exits that can improve upside capture while limiting major drawdowns.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Build Trend-Following Knowledge Base** - Read the transcript corpus and extract a reusable, source-cited set of trend-following rules and principles.
- [x] **Phase 2: Implement Corpus-Derived Strategy** - Turn the extracted knowledge into a concrete strategy spec, implement it in the existing backend/UI stack without breaking current app behavior. (completed 2026-04-04)
- [x] **Phase 3: Build Ratchet Benchmark And Diagnostics** - Fix the milestone evaluation basket, capture the current-best baseline, and explain why current sizing/backtest options degrade performance. (completed 2026-04-07)
- [x] **Phase 03.1: Lock Polymarket ratchet benchmark** - Freeze the improved BTC Polymarket behavior into a deterministic route-level ratchet before broader strategy changes continue. (completed 2026-04-08)
- [x] **Phase 03.2: Lock Current Strategy Configuration Ratchet** - Freeze the current backtest defaults, option ordering, and `/api/chart` strategy contract so later changes cannot silently drift the current configuration. (completed 2026-04-08)
- [ ] **Phase 4: Design Layered Position Management** - Use transcript principles plus diagnostics to define layered entry/exit behavior and risk controls that are more realistic than all-in/all-out trades.
- [ ] **Phase 5: Implement And Promote Improved Strategy Variants** - Ship the best validated improvements, enforce the ratchet gate, and verify the focus basket results against buy-and-hold and drawdown goals.

## Phase Details

### Phase 1: Build Trend-Following Knowledge Base
**Goal**: Read every transcript text file under `audio/`, extract the recurring trend-following concepts/rules/constraints, and write a structured knowledge-base artifact that cites source files/chapters and can drive strategy design.
**Depends on**: Nothing (first phase)
**Requirements**: [Historical milestone v1.0]
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
**Requirements**: [Historical milestone v1.0]
**Success Criteria** (what must be TRUE):
  1. A strategy specification exists that ties entry/exit/risk rules back to the Phase 1 knowledge base.
  2. The new strategy is available through `/api/chart` and can be selected/backtested in the UI.
  3. Existing chart/watchlist/financials/current-strategy flows continue to work.
  4. Automated tests cover the new strategy and the corpus-driven artifacts it depends on.
**Plans**: 2 plans

Plans:
- [x] 02-01: Derive a strategy spec from the knowledge base and map it onto indicator/backtesting code changes.
- [x] 02-02: Implement backend/UI integration, add tests, and run regression checks.

### Phase 3: Build Ratchet Benchmark And Diagnostics
**Goal**: Establish the fixed focus basket (`BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, `GOOG`), capture the current-best baseline, and produce reproducible diagnostics for why current sizing and backtest parameter options make results worse.
**Depends on**: Phase 2
**Requirements**: [RATCHET-01, RATCHET-02, DIAG-01, DIAG-02, DIAG-03, COMP-04]
**Success Criteria** (what must be TRUE):
  1. A repeatable benchmark harness evaluates the full focus basket with consistent settings and outputs.
  2. The current-best baseline is stored in a form that later strategy variants can be compared against.
  3. Diagnostics explain where vol-normalized sizing, fixed-fraction sizing, and current parameter toggles degrade results.
  4. The resulting analysis is specific enough to guide the next phase's strategy design instead of generic optimization advice.
**Plans**: 2 plans

Plans:
- [x] 03-01: Build the focus-basket benchmark workflow and baseline artifact for current strategy results.
- [x] 03-02: Diagnose performance degradation from sizing and backtest parameters, and summarize the failure modes.

### Phase 03.1: Lock Polymarket ratchet benchmark (INSERTED)

**Goal**: Freeze the newly improved BTC Polymarket strategy behavior into a deterministic benchmark artifact and regression guard before broader strategy work continues.
**Depends on**: Phase 3
**Requirements**: [RATCHET-03, COMP-03]
**Success Criteria** (what must be TRUE):
  1. The improved Polymarket BTC result is pinned behind a fixture-backed route-level regression test.
  2. The benchmark uses the real Polymarket history window starting `2025-08-08`, not a misleading longer flat-history span.
  3. The baseline artifacts document that the promoted behavior preserves the relevance-weighted signal path rather than raw aggregate skew.
  4. Existing app flows continue working while the benchmark guard is added.
**Plans:** 1 plan

Plans:
- [x] 03.1-01: Freeze deterministic Polymarket fixtures, add the route-level ratchet test, and document the promoted BTC baseline.

### Phase 03.2: Lock Current Strategy Configuration Ratchet (INSERTED)

**Goal**: Freeze the current backtest configuration surface so defaults, option ordering, and the backend strategy inventory cannot silently drift while later strategy work continues.
**Depends on**: Phase 03.1
**Requirements**: [RATCHET-03, COMP-03]
**Success Criteria** (what must be TRUE):
  1. A machine-readable spec records the current backtest defaults, strategy selector order, money-management controls, and route strategy inventory.
  2. A deterministic pytest guard proves `/backtest`, the JS default strategy, and `/api/chart` still match that current config contract.
  3. The strengthened ratchet reuses frozen BTC and Polymarket fixtures instead of live data.
  4. Completing the phase does not change the current baseline; it only makes future drift explicit.
**Plans:** 1 plan

Plans:
- [x] 03.2-01: Freeze the current config contract, add deterministic template/JS/route ratchet tests, and document the baseline.

### Phase 4: Design Layered Position Management
**Goal**: Translate transcript-derived trend-following principles and Phase 3 diagnostics into a concrete strategy design that layers into and out of positions while protecting against major drawdowns.
**Depends on**: Phase 3
**Requirements**: [STRAT-05, STRAT-06]
**Success Criteria** (what must be TRUE):
  1. A strategy specification describes how positions scale in and out instead of flipping only between fully invested and fully flat.
  2. The design explicitly ties layering, exits, and risk controls back to transcript-derived trend-following principles.
  3. The plan identifies which candidate changes should be tested first based on expected benchmark impact and implementation complexity.
**Plans**: 2 plans

Plans:
- [ ] 04-01: Specify layered entry/exit rules, risk controls, and promotion metrics based on transcript principles.
- [ ] 04-02: Convert the strategy design into concrete implementation tasks and validation criteria.

### Phase 5: Implement And Promote Improved Strategy Variants
**Goal**: Implement the highest-confidence strategy improvements, enforce the ratchet promotion rules, and verify that promoted variants improve the focus basket versus the current baseline and buy-and-hold benchmarks without breaking existing behavior.
**Depends on**: Phase 4
**Requirements**: [RATCHET-03, STRAT-07, COMP-03]
**Success Criteria** (what must be TRUE):
  1. The chosen strategy improvements are implemented in the existing backtest/chart stack with tests.
  2. A ratchet gate prevents regressions from becoming the new promoted baseline.
  3. Verification reports compare the promoted result to the prior baseline and to buy-and-hold for the focus basket.
  4. Existing app behavior outside the intended strategy changes continues to work.
**Plans**: 2 plans

Plans:
- [ ] 05-01: Implement the selected strategy and ratchet-system code changes with regression coverage.
- [ ] 05-02: Verify focus-basket results against baseline and buy-and-hold, then document the promoted baseline.

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 3.1 -> 3.2 -> 4 -> 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Build Trend-Following Knowledge Base | 2/2 | Complete | 2026-04-04 |
| 2. Implement Corpus-Derived Strategy | 2/2 | Complete | 2026-04-04 |
| 3. Build Ratchet Benchmark And Diagnostics | 2/2 | Complete | 2026-04-07 |
| 3.1. Lock Polymarket ratchet benchmark | 1/1 | Complete | 2026-04-08 |
| 3.2. Lock Current Strategy Configuration Ratchet | 1/1 | Complete | 2026-04-08 |
| 4. Design Layered Position Management | 0/2 | Planned | — |
| 5. Implement And Promote Improved Strategy Variants | 0/2 | Not Started | — |
