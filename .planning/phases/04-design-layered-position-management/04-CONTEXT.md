# Phase 4: Design Layered Position Management - Context

**Gathered:** 2026-04-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Use the Phase 3 ratchet benchmark and diagnostics to design a transcript-grounded layered position-management variant for `corpus_trend`. This phase should define how to scale into and out of positions, how to preserve exposure during strong trends, and which candidate designs should be tested first. It should not yet promote a new baseline or broaden the benchmark basket.

</domain>

<decisions>
## Implementation Decisions

### Strategy family and continuity
- **D-01:** Phase 4 should build on the existing `corpus_trend` breakout-and-trailing-exit family rather than invent a new unrelated signal stack, so improvements remain traceable to the current promoted baseline.
- **D-02:** The design should keep the current long/cash posture for now. Layering should happen within the long exposure path, not by introducing shorting or a parking asset during this phase.
- **D-03:** The ratchet benchmark from Phase 3 remains the promotion gate. Phase 4 may propose variants, but any implementation plan must still compare them on `BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, and `GOOG`.

### Layered entries
- **D-04:** Replace all-in entries with a staged position model that keeps meaningful capital in strong trends. The starting design target is a three-tranche structure with a core entry and one or two add-on sleeves, rather than many tiny risk-budget lots.
- **D-05:** Add-on rules should reward continued trend confirmation or constructive pullbacks, not merely rising recent volatility. The diagnostics showed that shrinking exposure as volatility rises is the wrong direction on the current focus basket winners.
- **D-06:** Phase 4 should prefer tranche sizing that preserves substantial participation in major winners and avoids the tiny notional sizes seen in `vol_trade`, `vol_monthly`, `vol_capped`, and the more extreme fixed-fraction variants.

### Layered exits and drawdown control
- **D-07:** Exits should also be layered. The design should keep a core sleeve invested until full trend invalidation while allowing partial scale-outs when trend quality weakens.
- **D-08:** Defensive scale-outs should be triggered by explicit rule-based deterioration signals such as trailing-stop pressure, failed add-on conditions, or channel breaks, rather than discretionary drawdown overrides.
- **D-09:** Drawdown discipline remains rule-driven and non-adaptive: do not introduce parameter changes that respond to recent pain or boredom, consistent with `drawdown-001`.

### Evidence and validation priorities
- **D-10:** Candidate designs should be ranked by expected ratchet impact first, not by theoretical elegance. The first design pass should target the specific failure Phase 3 exposed: under-participation in the strongest trends.
- **D-11:** Phase 4 planning should explicitly compare a small number of candidate layering schemes rather than a broad optimizer sweep. The goal is an explainable first improvement, not a giant search space.
- **D-12:** The design must remain grounded in transcript principles `trend-001`, `entry-001`, `exit-001`, `risk-001`, `drawdown-001`, `whipsaw-001`, and `portfolio-001`, while honoring the diagnostic constraint to preserve capital deployment on strong trends.

### the agent's Discretion
- Exact tranche percentages, as long as the first design keeps meaningful exposure and is simple enough to explain and test.
- Whether add-on triggers are breakout continuation, pullback recovery, time-in-trend confirmation, or a small combination of these, as long as they are rule-based and benchmarkable.
- Whether scale-outs are encoded as sleeve liquidation, fractional lot sales, or another trade representation compatible with the existing backtest/report contract.

</decisions>

<specifics>
## Specific Ideas

- The strongest Phase 3 finding was not that risk control is bad, but that the currently exposed implementations of vol sizing and fixed fraction reduce capital deployment too aggressively.
- A reasonable first design target is a `core + add + add` entry structure and a `trim + trim + exit` path on deterioration, because that directly answers the user's request for more layering in and out than all-in/all-out.
- The design should protect against major drawdowns by reducing exposure earlier than a full invalidation exit, but without collapsing the entire position too early on the names that trend the best.
- Cash remains the flat-state baseline in this phase; index-tracker parking stays deferred.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone scope and current evidence
- `.planning/PROJECT.md` — Milestone v1.1 goal and ratchet-improvement intent.
- `.planning/REQUIREMENTS.md` — Phase 4 requirements `STRAT-05` and `STRAT-06`, plus the downstream relationship to `STRAT-07`.
- `.planning/ROADMAP.md` — Phase 4 goal, success criteria, and plan split.
- `.planning/STATE.md` — Current project position after Phase 3 completion.

### Prior phase artifacts
- `.planning/phases/02-implement-corpus-derived-strategy/corpus-trend-strategy-spec.md` — Current strategy contract that the layered design should evolve rather than replace.
- `.planning/phases/03-build-ratchet-benchmark-and-diagnostics/03-01-SUMMARY.md` — Established baseline and ratchet benchmark artifact set.
- `.planning/phases/03-build-ratchet-benchmark-and-diagnostics/03-02-SUMMARY.md` — Diagnostic conclusions and Phase 4 constraints.
- `.planning/phases/03-build-ratchet-benchmark-and-diagnostics/focus-basket-baseline.md` — Promoted baseline metrics for the fixed basket.
- `.planning/phases/03-build-ratchet-benchmark-and-diagnostics/focus-basket-diagnostics.md` — Why current sizing/backtest knobs underperform and what must not be repeated.

### Transcript grounding
- `.planning/phases/01-build-trend-following-knowledge-base/trend-following-knowledge-base.md` — Human-readable principle catalog and strategy implications.
- `.planning/phases/01-build-trend-following-knowledge-base/trend-following-knowledge-base.json` — Machine-readable principle IDs and strategy handoff.

### Existing codebase surfaces
- `lib/backtesting.py` — current lot/trade accounting, ribbon accumulation precedent, and money-management behavior to either reuse or explicitly avoid.
- `routes/chart.py` — `/api/chart` contract and strategy payload shapes.
- `tests/test_backtest.py` — existing trade semantics and backtest behavior expectations.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `lib/backtesting.py` already contains `backtest_ribbon_accumulation(...)`, which is the clearest local precedent for multi-lot entries, partial exits, and contribution-aware equity curves.
- `backtest_corpus_trend(...)` and `_run_corpus_trend_backtest(...)` already provide the current baseline route/backtest wiring that a layered variant can extend or parallel without changing the external contract.
- The Phase 3 benchmark/diagnostic scripts now provide a deterministic way to compare candidate layering designs against the promoted baseline before implementation promotion.

### Established Patterns
- The repo expects strategy comparisons to flow through `/api/chart` and route payloads, not a separate hidden scoring engine.
- Trade objects already support quantity-based accounting, which is compatible with multi-tranche entries and staged exits if the implementation keeps the current trade schema.
- The app already has a precedent for accumulation behavior in ribbon backtests, so layering is not alien to the codebase even though `corpus_trend` is currently all-in/all-out.

### Integration Points
- Phase 4 planning will likely touch `lib/backtesting.py`, `routes/chart.py`, and the Phase 3 benchmark/diagnostic scripts to define what a layered `corpus_trend` variant should look like and how it will be evaluated.
- If a new strategy key is introduced for comparison, Phase 5 must preserve the current payload conventions and keep the benchmark scripts in sync.
- If the layered design instead upgrades `corpus_trend` in place, Phase 5 must be especially clear about ratchet promotion and baseline replacement semantics.

</code_context>

<deferred>
## Deferred Ideas

- Parking flat capital in an index tracker or other sleeve remains deferred until after the first layered design is benchmarked against cash.
- Large optimizer sweeps across many tranche schedules or parameter grids remain out of scope for this phase.
- Cross-ticker portfolio allocation beyond the single-strategy fixed basket is still a later milestone concern.

</deferred>

---

*Phase: 04-design-layered-position-management*
*Context gathered: 2026-04-07*
