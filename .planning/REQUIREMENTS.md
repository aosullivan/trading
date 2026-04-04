# Requirements: TriedingView

**Defined:** 2026-04-04
**Core Value:** New trading strategy variants should be testable and visually comparable in the existing chart/backtest UI without breaking current indicators, watchlist flows, or data correctness.

## v1 Requirements

### Ribbon Strategy

- [ ] **RIB-01**: The backend can compute a new ribbon strategy variant and return its series, direction, and backtest outputs from `/api/chart`
- [ ] **RIB-02**: The UI exposes the new ribbon strategy in the strategy selector and, if applicable, as a chart overlay/signal toggle with clear labels
- [ ] **RIB-03**: Existing Trend Ribbon behavior remains available so the new variant can be compared without replacing the baseline
- [ ] **RIB-04**: The new strategy has automated test coverage for indicator output, backtest behavior, and route/UI contract integration

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
| Replacing all existing strategy implementations | Current scope is one new ribbon strategy variant |
| Full frontend architecture migration to a bundler/framework | Too large and unrelated to the strategy feature |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| RIB-01 | Phase 1 | Pending |
| RIB-02 | Phase 1 | Pending |
| RIB-03 | Phase 1 | Pending |
| RIB-04 | Phase 1 | Pending |
| COMP-01 | Phase 1 | Pending |
| COMP-02 | Phase 1 | Pending |

**Coverage:**
- v1 requirements: 6 total
- Mapped to phases: 6
- Unmapped: 0

---
*Requirements defined: 2026-04-04*
*Last updated: 2026-04-04 after initial definition*
