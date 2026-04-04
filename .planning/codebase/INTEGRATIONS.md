# Codebase Integrations

## External Market Data
- yfinance downloads OHLCV and ticker metadata in `lib/cache.py` and `lib/data_fetching.py`.
- FRED CSV endpoints provide Treasury yield history in `_fetch_treasury_yield_history()` in `lib/data_fetching.py`.

## Ticker Mapping
- `normalize_ticker()` in `lib/data_fetching.py` adds `^` for known index symbols and maps `SPX` to `^GSPC`.
- Treasury yield/proxy tickers are handled by `_TREASURY_YIELD_SERIES` and `_TREASURY_PRICE_PROXIES`.

## HTTP Contracts
- `routes/chart.py` serves `/api/chart`.
- `routes/financials.py` serves `/api/financials`.
- `routes/watchlist.py` serves watchlist CRUD plus quote/trend endpoints.
- `routes/pages.py` serves `/`, `/backtest`, and `/favicon.ico`.

## Browser/CDN
- Lightweight Charts is loaded from `https://unpkg.com/...` in both page templates.
- Google Fonts Inter is loaded from `fonts.googleapis.com`.
- Tooltip links in `templates/partials/signal_chips.html` point to Investopedia/TradingView/StockCharts docs.

## Local Persistence
- `routes/watchlist.py` writes `watchlist.json` under the user-data directory.
- `lib/data_fetching.py` persists CSV/meta cache files under `data_cache/`.
- `lib/cache.py` persists ticker metadata under `data_cache/ticker_info/` and redirects yfinance cache files to `data_cache/yfinance/`.
- `routes/watchlist.py` stores trend snapshots under `data_cache/watchlist_trends/`.

## Tests
- Backend tests use Flask's test client and patch yfinance calls with `unittest.mock.patch`.
- `tests/test_ui.py` drives browser behavior with Playwright against a subprocess Flask server.
