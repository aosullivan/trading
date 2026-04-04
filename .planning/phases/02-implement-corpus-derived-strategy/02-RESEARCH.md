# Phase 2 Research: Implement Corpus-Derived Strategy

## Planning Goal
Turn the Phase 1 KB into one concrete, source-linked strategy implementation that fits the current Flask/backtest/UI stack, keeps existing strategy behavior intact, and has a clear automated validation path.

Core source context: `.planning/phases/02-implement-corpus-derived-strategy/02-CONTEXT.md`, `.planning/phases/01-build-trend-following-knowledge-base/trend-following-knowledge-base.md`, `.planning/phases/01-build-trend-following-knowledge-base/trend-following-knowledge-base.json`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/codebase/*.md`.

## Observed Implementation Surface
- `routes/chart.py` already computes all indicator series and backtests in one request path, then returns a top-level `strategies` map keyed by strategy ID. Adding a non-default `corpus_trend` entry here is the least disruptive backend integration path.
- `templates/partials/backtest_panel.html` hardcodes all strategy `<option>` values and labels, while `static/js/backtest_panel.js` already reads the selected `<option value>` and keeps `BT_DEFAULT_STRATEGY='ribbon'`. So a new option can be appended without introducing new frontend state machinery.
- `tests/test_routes.py::TestChartAPI.test_chart_strategies_present` asserts the current strategy keys list and each strategy's `trades`/`summary` contract. `tests/test_ui.py::TestBacktestPanel.test_strategy_select_options` asserts the option count is 12 and the first option remains `ribbon` / `Trend-Driven`.
- `lib/technical_indicators.py` already exposes `compute_donchian_breakout`, `compute_ma_confirmation`, `compute_keltner_breakout`, and ATR-style calculations inside several indicators. Direction series conventions are consistent: `1` means long, `-1` means bearish/flat, and `0` is sometimes a neutral bridge.
- `lib/backtesting.py::backtest_direction` is all-in/all-out, but `backtest_ribbon_accumulation` shows the codebase already accepts variable quantity lots, per-lot sleeves, contributions, and summaries derived from custom equity curves. A dedicated `backtest_corpus_trend(...)` can reuse trade dict conventions while implementing ATR/risk-based sizing.

## Recommended Strategy Contract
Recommendation, grounded in `02-CONTEXT.md` and the KB handoff:
- Strategy ID: `corpus_trend`
- UI label: `Corpus Trend (Donchian/ATR)` or similar wording that signals the corpus-derived rule family without replacing the existing `Trend-Driven` default
- Spec artifact: `.planning/phases/02-implement-corpus-derived-strategy/corpus-trend-strategy-spec.md`
- Backend signal helper: likely `compute_corpus_trend_signal(...)` in `lib/technical_indicators.py` returning breakout/exit bands plus a direction series
- Backend backtest helper: likely `backtest_corpus_trend(...)` in `lib/backtesting.py` returning `(trades, summary, equity_curve)` with ATR-sized entries and deterministic channel exits
- Route payload: add `payload["strategies"]["corpus_trend"] = {"trades": ..., "summary": ..., "equity_curve": ..., "buy_hold_equity_curve": buy_hold_equity_curve}` while preserving every existing strategy key and response field

## Entry/Exit Family Recommendation
Recommended first implementation: **Donchian breakout entry + trailing Donchian/channel exit + ATR-based position sizing**.

Why this is the best first cut:
- It directly matches Phase 1 principle IDs and strategy handoff:
  - `entry-001`, `trend-001`, `regime-001` -> price-only breakout/trend confirmation
  - `exit-001`, `whipsaw-001`, `drawdown-001` -> systematic trailing/channel exits and no drawdown-triggered parameter changes
  - `sizing-001`, `risk-001`, `portfolio-001` -> volatility/risk-aware sizing and reusable cross-market rules
- It fits current code with minimal architectural disruption:
  - Donchian channels already exist in `compute_donchian_breakout(...)`
  - ATR calculations already exist in Supertrend, Keltner, ADX, and Trend Ribbon implementations
  - Existing route/UI contracts can carry a new strategy key without schema redesign
- It is easier to explain and test than a hybrid route-dependent regime model, and it avoids overfitting to the Phase 1 extractor's sparse term matches.

Implementation caution:
- Current `compute_donchian_breakout(df, period=10)` uses a single period for both entry and exit and a relatively fast 10-bar horizon. The KB/context prefer slower medium/long-horizon behavior and separate trailing-exit logic. A new corpus-trend helper should probably use asymmetric windows, e.g. longer entry lookback than exit lookback, instead of reusing `DONCHIAN_PERIOD=10` verbatim.
- Existing `backtest_direction(...)` invests all available cash on each entry. To satisfy `D-05`, a new backtest helper should size shares from ATR stop distance and a fixed account risk fraction, and leave unused cash idle instead of forcing all-in exposure.

## Route/UI Contract Changes
Observed safe integration path:
- Extend `_get_indicator_bundle(...)` in `routes/chart.py` with corpus-trend signal outputs and add `corpus_trend` to its internal `direction_map` only if that direction is meant to appear in `trend_flips`.
- Compute `corpus_trend_trades`, `corpus_trend_summary`, and `corpus_trend_equity_curve` in `chart_data()` and append a `corpus_trend` object to `payload["strategies"]`.
- Add one `<option value="corpus_trend">...</option>` to `templates/partials/backtest_panel.html`, but do not move or rename the first `ribbon` option because `tests/test_ui.py` currently asserts that exact first option.
- No change is needed to `static/js/backtest_panel.js` for key routing unless the selected option requires custom display text; the script already uses the selected strategy key and renders the standard trade/summary payload.

## Regression Risks To Plan Around
- **Contract drift:** updating tests for strategy count/options can accidentally hide a breaking change to default `ribbon` ordering. Keep assertions that `ribbon` remains first/default and add explicit assertions for the new `corpus_trend` option/key.
- **Chart-route performance:** `/api/chart` already computes many strategies per request. Adding another strategy and a new ATR/channel helper increases request cost. The first implementation should avoid expensive parameter sweeps or per-request file reads of the KB artifact.
- **Hidden chart/watchlist coupling:** `routes/watchlist.py` uses `compute_all_trend_flips(...)` for summary rows, but Phase 2 scope only requires `/api/chart` and backtest UI integration. Unless there is a deliberate UI need, adding `corpus_trend` to watchlist trend tabs should be deferred to avoid widening regression scope.
- **Long-only engine mismatch:** current backtests are long/cash, not long/short. If the spec says "long/short" from `entry-001`, implementation should either explicitly choose long/cash for v1 compatibility or introduce short support with dedicated tests. The safer Phase 2 default is long/cash and document that choice in the spec artifact.
- **Extractor caveat:** Phase 1's KB is based on `PRINCIPLE_BLUEPRINTS` plus deterministic substring matching in `scripts/build_trend_following_kb.py`, not deep semantic parsing of every sentence. Phase 2 should preserve principle IDs/citations in the spec, but avoid overstating this artifact as exhaustive model discovery.

## Suggested Strategy Spec Contents
The `02-01` plan should produce a markdown spec with at least:
- strategy name + stable key (`corpus_trend`)
- entry rule formula, exit rule formula, and neutral/initial-state behavior
- ATR/risk sizing formula and constants with rationale
- whether v1 is long/cash or long/short, and why
- how drawdown discipline is encoded or reported
- explicit traceability table mapping implementation decisions to `entry-001`, `exit-001`, `sizing-001`, `risk-001`, `drawdown-001`, `trend-001`, `whipsaw-001`, `portfolio-001`, and `regime-001`
- implementation file map for `02-02`

## Validation Architecture
Concrete checks a planner can wire into `02-01` and `02-02`:
- **Spec traceability checks**
  - `rg -n "entry-001|exit-001|sizing-001|risk-001|drawdown-001|trend-001|whipsaw-001|portfolio-001|regime-001" .planning/phases/02-implement-corpus-derived-strategy/corpus-trend-strategy-spec.md`
  - `rg -n "corpus_trend|Donchian|ATR|long/cash" .planning/phases/02-implement-corpus-derived-strategy/corpus-trend-strategy-spec.md`
- **Indicator/backtest unit tests**
  - Add tests in `tests/test_indicators.py` for the new signal helper's entry/exit transitions and warmup behavior
  - Add tests in `tests/test_backtest.py` for ATR-sized quantities, stop/channel exits, open-trade marking, and empty-frame behavior
  - Run `pytest tests/test_indicators.py tests/test_backtest.py`
- **Route/UI contract tests**
  - Extend `tests/test_routes.py::TestChartAPI.test_chart_strategies_present` to include `corpus_trend` and verify `trades`, `summary`, and `equity_curve`
  - Extend `tests/test_ui.py::TestBacktestPanel.test_strategy_select_options` to assert the new option exists while `ribbon` remains first
  - Run `pytest tests/test_routes.py` and, when the browser is available, `pytest -m ui tests/test_ui.py -k strategy_select_options`
- **Compatibility checks**
  - `rg -n "BT_DEFAULT_STRATEGY='ribbon'" static/js/backtest_panel.js` to confirm default strategy remains unchanged
  - `rg -n '"ribbon"' routes/chart.py templates/partials/backtest_panel.html tests/test_ui.py` to ensure the existing strategy key/label is preserved

## Planning Recommendation
- `02-01` should create the markdown strategy spec first, choose exact default lookbacks/risk constants, and define function names/contracts before code changes.
- `02-02` should implement `corpus_trend` in `lib/` and `routes/chart.py`, append the UI option, and extend route/backtest/UI tests in one vertically integrated pass.
- If implementation introduces short selling or a multi-asset allocator, that is scope creep relative to `02-CONTEXT.md` and should be deferred unless the user explicitly reopens the phase context.
