# Codebase Stack

## Runtime And Language
- Python backend with Flask app entrypoint in `app.py`.
- Desktop wrapper in `desktop_app.py` uses `pywebview` and Werkzeug.
- Frontend is plain HTML/CSS/JavaScript from `templates/` and `static/`.

## Dependencies
- `requirements.txt` lists `flask`, `pyinstaller`, `pywebview`, `yfinance`, `pandas`, `numpy`.
- `lib/support_resistance.py` imports SciPy APIs, so `scipy` is a runtime dependency not currently listed in `requirements.txt`.
- `tests/test_ui.py` imports Playwright, so `playwright` is a test dependency outside `requirements.txt`.

## Frontend Libraries
- `templates/index.html` and `templates/backtest.html` load TradingView Lightweight Charts from unpkg.
- Both templates load Google Fonts Inter from `fonts.googleapis.com`.
- `static/chart_support_resistance.js` uses a UMD wrapper so browser code and Node tests can both consume it.

## Data/Storage
- yfinance and FRED power market data fetches in `lib/cache.py` and `lib/data_fetching.py`.
- Writable files and caches resolve through `lib/paths.py` into per-user app-data directories.
- Trend optimizer results use SQLite through `lib/trend_optimizer.py`.

## Config
- Numeric defaults live in `lib/settings.py` and `lib/technical_indicators.py`.
- `TRIEDINGVIEW_USER_DATA_DIR` overrides writable data dir for local/test runs.
- `pytest.ini` configures pytest discovery and a `ui` marker.
