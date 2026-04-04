# Codebase Concerns

## Dependency Drift
- `scipy` is imported in `lib/support_resistance.py` but missing from `requirements.txt`.
- `playwright` is imported in `tests/test_ui.py` but missing from `requirements.txt`.
- README references `./scripts/build_macos_app.sh`, but that script is absent from `scripts/`.

## Contract Drift
- `tests/test_ui.py` expects page title `"Trading App"` while `templates/index.html` uses `"TriedingView"`.
- Adding a new strategy requires coordinated edits across `lib/technical_indicators.py`, `routes/chart.py`, `templates/partials/backtest_panel.html`, `templates/partials/signal_chips.html`, and several `static/js/` files.

## Maintainability
- Frontend code is tightly coupled through globals and script order.
- Inline `onclick`/`onchange` handlers bind templates directly to global function names.
- Broad `except Exception` blocks can hide logic bugs or cache corruption.

## Concurrency/Data Risks
- `_cache` in `lib/cache.py` is a shared dict without a dedicated lock.
- Background daemon refresh threads in `routes/watchlist.py` and `lib/cache.py` have limited lifecycle/error reporting.
- Interval resampling and prior-direction logic are duplicated in `routes/chart.py` and `lib/trend_optimizer.py`, which can cause chart-vs-optimizer drift.

## Performance
- `/api/chart` computes many indicators/backtests and support/resistance levels per request; long histories can be expensive.
- Watchlist trend refresh computes indicator summaries per ticker and can become heavy for large watchlists.
- Optimizer scripts in `lib/trend_optimizer.py` intentionally run large parameter sweeps and should stay off the request path.

## Repo Hygiene
- `.codex/` is a generated local GSD install and should be committed only if that is intentional for this repo.
- `scripts/transcribe_audiobook.py` appears unrelated to the trading app domain.
- The worktree currently has unrelated modified app/test files; avoid mixing GSD setup commits with feature commits.
