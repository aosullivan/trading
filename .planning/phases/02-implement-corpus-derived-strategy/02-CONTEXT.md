# Phase 2: Implement Corpus-Derived Strategy - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Use the Phase 1 trend-following knowledge base to derive one concrete, source-cited strategy spec, implement that strategy in the existing chart/backtest stack, expose it through `/api/chart` and the backtest UI, and add automated regression tests. This phase should not replace the existing `ribbon` default strategy or introduce unrelated optimizer/regime-routing features.

</domain>

<decisions>
## Implementation Decisions

### Strategy family and first implementation target
- **D-01:** Implement one new strategy key, separate from `ribbon`, so existing workflows stay intact and users can compare the corpus-derived strategy against current strategies.
- **D-02:** Use a price-only trend-following rule set as the first implementation because `entry-001`, `trend-001`, and `regime-001` all argue against macro/fundamental filters.
- **D-03:** Default the new strategy spec toward a Donchian-style breakout entry plus systematic trailing/channel exit, because that is the most direct fit for the Phase 1 handoff and the existing code already has Donchian/channel primitives.
- **D-04:** Prefer a medium/long lookback and slower churn profile over fast tactical flipping so whipsaws are treated as an accepted cost rather than something to over-optimize away.

### Position sizing, risk, and drawdown behavior
- **D-05:** Encode volatility/risk-aware position sizing in the new strategy's backtest path, rather than reusing only all-in/all-out fixed-capital trades, so `sizing-001` and `risk-001` materially affect the strategy implementation.
- **D-06:** Keep drawdown discipline explicit in reporting and avoid adding adaptive parameter changes triggered by recent drawdowns, matching `drawdown-001`.
- **D-07:** If portfolio-level risk controls are hard to express in the current single-ticker backtest API, start with per-trade ATR/volatility sizing and document portfolio-level diversification as a known limitation of the first implementation.

### UI/API integration
- **D-08:** Add the new strategy to the existing `strategies` payload under a stable key such as `corpus_trend`, with `trades`, `summary`, `equity_curve`, and a `buy_hold_equity_curve` when available, matching the current API contract.
- **D-09:** Append a clearly named strategy option in `templates/partials/backtest_panel.html` with copy that reflects the corpus-derived rule family, but keep `BT_DEFAULT_STRATEGY='ribbon'` unchanged in `static/js/backtest_panel.js`.
- **D-10:** Do not introduce a separate frontend state model for this strategy; reuse the existing strategy-select/report flow and keep UI changes minimal.

### Specification and traceability
- **D-11:** Before code implementation, write a Phase 2 strategy spec artifact under `.planning/phases/02-implement-corpus-derived-strategy/` that maps each rule choice back to Phase 1 principle IDs and citations from `trend-following-knowledge-base.md`.
- **D-12:** Tests should verify both behavior and traceability: route payload inclusion, non-empty trade/summary structure on synthetic data, UI option presence, and that the implementation spec references the relevant Phase 1 principle IDs.

### the agent's Discretion
- Exact strategy key and display name, as long as they are stable, descriptive, and do not collide with existing strategy IDs.
- Exact breakout/exit lookback values and ATR/risk-budget defaults, as long as they stay price-only, medium/long-horizon, and are justified in the Phase 2 spec.
- Whether to add a dedicated helper module for the new strategy/backtest or keep the implementation inside existing `lib/` modules, as long as route/API contracts remain consistent.
- Whether lightweight chart overlays are worth adding in the first pass; if overlay work creates too much UI coupling, prioritize backtest/report correctness and keep overlays deferred.

</decisions>

<specifics>
## Specific Ideas

