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

## Project Workflow (GSD)

This repo uses **GSD (Get Shit Done)** for milestone, phase, and planning workflow.

Important: in this project, GSD is used primarily through **Codex / Claude slash commands**, not as a normal standalone shell CLI.

The main workflow is:

```text
/gsd-progress -> /gsd-plan-phase <n> -> /gsd-execute-phase <n>
```

Useful commands:

- `/gsd-progress` — inspect the current milestone, phase, and recommended next action
- `/gsd-resume-work` — restore context from the last session
- `/gsd-plan-phase <n>` — create the next detailed phase plan
- `/gsd-execute-phase <n>` — execute a planned phase
- `/gsd-new-milestone "<name>"` — start the next milestone when the current one is complete
- `/gsd-complete-milestone <version>` — archive a finished milestone

Planning artifacts live in [`/.planning`](.planning):

- `.planning/PROJECT.md` — project intent and current milestone posture
- `.planning/ROADMAP.md` — active milestone roadmap
- `.planning/STATE.md` — current position and resume point
- `.planning/phases/` — per-phase plans, summaries, and context
- `.planning/milestones/` — archived milestone requirements and roadmaps

The repo also vendors GSD internals in [`.codex/get-shit-done/`](.codex/get-shit-done/).
That bundle includes workflows, templates, and the low-level helper `node .codex/get-shit-done/bin/gsd-tools.cjs`.

`gsd-tools.cjs` is **internal plumbing**, not the primary day-to-day interface. Use the `/gsd-*` commands above for normal project workflow.

## macOS App

Build a local `.app` bundle:

```bash
./scripts/build_macos_app.sh
```

Then open `dist/TriedingView.app` from Finder.

The desktop build stores watchlist and cache files in
`~/Library/Application Support/TriedingView`.

## Trend-Driven Optimizer

See [scripts/README.md](scripts/README.md) for the manifest, overnight run,
resume, and export workflow for `scripts/optimize_trend_ribbon.py`.

## Benchmark backtests (CI)

Pinned BTC-USD history and PnL floors guard selected strategies against regressions
versus buy-and-hold. How to run tests, regenerate the fixture CSV, and update
floors: [docs/benchmark-backtests.md](docs/benchmark-backtests.md).


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

For daily strategies, the backtest panel also supports staged confirmation modes:
- `Daily 30 / Weekly 70`
- `Daily 50 / Weekly 50`

These enter with starter capital on the daily signal, then add the remaining sleeve once the weekly trend confirms. Exits unwind in reverse.

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
