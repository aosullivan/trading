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
- basket source and basket definition
- start and end dates
- heat limit
- money-management configuration

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
- `GET /api/portfolio/campaigns/<campaign_id>`
- `POST /api/portfolio/campaigns/<campaign_id>/queue`
- `POST /api/portfolio/campaigns/<campaign_id>/rerun`
- `POST /api/portfolio/campaigns/<campaign_id>/schedule`
- `POST /api/portfolio/campaigns/run-due`

## UI Surface

The `/portfolio` page now includes a campaign dashboard that lets the user:

- save the current portfolio form as a campaign
- inspect saved campaigns and their progress
- view per-run status and latest summary tags
- save a local schedule for the selected campaign
- rerun a completed campaign from the same screen

## Persistence

Campaigns are stored locally under `TRIEDINGVIEW_USER_DATA_DIR/portfolio_campaigns/`.

Each campaign is saved as one JSON document, with an `index.json` file used for the list view. This keeps the feature local-first and aligned with the repo’s existing user-data model.
