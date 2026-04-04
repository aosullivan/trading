# Codebase Conventions

## Python
- 4-space indentation, snake_case names, and UPPER_SNAKE_CASE constants.
- Route modules expose `bp = Blueprint(...)` and delegate most domain logic into `lib/`.
- Broad `except Exception` is common around network/cache/file-write paths to keep the app responsive.
- Pandas Series/DataFrames are the standard indicator/backtest data shape with `Open`, `High`, `Low`, `Close`, `Volume` columns.
- Strategy direction values generally use `1` for bullish/long, `-1` for bearish/flat, and sometimes `0` for neutral bridge bars.

## Flask/API
- Missing ticker inputs return `jsonify({"error": ...}), 400`.
- `app.py` registers blueprints from `routes.ALL_BLUEPRINTS`.
- Route helper functions in `routes/chart.py` handle interval resampling, visible-window slicing, prior-direction lookup, and indicator cache keys.

## Frontend
- No JS modules or bundler; scripts rely on global variables/functions and template load order.
- Templates include partials and often bind inline DOM events to globals.
- CSS is centralized in `static/styles.css` with compact class prefixes like `.wl-*`, `.bt-*`, `.tf-*`, `.fin-*`.
- UI state is toggled with classes like `active`, `open`, and `collapsed`.

## Persistence
- Read-only resource paths go through `get_resource_path(...)`.
- Writable files and caches go through `get_user_data_path(...)`.
- Cache dictionaries and refresh-state sets are module globals.

## Testing
- Pytest classes group tests by domain/behavior.
- Fixtures in `tests/conftest.py` patch module globals for isolated temp paths and clear cache dicts/sets.
- Browser tests use Playwright against a live Flask subprocess.
