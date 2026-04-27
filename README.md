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
TRIEDINGVIEW_USER_DATA_DIR=/tmp/tv_user python3 app.py
```

The `TRIEDINGVIEW_USER_DATA_DIR` env var keeps watchlist and cache data out of the repo working tree.

Opens at http://localhost:5050

## Testing

```bash
source venv/bin/activate
TRIEDINGVIEW_USER_DATA_DIR=/tmp/tv_user pytest -q
```

UI tests in `tests/test_ui.py` are excluded by default and require Playwright plus Chromium:

```bash
pip install playwright
playwright install
```

## Syntax Check

No linter is configured in this project. For a basic syntax pass, run:

```bash
python3 -m compileall .
```

## Project Workflow (GSD)

This repo uses **GSD (Get Shit Done)** for milestone, phase, and planning workflow.

Important: in this project, GSD is used primarily through **Codex / Claude slash commands**, not as a normal standalone shell CLI.
The planning surface in `.planning/` is intentionally **local-only** in this repo and is gitignored, so GSD artifacts are meant for live workflow/state management rather than committed project history.

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

Because `.planning/` is gitignored here:

- use GSD to drive the workflow and inspect local planning state
- do not expect GSD planning artifacts to be committed or pushed
- treat code/tests/docs in the tracked repo as the durable shared history

The repo also vendors GSD internals in [`.codex/get-shit-done/`](.codex/get-shit-done/).
That bundle includes workflows, templates, and the low-level helper `node .codex/get-shit-done/bin/gsd-tools.cjs`.

`gsd-tools.cjs` is **internal plumbing**, not the primary day-to-day interface. Use the `/gsd-*` commands above for normal project workflow, and use the CLI helper mainly for local validation/status checks.

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

The maintained strategy contract is now guarded by the promoted focus-basket
baseline in [docs/focus-basket-ratchet-benchmark.md](docs/focus-basket-ratchet-benchmark.md)
plus the dedicated Polymarket benchmark in
[`tests/test_polymarket_benchmark_backtests.py`](tests/test_polymarket_benchmark_backtests.py).


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
| 1 | Trend-Driven | Trend ribbon regime with weekly confirmation and cooldown logic |
| 2 | Corpus Trend (Donchian/ATR) | Corpus stop-line trend following with optional confirmation layering |
| 3 | Corpus Trend Layered | Comparison-only layered corpus exposure profile |
| 4 | CCI Hysteresis (30/150/-40) | Final promoted baseline from the bounded search program |
| 5 | Polymarket Skew | Prediction-market probability skew routed through the backtest engine |

The maintained product surface is intentionally narrow now: `ribbon`,
`corpus_trend`, `corpus_trend_layered`, `cci_hysteresis`, and `polymarket`.
The backtest selector also exposes a small experimental shelf for previously
promising strategies: `trend_sr_macro_v1`, `weekly_core_overlay_v1`,
`supertrend_i`, `bb_breakout`, `ema_crossover`, and `cci_trend`.

For the retained daily trend strategies, the backtest panel still supports staged confirmation modes:
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
