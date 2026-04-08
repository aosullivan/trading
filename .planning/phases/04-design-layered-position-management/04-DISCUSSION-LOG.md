# Phase 4 Discussion Log

**Date:** 2026-04-07
**Mode:** Auto-discuss continuation after Phase 3 execution

## Why Auto-Discuss Was Used

The user asked to continue immediately after Phase 3 execution and diagnostics. The main gray areas were already narrowed by:

- the promoted ratchet benchmark in Phase 3
- the diagnostic finding that current vol/fixed-fraction sizing hurts primarily by collapsing exposure
- the user's earlier requirement for more layering in and out of positions than all-in/all-out

Given that context, the recommended defaults were locked directly into `04-CONTEXT.md` so planning can proceed without re-asking foundational questions.

## Areas Resolved

### 1. Whether Phase 4 should keep the current signal family
- Decision: Yes. Build on `corpus_trend` rather than introducing an unrelated strategy family.
- Reason: The ratchet benchmark and diagnostics are already pinned to the current baseline, so continuity matters.

### 2. What problem layering should solve first
- Decision: Prioritize preserving capital deployment on strong trends while still allowing earlier risk reduction on deterioration.
- Reason: Phase 3 showed that under-participation, not just drawdown, is the current dominant failure mode on the basket leaders.

### 3. Whether layering should mean tiny risk-budget sizing
- Decision: No. Use a small number of meaningful tranches rather than micro-sized volatility or fixed-fraction positions.
- Reason: The Phase 3 diagnostics showed average entry notional collapsing from roughly `233.93%` in the baseline to `4.35%` under vol sizing and around `41.6%` under fixed fraction.

### 4. What should remain deferred
- Decision: Keep flat capital in cash, defer parking assets, and avoid broad optimizer sweeps in this phase.
- Reason: Those additions would muddy the first layered-design comparison against the already promoted Phase 3 baseline.

## Planning Handoff

Phase 4 planning should now produce:

- a layered-entry / layered-exit design spec grounded in transcript principles
- a small candidate set worth implementing first
- validation criteria tied back to the fixed ratchet basket and Phase 3 evidence
