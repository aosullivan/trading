# Portfolio Campaigns

Portfolio campaigns let the app treat portfolio backtests as a planned batch of runs instead of one ad hoc request at a time.

## What A Campaign Stores

Each campaign stores:

- a name, goal, optional notes, and tags
- one or more run specs
- a lightweight schedule definition
- per-run status and the most recent summary result

Each run spec stores the exact portfolio backtest inputs required to replay the run locally:

- strategy
- allocator policy
- basket source and basket definition
- start and end dates
- heat limit
- money-management configuration
- optional research-matrix context for canonical basket and regime labels

## Run Status Model

Runs move through these states:

- `planned`
- `queued`
- `running`
- `completed`
- `failed`
- `skipped`

Campaign progress is derived from those run states so the UI can show what is complete, what is still remaining, and whether the campaign is currently active.

## Scheduling Model

Campaigns support three schedule modes:

- `manual`
- `hourly`
- `weekly`

`manual` keeps execution user-triggered only.

`hourly` reruns the full campaign on a fixed local interval.

`weekly` reruns the full campaign on selected weekdays at a chosen local hour and minute.

When a scheduled campaign becomes due, the app requeues all non-running runs, executes them sequentially, and stores the latest lightweight summary for each run.

## API Surface

- `GET /api/portfolio/campaigns`
- `POST /api/portfolio/campaigns`
- `GET /api/portfolio/research-matrix`
- `POST /api/portfolio/campaigns/research-matrix`
- `GET /api/portfolio/campaigns/completed-runs`
- `GET /api/portfolio/campaigns/compare`
- `GET /api/portfolio/campaigns/<campaign_id>`
- `POST /api/portfolio/campaigns/<campaign_id>/queue`
- `POST /api/portfolio/campaigns/<campaign_id>/rerun`
- `POST /api/portfolio/campaigns/<campaign_id>/schedule`
- `POST /api/portfolio/campaigns/run-due`

## UI Surface

The `/portfolio` page now includes a campaign dashboard that lets the user:

- save the current portfolio form as a campaign
- create the canonical `v1.18` research matrix campaign in one click
- inspect saved campaigns and their progress
- view per-run status and latest summary tags
- save a local schedule for the selected campaign
- rerun a completed campaign from the same screen

The same page also includes a completed-run comparison surface that lets the user:

- rank saved completed runs by gap versus buy-and-hold, return, return-over-drawdown, or lowest drawdown
- filter saved runs by strategy, basket source, and status without rerunning backtests
- select up to three runs and inspect them side by side using the same saved metrics
- see metric leaders quickly so winners are obvious before opening a full campaign

## Comparison Model

Run comparison stays read-only and uses saved campaign results only. The ranking surface does not fetch fresh market data or rerun portfolio backtests.

Each comparison row combines:

- campaign metadata
- saved run definition
- latest saved completed-run summary
- optional research-matrix basket and regime context

The first saved decision metrics are:

- strategy return
- buy-and-hold return
- gap versus buy-and-hold
- max drawdown
- buy-and-hold max drawdown
- drawdown gap versus buy-and-hold
- upside capture versus buy-and-hold on positive benchmark windows
- return over drawdown
- average invested capital
- average active positions
- average redeployment lag
- turnover
- max single-name weight
- traded tickers and order count for quick context

## Canonical Research Matrix

`v1.18` adds a canonical research matrix so portfolio-policy experiments stop being ad hoc. The matrix is defined by:

- strategies: `ribbon`, `corpus_trend`, `cci_hysteresis`
- allocator policies: `signal_flip_v1`, `signal_equal_weight_redeploy_v1`, `signal_top_n_strength_v1`, `core_plus_rotation_v1`
- baskets: `focus_7`, `growth_5`, `diversified_10`
- windows: `crash_recovery_2020_2021`, `drawdown_chop_2022`, `bull_recovery_2023_2025`

The matrix builder stores that context on each run so later evaluation can group results by basket and regime without reinterpreting free-form run names.

## Persistence

Campaigns are stored locally under `TRIEDINGVIEW_USER_DATA_DIR/portfolio_campaigns/`.

Each campaign is saved as one JSON document, with an `index.json` file used for the list view. This keeps the feature local-first and aligned with the repo’s existing user-data model.
