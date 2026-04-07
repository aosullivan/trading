# Phase 3: Build Ratchet Benchmark And Diagnostics - Context

**Gathered:** 2026-04-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish the fixed focus basket (`BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, `GOOG`), capture the current-best baseline, and produce reproducible diagnostics for why current sizing and backtest parameter options make results worse. This phase defines the benchmark gate and the diagnostic outputs; it does not yet redesign the strategy logic itself.

</domain>

<decisions>
## Implementation Decisions

### Ratchet scorecard and promotion gate
- **D-01:** Define a ratchet scorecard that compares every candidate against the current promoted baseline on the full seven-ticker basket, not on a single favorite ticker.
- **D-02:** Treat aggregate improvement as necessary but not sufficient: a candidate should only be promotable if the basket-level score improves and no ticker suffers a major regression in max drawdown or buy-and-hold-relative return.
- **D-03:** Use the ratchet gate to preserve progress rather than chase unstable one-off wins. A result that improves one ticker while materially worsening others should be rejected rather than becoming the new baseline.

### Basket evaluation rules
- **D-04:** Use the fixed equal-weight focus basket `BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, and `GOOG` for milestone-level evaluation.
- **D-05:** Require broad participation in improvements: the first-pass benchmark should favor changes that improve at least 5 of the 7 focus tickers while avoiding obvious failures on the remaining names.
- **D-06:** Compare promoted variants against both the prior promoted baseline and buy-and-hold, because the user wants better upside capture without simply optimizing internal metrics that still lag passive exposure.

### Out-of-market and baseline assumptions
- **D-07:** For Phase 3, treat out-of-market capital as cash when benchmarking and diagnostics are run, rather than introducing a parking asset or synthetic index sleeve during this phase.
- **D-08:** Keep the current `corpus_trend` implementation as the starting baseline artifact that future candidates must beat, even if diagnostics reveal weaknesses in its current sizing and exit behavior.

### Diagnostic priorities
- **D-09:** Phase 3 must explicitly explain why vol-normalized sizing has been making results worse in the current stack.
- **D-10:** Phase 3 must explicitly explain why fixed-fraction sizing has been making results worse in the current stack.
- **D-11:** Phase 3 must audit other currently exposed backtest knobs that may be degrading outcomes, especially stop/exit sensitivity, compounding mode, and any parameter choices that increase churn or truncate trend capture.
- **D-12:** Diagnostic outputs should be reproducible and artifact-backed so future strategy decisions can point to evidence instead of repeating ad hoc experiments.

### the agent's Discretion
- Exact benchmark artifact format, as long as it is easy to diff and supports ratchet comparisons over time.
- Exact basket score formula, as long as it combines return strength, drawdown discipline, and buy-and-hold comparison in a way that honors the gate above.
- Whether the benchmark harness lives as pytest fixtures, CLI scripts, or both, as long as the results are repeatable and planning can clearly see how to run them.

</decisions>

<specifics>
## Specific Ideas

- The user wants strategy work to "only get better" after a genuine improvement is found, not oscillate between better and worse variants.
- The focus basket for all milestone evaluation is `BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, and `GOOG`.
- The user believes the current strategy stack needs more layered scaling in and out of positions rather than all-in/all-out behavior, but that redesign belongs to the next phase after diagnostics.
- The user specifically called out vol-normalized sizing, fixed-fraction sizing, and "other backtesting parameters" as things that currently make results worse and need explanation.
- The target outcome is to beat buy-and-hold using transcript-grounded trend-following principles while avoiding major drawdowns.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone scope and success criteria
- `.planning/PROJECT.md` — Milestone v1.1 goal, focus basket, ratchet intent, and non-negotiable constraints.
- `.planning/REQUIREMENTS.md` — Phase 3 requirements `RATCHET-01`, `RATCHET-02`, `DIAG-01`, `DIAG-02`, `DIAG-03`, and `COMP-04`.
- `.planning/ROADMAP.md` — Phase 3 goal, success criteria, and the split between benchmark/baseline work and diagnostics.
- `.planning/STATE.md` — Current milestone status and the open concern that the ratchet scorecard still needed definition.

### Prior strategy grounding
- `.planning/phases/01-build-trend-following-knowledge-base/trend-following-knowledge-base.md` — Transcript-derived trend-following principles that Phase 3 diagnostics must continue to respect.
- `.planning/phases/01-build-trend-following-knowledge-base/trend-following-knowledge-base.json` — Machine-readable principle and strategy handoff data.
- `.planning/phases/02-implement-corpus-derived-strategy/corpus-trend-strategy-spec.md` — Current `corpus_trend` rule set and its intended rationale.
- `.planning/phases/02-implement-corpus-derived-strategy/02-CONTEXT.md` — Locked decisions from the initial corpus-driven strategy implementation.
- `.planning/phases/02-implement-corpus-derived-strategy/02-UAT.md` — Most recent manual verification notes for the current strategy milestone.

### Existing benchmark and regression references
- `docs/benchmark-backtests.md` — Existing pinned benchmark pattern that already enforces "do not get worse" semantics for BTC strategies in CI.
- `tests/test_btc_benchmark_backtests.py` — Existing endpoint-level benchmark guard that can inspire the new cross-ticker ratchet harness.
- `tests/fixtures/btc_benchmark_backtests.json` — Example persisted benchmark threshold artifact format already used by the repo.
- `tests/test_strategy_regression.py` — Deterministic strategy regression coverage complementary to market-window benchmarks.

### Codebase conventions and test context
- `.planning/codebase/CONVENTIONS.md` — API, persistence, and backtest data-shape conventions Phase 3 should follow.
- `.planning/codebase/TESTING.md` — Existing benchmark, route, and backtest test entry points relevant to the benchmark harness.
- `.planning/codebase/CONCERNS.md` — Known codebase risks to avoid when adding benchmark and diagnostic machinery.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `lib/backtesting.py`: contains `MoneyManagementConfig`, `backtest_direction`, `backtest_managed`, `build_equity_curve`, `build_buy_hold_equity_curve`, and risk metric helpers that Phase 3 can reuse for apples-to-apples comparisons.
- `routes/chart.py`: already exposes `/api/chart` query parameters for money-management knobs (`mm_sizing`, `mm_stop`, `mm_stop_val`, `mm_risk_cap`, `mm_compound`) and returns strategy summaries plus buy-and-hold curves from the same engine the UI uses.
- `docs/benchmark-backtests.md` plus `tests/test_btc_benchmark_backtests.py`: demonstrate an existing pinned-floor regression pattern that maps well to the desired ratchet concept.
- `lib/portfolio_backtesting.py`: provides a portfolio-style harness that may inform future multi-ticker comparison work, but Phase 3 should stay focused on consistent evaluation rather than introduce new capital-allocation behavior.

### Established Patterns
- The repo already guards selected strategies by hitting `/api/chart` with fixed params and frozen data rather than relying on live downloads; Phase 3 should preserve that repeatable-testing pattern where possible.
- Buy-and-hold comparisons are already derived from the same visible window and returned in the route payload, so benchmark comparisons should avoid inventing a second incompatible baseline calculation.
- Writable benchmark artifacts and fixtures should follow the repo's file-based, inspectable style instead of hiding state in opaque caches.

### Integration Points
- Benchmark harness logic will likely touch `routes/chart.py`, supporting scripts under `scripts/`, and pytest coverage under `tests/`.
- Diagnostic analysis will likely need to exercise `lib/backtesting.py` money-management paths and compare them against the current `corpus_trend` route payload coming from `routes/chart.py`.
- If Phase 3 persists promoted baselines or scorecards, those artifacts should live in repo-visible fixtures or planning docs, with writable runtime data using `get_user_data_path(...)` only if truly necessary.

</code_context>

<deferred>
## Deferred Ideas

- Layered entries and exits are explicitly deferred to Phase 4, after Phase 3 explains current failure modes and defines the ratchet gate.
- Parking capital in an index tracker or other non-cash sleeve while flat is deferred beyond Phase 3; the immediate benchmark baseline should stay in cash for clarity.
- Ideas from the general todo file such as inverse strategies, Pelosi/Cramer trackers, AI chat iteration, and cross-strategy consensus are outside this milestone phase.

### Reviewed Todos (not folded)
- `Test index tracker parking when out of market vs cash` — relevant to future portfolio/parking design, but deferred because Phase 3 should keep out-of-market handling in cash while the baseline and diagnostics are stabilized.
- `general.md` brainstorming notes — reviewed and left out of scope because they introduce new capabilities rather than clarify the benchmark/diagnostic phase.

</deferred>

---

*Phase: 03-build-ratchet-benchmark-and-diagnostics*
*Context gathered: 2026-04-07*
