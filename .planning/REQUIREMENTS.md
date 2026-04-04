# Requirements: TriedingView

**Defined:** 2026-04-04
**Core Value:** The strategy should be grounded in what the `audio/` transcripts actually say about trend following, not just manually invented indicator tweaks.

## v1 Requirements

### Corpus Knowledge Extraction

- [x] **KB-01**: All transcript `.txt` files in `audio/` are read in a deterministic order and processed into a structured trend-following knowledge base
- [x] **KB-02**: The knowledge base captures strategy-relevant concepts such as entry/exit principles, position sizing, risk control, drawdown discipline, trend persistence, whipsaw handling, and market regime assumptions
- [x] **KB-03**: Extracted knowledge is saved in a reusable artifact that can be inspected, cited back to source transcript files/chapters, and used as the basis for strategy design

### Strategy Synthesis And Implementation

- [ ] **STRAT-01**: A concrete trend-following strategy specification is derived from the knowledge base before implementation begins
- [ ] **STRAT-02**: The derived strategy is implemented in the backend indicator/backtest stack and exposed through `/api/chart`
- [ ] **STRAT-03**: The strategy is selectable/inspectable in the UI with clear naming and explanatory text that reflects the corpus-derived rules
- [ ] **STRAT-04**: Automated tests cover transcript processing, strategy implementation, route payload integration, and regression protection for existing app behavior

### Brownfield Compatibility

- [ ] **COMP-01**: Existing chart, watchlist, financials, and current strategy flows continue working after the new ribbon strategy is added
- [ ] **COMP-02**: Any new config/profile values follow existing path, cache, and serialization conventions documented in `.planning/codebase/`

## v2 Requirements

### Future Strategy Research

- **RIBV2-01**: Run large benchmark/optimizer sweeps for the new ribbon strategy after the initial implementation stabilizes
- **RIBV2-02**: Add richer per-ticker profile selection or automatic regime-aware profile routing if the first variant proves useful

## Out of Scope

| Feature | Reason |
|---------|--------|
| Auth, cloud sync, or a hosted multi-user backend | Not needed for this local-first feature |
| Replacing all existing strategy implementations | Current scope is corpus-derived trend-following strategy design plus one implementation |
| Full frontend architecture migration to a bundler/framework | Too large and unrelated to the strategy feature |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| KB-01 | Phase 1 | Complete |
| KB-02 | Phase 1 | Complete |
| KB-03 | Phase 1 | Complete |
| STRAT-01 | Phase 2 | Pending |
| STRAT-02 | Phase 2 | Pending |
| STRAT-03 | Phase 2 | Pending |
| STRAT-04 | Phase 2 | Pending |
| COMP-01 | Phase 2 | Pending |
| COMP-02 | Phase 2 | Pending |

**Coverage:**
- v1 requirements: 9 total
- Mapped to phases: 9
- Unmapped: 0

---
*Requirements defined: 2026-04-04*
*Last updated: 2026-04-04 after initial definition*
