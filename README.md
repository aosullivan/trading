# Trading App

Local backtesting and charting tool for stocks, crypto, and ETFs. Built with Flask, yfinance, and TradingView's Lightweight Charts.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Running

```bash
source venv/bin/activate
python app.py
```

Opens at http://localhost:5050

## Features

### Chart View (`/`)

- Interactive candlestick charts with TradingView's Lightweight Charts
- Daily, weekly, and monthly intervals
- Overlay toggles: Supertrend, Auto MA, SMA 50/100/200, 50W/100W/200W MA, EMA 9/21, MACD
- Backtest panel with full trade history, metrics, and strategy comparison
- Watchlist with live quotes, sorting, and click-to-load

## Strategies

| # | Strategy | Description |
|---|----------|-------------|
| 1 | Supertrend | ATR-based trend bands (period=10, multiplier=3) |
| 2 | EMA 9/21 Cross | Fast/slow EMA crossover |
| 3 | MACD Signal | MACD/signal line crossover (12/26/9) |
| 4 | MA Confirm (200/3) | Price above 200 SMA for 3 consecutive candles |
| 5 | Donchian (20) | 20-period high/low channel breakout |
| 6 | ADX Trend (14/25) | +DI/-DI direction when ADX > 25 |
| 7 | Bollinger Breakout | Close breaks above upper Bollinger Band (20/2) |
| 8 | Keltner Breakout | Close breaks above upper Keltner Channel (EMA 20, ATR 10, mult 1.5) |
| 9 | Parabolic SAR | Classic SAR flip (af=0.02, max=0.2) |
| 10 | CCI Trend (20/100) | CCI above +100 = long, below -100 = short |

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
