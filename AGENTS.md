# AGENTS.md

## Cursor Cloud specific instructions

### Product overview

TriedingView is a local-first backtesting and charting app (Flask + yfinance + TradingView Lightweight Charts). Single service: a Flask dev server on port 5050.

### Running the app

```bash
source venv/bin/activate
TRIEDINGVIEW_USER_DATA_DIR=/tmp/tv_user python3 app.py
```

The `TRIEDINGVIEW_USER_DATA_DIR` env var isolates user data (watchlist, cache) from the repo working tree. The app opens at http://localhost:5050.

### Running tests

```bash
source venv/bin/activate
TRIEDINGVIEW_USER_DATA_DIR=/tmp/tv_user pytest -q
```

UI tests (`tests/test_ui.py`) are excluded by default via `pytest.ini` (`--ignore=tests/test_ui.py`). They require Playwright + Chromium (`pip install playwright && playwright install`).

### Linting

No linter is configured in this project. A compile-all check (`python3 -m compileall .`) can be used as a basic syntax check.

### Caveats

- The `venv/` directory is in `.gitignore`; never commit it.
- Internet access is required for chart data (yfinance calls Yahoo Finance). Tests mock yfinance, so they work offline.
- There is no database to start; SQLite is only used by the optimizer CLI scripts and is built into Python.
- `python3.12-venv` system package must be installed before creating the virtualenv (not available by default on Ubuntu 24.04 minimal).
