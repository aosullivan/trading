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
- Daily and weekly intervals
- Overlay toggles: Supertrend, SMA 50/100/200, 200W MA, EMA 9/21, MACD
- Backtest panel with full trade history, metrics, and strategy comparison
- Watchlist with live quotes, sorting, and click-to-load

### Backtest Report (`/report`)

- Pre-generated backtest results for all watchlist tickers
- Summary table: tickers as rows, years as columns, P&L colored green/red
- Filter by specific strategy or show best strategy per cell
- Click any cell to drill down into full metrics and trade list

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

## Generating the Report

The report page loads from a static `report_data.json` file. To regenerate it:

```bash
# Default periods: 2024, 2025, YTD current year
python generate_report.py

# Custom years
python generate_report.py --years 2023 2024 2025

# Custom date range
python generate_report.py --start 2022-01-01 --end 2023-12-31
```

This downloads data for all watchlist tickers and runs every strategy against each period. Takes ~1-2 minutes depending on watchlist size.

## Adding a New Strategy

1. Add a `compute_<name>(df, ...)` function in `app.py` that returns a direction Series (1=long, -1=short, 0=flat)
2. Add an entry to the `STRATEGIES` dict in `app.py`
3. Wire it into `/api/chart` for the live chart view (compute + backtest calls, add to strategies response dict)
4. Add a `<option>` to the strategy dropdown in `templates/index.html`
5. Re-run `python generate_report.py` to update the report

## Project Structure

```
app.py                  Flask app, all strategy logic and API routes
generate_report.py      Script to generate report_data.json
report_data.json        Pre-generated backtest results
watchlist.json          Saved watchlist tickers
templates/
  index.html            Chart + backtest UI
  report.html           Backtest report UI
requirements.txt        Python dependencies
```