- The Phase 1 KB handoff says the first strategy should start from `price_breakout_or_moving_average_entries`, `systematic_trailing_or_channel_exits`, and `volatility_scaled_cross_market_portfolio`.
- The user explicitly wants the strategy to come from the transcript learning artifact, not from manually inventing another indicator variant.
- Assumption made in this context pass: Donchian/channel-style breakout + trailing exit is the first concrete implementation family, because it is easier to explain, already partially supported by existing code, and aligns with the KB's price-only/long-horizon stance.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Scope and requirements
- `.planning/PROJECT.md` — Product goal and user clarification that transcript-derived strategy design is the core outcome.
- `.planning/REQUIREMENTS.md` — Phase 2 requirements `STRAT-01` through `COMP-02`.
- `.planning/ROADMAP.md` — Phase 2 scope, success criteria, and two-plan split.
- `.planning/STATE.md` — Current execution position and project continuity notes.

### Phase 1 handoff artifacts
- `.planning/phases/01-build-trend-following-knowledge-base/trend-following-knowledge-base.md` — Human-readable principle catalog and strategy design implications.
- `.planning/phases/01-build-trend-following-knowledge-base/trend-following-knowledge-base.json` — Machine-readable principles and `strategy_handoff` rule map.
- `.planning/phases/01-build-trend-following-knowledge-base/01-02-SUMMARY.md` — Phase 1 implementation choices and caveat that extraction is a deterministic first pass.
- `.planning/phases/01-build-trend-following-knowledge-base/01-CONTEXT.md` — Source-traceability and corpus-grounding decisions that should carry into Phase 2.

### Existing codebase context
- `.planning/codebase/STRUCTURE.md` — Files likely to change for strategy implementation and UI/API integration.
- `.planning/codebase/CONVENTIONS.md` — Existing API, data-shape, naming, and persistence conventions.
- `.planning/codebase/TESTING.md` — Test entry points and existing fixture coverage.
- `.planning/codebase/CONCERNS.md` — Contract-coupling and regression risks when adding a strategy.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `lib/technical_indicators.py`: existing Donchian, MA, ATR-derived, and direction-series patterns can seed the corpus-derived signal implementation.
- `lib/backtesting.py`: `compute_summary`, `build_equity_curve`, and the existing trade object shape should be preserved; a new backtest helper can extend sizing/risk behavior.
- `routes/chart.py`: strategy payload assembly already returns a `strategies` map that can host a new `corpus_trend` entry without changing the top-level response shape.
- `templates/partials/backtest_panel.html` and `static/js/backtest_panel.js`: strategy selection already flows through the `<select>` value and report rendering, so a new option can be added with minimal frontend code.
- `tests/test_routes.py` and `tests/test_ui.py`: existing assertions around strategy keys/options should be extended rather than replaced.

### Established Patterns
- Indicators return Pandas series plus direction series where `1` means long and non-`1` means flat/bearish in the current long-only backtest engine.
- `/api/chart` computes all strategy backtests server-side and returns each strategy as `{trades, summary, equity_curve, buy_hold_equity_curve?}`.
- Frontend strategy switching depends on a stable key in the payload and a matching `<option value="...">`.

### Integration Points
- Add the new signal/backtest implementation in `lib/technical_indicators.py` and/or `lib/backtesting.py`.
- Wire the new strategy into `_get_indicator_bundle(...)` and the final `payload["strategies"]` map in `routes/chart.py`.
- Append the new UI option in `templates/partials/backtest_panel.html` and extend tests in `tests/test_routes.py`, `tests/test_backtest.py`, and `tests/test_ui.py`.

</code_context>

<deferred>
## Deferred Ideas

- Multi-ticker portfolio allocation/backtesting that truly realizes `portfolio-001` across a basket belongs in a later phase; the first implementation can still make a single-ticker strategy reusable across assets.
- Large optimizer sweeps for lookback/risk parameters remain v2 scope after a first corpus-derived strategy exists.
- A richer overlay/annotation layer that visually explains which Phase 1 principle triggered a trade can be deferred if the first pass delivers a selectable strategy and tested backtest results.

</deferred>

---

*Phase: 02-implement-corpus-derived-strategy*
*Context gathered: 2026-04-04*
