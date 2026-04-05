# AGENTS.md

## Cursor Cloud specific instructions

### Overview

TriedingView is a single-service Flask (Python) application for stock/crypto/ETF backtesting and charting. It runs on port 5050 with no external databases or services required. Market data is fetched live from Yahoo Finance via `yfinance`.

### Running the app

```bash
source venv/bin/activate
python3 app.py          # serves at http://localhost:5050
```

### Testing

- **Unit/integration tests** (no running server needed): `pytest --ignore=tests/test_ui.py`
- **UI tests** (require a running Flask server + Playwright browsers): `pytest -m ui`
- All tests use mocked/isolated data in `conftest.py`; no internet needed for unit tests.

### Linting

No linter config file exists in the repo. Use `ruff check .` for quick linting. There are pre-existing lint warnings in the codebase.

### Gotchas

- `requirements.txt` is missing `scipy` and `playwright` — these are needed at runtime and for UI tests respectively. The update script installs them alongside the listed requirements.
- The app caches market data in a `data_cache/` directory (file-system-based). Delete it to force fresh data fetches.
- `watchlist.json` at the repo root stores the user's watchlist; tests use an isolated temp copy.
