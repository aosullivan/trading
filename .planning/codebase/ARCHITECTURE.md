# Codebase Architecture

## High-Level Shape
- Flask serves Jinja templates and JSON APIs; browser-side global JS renders charts, watchlists, overlays, and backtest panels.
- Most domain logic lives in `lib/`; route modules in `routes/` parse HTTP requests and assemble responses.
- `desktop_app.py` wraps the same Flask app for a local desktop shell.

## Main Request Flow
- `templates/index.html` loads JS globals from `static/js/*.js` in script order.
- `static/js/chart_load.js` calls `/api/chart`.
- `routes/chart.py` normalizes ticker/interval params, downloads data, computes indicators/backtests/support-resistance, and returns one payload.
- Frontend modules update chart overlays, legend, signal markers, backtest panel, and financial/watchlist UI.

## Core Libraries
- `lib/technical_indicators.py` computes all strategy signals.
- `lib/backtesting.py` simulates trades, equity curves, summary stats, and ribbon regime variants.
- `lib/chart_serialization.py` converts pandas series and trend flips into chart JSON.
- `lib/support_resistance.py` detects support/resistance zones.
- `lib/cache.py` and `lib/data_fetching.py` handle market-data caching and rate limiting.
- `lib/trend_ribbon_profile.py` centralizes current ribbon parameter profiles.
- `lib/trend_optimizer.py` runs offline parameter sweeps with SQLite persistence.

## Frontend Architecture
- JS files share global state such as `chart`, `lastData`, `chartStart`, `chartEnd`, and watchlist globals from `static/js/chart_core.js`.
- Templates wire events inline (`onclick`, `onchange`, `onkeydown`) to global JS functions.
- `static/styles.css` is the single app stylesheet and uses state classes like `open`, `active`, `collapsed`, `up`, and `dn`.

## Caching/State
- Module-level TTL dicts provide in-memory cache in `lib/cache.py` and `routes/watchlist.py`.
- Disk caches and watchlist files live under paths from `lib/paths.py`.
- Watchlist refresh uses daemon background threads and lock-guarded in-flight sets.
