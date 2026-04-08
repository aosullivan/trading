# Requirements: TriedingView

**Defined:** 2026-04-07
**Core Value:** Strategy changes should stay grounded in the `audio/` transcripts' trend-following principles and only be promoted when they measurably improve the ratchet benchmark across the focus basket without introducing avoidable regressions.

## v1 Requirements

### Ratchet Benchmarking

- [x] **RATCHET-01**: Backtest evaluation uses a fixed focus basket of `BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, and `GOOG`
- [x] **RATCHET-02**: The project stores a repeatable current-best baseline artifact or scorecard for the focus basket so candidate changes can be compared against it
- [ ] **RATCHET-03**: Strategy improvements are only promoted when they do not regress the agreed benchmark scorecard across the focus basket

### Strategy Diagnostics

- [x] **DIAG-01**: Backtest analysis explains why vol-normalized sizing and fixed-fraction sizing are currently making results worse
- [x] **DIAG-02**: Backtest analysis explains which existing strategy/backtest parameters degrade performance and under what conditions
- [x] **DIAG-03**: Diagnostic outputs are reproducible enough to support future ratchet decisions rather than one-off observations

### Strategy Improvement

- [ ] **STRAT-05**: Strategy behavior supports layered entries and layered exits instead of relying solely on all-in/all-out position changes
- [ ] **STRAT-06**: Strategy changes continue to reflect transcript-derived trend-following principles around trend capture, whipsaw handling, and drawdown discipline
- [ ] **STRAT-07**: Promoted strategy variants aim to beat buy-and-hold on the focus basket while reducing major drawdowns versus the current baseline

### Brownfield Compatibility

- [ ] **COMP-03**: Existing chart, watchlist, financials, optimizer, and current strategy flows continue working after ratchet and strategy changes are added
- [x] **COMP-04**: Any new benchmark/profile/baseline values follow existing path, cache, and serialization conventions documented in `.planning/codebase/`

## v2 Requirements

### Future Strategy Research

- **OPTV2-01**: Expand the ratchet basket or weighting model beyond the initial focus set once the first benchmark gate is stable
- **OPTV2-02**: Add richer regime detection or per-ticker adaptation if the benchmark harness shows consistent benefit
- **OPTV2-03**: Add deeper portfolio-level capital allocation once single-strategy ratcheting is trustworthy

## Out of Scope

| Feature | Reason |
|---------|--------|
| Auth, cloud sync, or a hosted multi-user backend | Not needed for this local-first feature |
| Live trading, broker execution, or intraday order management | This milestone is about offline backtest quality and benchmarking |
| Full frontend architecture migration to a bundler/framework | Too large and unrelated to the strategy feature |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| RATCHET-01 | Phase 3 | Complete |
| RATCHET-02 | Phase 3 | Complete |
| RATCHET-03 | Phase 5 | Pending |
| DIAG-01 | Phase 3 | Complete |
| DIAG-02 | Phase 3 | Complete |
| DIAG-03 | Phase 3 | Complete |
| STRAT-05 | Phase 4 | Pending |
| STRAT-06 | Phase 4 | Pending |
| STRAT-07 | Phase 5 | Pending |
| COMP-03 | Phase 5 | Pending |
| COMP-04 | Phase 3 | Complete |

**Coverage:**
- v1 requirements: 11 total
- Mapped to phases: 11
- Unmapped: 0

---
*Requirements defined: 2026-04-07*
*Last updated: 2026-04-07 for milestone v1.1 Strategy Ratchet Optimization*
