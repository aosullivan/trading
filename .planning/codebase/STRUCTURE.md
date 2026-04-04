# Codebase Structure

## Top Level
- `app.py` — Flask app factory and dev-server entrypoint.
- `desktop_app.py` — desktop-window wrapper.
- `lib/` — indicators, data fetching, caching, backtesting, optimizer, serialization, financial formatting, path utilities.
- `routes/` — Flask blueprints.
- `templates/` — page shells and partials.
- `static/` — JS/CSS/assets.
- `scripts/` — optimizer/cache helper scripts and other utilities.
- `tests/` — pytest and Playwright tests.

## `lib/`
- `lib/cache.py`
- `lib/data_fetching.py`
- `lib/technical_indicators.py`
- `lib/backtesting.py`
- `lib/chart_serialization.py`
- `lib/support_resistance.py`
- `lib/financials.py`
- `lib/trend_ribbon_profile.py`
- `lib/trend_optimizer.py`
- `lib/settings.py`
- `lib/paths.py`

## `routes/`
- `routes/__init__.py`
- `routes/pages.py`
- `routes/chart.py`
- `routes/financials.py`
- `routes/watchlist.py`

## `templates/`
- `templates/index.html`
- `templates/backtest.html`
- `templates/partials/toolbar.html`
- `templates/partials/signal_chips.html`
- `templates/partials/backtest_panel.html`
- `templates/partials/watchlist.html`
- `templates/partials/financials_modal.html`

## `static/`
- `static/styles.css`
- `static/favicon.svg`
- `static/chart_support_resistance.js`
- `static/js/chart_core.js`
- `static/js/chart_load.js`
- `static/js/chart_overlays.js`
- `static/js/chart_legend.js`
- `static/js/chart_sr.js`
- `static/js/chart_signals.js`
- `static/js/backtest_panel.js`
- `static/js/backtest_report.js`
- `static/js/financials_modal.js`
- `static/js/url_state.js`
- `static/js/watchlist.js`
- `static/js/app_init.js`

## `tests/`
- `tests/conftest.py` sets temp cache/watchlist fixtures and synthetic OHLCV data.
- `tests/test_routes.py`, `tests/test_backtest.py`, `tests/test_data_fetching.py`, `tests/test_indicators.py`, `tests/test_support_resistance.py`, `tests/test_sr_regression.py`, `tests/test_trend_optimizer.py`, `tests/test_chart_sr_js.py`, `tests/test_chart_template_contract.py`, `tests/test_ui.py`.
- `tests/fixtures/*.json` contains support/resistance regression fixtures.

## Naming/Organization
- Flask blueprints are grouped by route domain.
- Backend helper functions often use leading underscores even across module imports.
- Frontend feature code uses prefixes such as `wl*`, `bt*`, `chart*`, and `render*`.
