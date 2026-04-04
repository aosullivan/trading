---
phase: 02-implement-corpus-derived-strategy
plan: 01
subsystem: planning
tags:
  - corpus-trend
  - donchian
  - atr
requires:
  - phase: 01-build-trend-following-knowledge-base
    provides: Source-cited Phase 1 principle catalog and strategy handoff
provides:
  - Concrete corpus_trend strategy contract
  - Phase 1 principle traceability map for implementation
affects:
  - 02-implement-corpus-derived-strategy
tech-stack:
  added: []
  patterns:
    - Spec-first strategy implementation with explicit rule/default contracts
    - Principle-ID traceability from corpus KB to runtime strategy code
key-files:
  created:
    - .planning/phases/02-implement-corpus-derived-strategy/corpus-trend-strategy-spec.md
  modified: []
key-decisions:
  - "Implement corpus_trend as a long/cash, price-only Donchian breakout plus trailing channel/ATR-stop strategy with 55/20/14/2.0/1.0% defaults."
  - "Keep ribbon as the default strategy and expose corpus_trend as an additive UI/API option."
  - "Treat portfolio-001 as single-ticker reusable rules in v1, not a true multi-ticker allocator."
patterns-established:
  - "Runtime strategy changes must reference Phase 1 principle IDs and preserve existing payload/default-strategy contracts."
requirements-completed:
  - STRAT-01
  - COMP-02
duration: 2 min
completed: 2026-04-04
---

# Phase 02 Plan 01: Corpus-Trend Strategy Spec Summary

**Donchian/ATR corpus_trend contract with long/cash defaults, UI/API payload shape, and principle-ID traceability**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-04T18:24:23Z
- **Completed:** 2026-04-04T18:25:59Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Created `.planning/phases/02-implement-corpus-derived-strategy/corpus-trend-strategy-spec.md` with the exact `corpus_trend` contract, Donchian/ATR defaults, warmup rules, position sizing formula, and route/UI integration shape.
- Added a traceability table mapping implementation choices back to `entry-001`, `exit-001`, `sizing-001`, `risk-001`, `drawdown-001`, `trend-001`, `whipsaw-001`, `portfolio-001`, and `regime-001`.
- Documented the Phase 1 extraction caveat and the v1 single-ticker portfolio limitation so implementation remains honest about what the KB can support.

## Task Commits

1. **Task 1: Write the corpus-trend rule and contract spec** - `7a7c7d5` (docs)
2. **Task 2: Add Phase 1 principle traceability and implementation file map** - `a495641` (docs)

## Files Created/Modified

- `.planning/phases/02-implement-corpus-derived-strategy/corpus-trend-strategy-spec.md` - Strategy rule formulas, defaults, API/UI contract, traceability map, and implementation file map.

## Decisions Made

- Chose a long/cash Donchian 55-bar breakout + 20-bar trailing exit with ATR(14) and 2.0x stop sizing at 1.0% equity risk per entry as the first implementation target.
- Kept `ribbon` as the default backtest strategy and reserved `corpus_trend` as a new additive strategy key.
- Deferred true multi-ticker portfolio allocation and optimization sweeps out of this first implementation pass.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for `02-02`: the implementation spec now names the backend helper functions, route payload key, UI option, exact defaults, and all Phase 1 principle mappings needed for code/test work.

---
*Phase: 02-implement-corpus-derived-strategy*
*Completed: 2026-04-04*
