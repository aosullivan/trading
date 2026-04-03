# TriedingView

Local backtesting and charting tool for stocks, crypto, and ETFs. Built with Flask, yfinance, and TradingView's Lightweight Charts.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Running

```bash
source venv/bin/activate
python3 app.py
```

Opens at http://localhost:5050

## macOS App

Build a local `.app` bundle:

```bash
./scripts/build_macos_app.sh
```

Then open `dist/TriedingView.app` from Finder.

The desktop build stores watchlist and cache files in
`~/Library/Application Support/TriedingView`.

## Features

### Chart View (`/`)

- Interactive candlestick charts with TradingView's Lightweight Charts
- Daily, weekly, and monthly intervals
- Overlay toggles: Supertrend, Auto MA, SMA 50/100/200, 50W/100W/200W MA, EMA 5/20, MACD
- Backtest panel with full trade history, metrics, and strategy comparison
- Watchlist with live quotes, sorting, and click-to-load

## Strategies

| # | Strategy | Description |
|---|----------|-------------|
| 1 | MA Confirm (180/1 up/5 down) | 1 close above 180 SMA to enter; 5 consecutive closes below 180 SMA to exit |
| 2 | Supertrend (10/2.5) | ATR-based trend bands (period=10, multiplier=2.5) |
| 3 | EMA 5/20 Cross | Fast/slow EMA crossover |
| 4 | MACD Signal (16/32/9) | MACD/signal line crossover |
| 5 | Donchian (10) | 10-period high/low channel breakout |
| 6 | ADX Trend (14/25) | +DI/-DI direction when ADX > 25 |
| 7 | Bollinger Breakout (30/1.5) | Close breaks above upper Bollinger Band |
| 8 | Keltner Breakout (30/10/1.5) | Close breaks above upper Keltner Channel |
| 9 | Parabolic SAR (0.01/0.01/0.1) | SAR flip with smoother AF settings |
| 10 | CCI Trend (30/80) | CCI above +80 = long, below -80 = short |

All strategies output a direction signal (1=long, -1=short/flat) and use the same `backtest_direction()` engine.

## Adding a New Strategy

1. Add a `compute_<name>(df, ...)` function in `lib/technical_indicators.py` that returns a direction Series (1=long, -1=short, 0=flat)
2. Wire it into `/api/chart` in `routes/chart.py` (compute + backtest calls, add to the `strategies` payload)
3. Add overlay/legend handling in `static/js/chart_overlays.js` and `static/js/chart_legend.js` if the strategy has chart visuals
4. Add a `<option>` to the strategy dropdown in `templates/partials/backtest_panel.html`

## Project Structure

```
app.py                  Flask app bootstrap + blueprint registration
lib/                    Data fetching, caching, indicators, backtesting, serialization
routes/                 Flask blueprints for pages and API endpoints
static/js/              Frontend chart, overlays, backtest, watchlist, and modal scripts
static/styles.css       Extracted app styles
templates/
  index.html            Thin page shell that includes partials and scripts
  partials/             Toolbar, signal chips, backtest panel, watchlist, financials modal
watchlist.json          Saved watchlist tickers
requirements.txt        Python dependencies
```
