# Trend-Driven Optimizer Harness

This CLI builds a reviewable manifest of all `ribbon` strategy permutations,
then runs/resumes a SQLite-backed brute-force optimization across tickers,
intervals, and date windows.

## 1) Generate the manifest first

```bash
source venv/bin/activate
python3 scripts/optimize_trend_ribbon.py manifest --as-of 2026-04-02
```

This writes:
- `ribbon_configs.csv`: every strategy config permutation and `config_id`
- `date_windows.csv`: the 56 date windows in the optimization ladder
- `evaluation_targets.csv`: every ticker/interval/window target plus skip reasons
- `manifest_summary.json`: total counts and planned evaluation volume

Default output directory:

```text
~/Library/Application Support/TriedingView/optimizer/manifests/trend_ribbon
```

## 2) Run a small smoke test

```bash
python3 scripts/optimize_trend_ribbon.py run \
  --run-id ribbon-smoke \
  --as-of 2026-04-02 \
  --limit-targets 3 \
  --batch-size 32 \
  --progress-every 32
```

`--limit-targets` caps the number of ticker/interval/window targets, which is
useful before launching a full overnight job.

## 3) Launch the full overnight run

```bash
nohup python3 scripts/optimize_trend_ribbon.py run \
  --run-id ribbon-v1 \
  --as-of 2026-04-02 \
  --workers 1 \
  --batch-size 128 \
  --progress-every 500 \
  > /tmp/ribbon-v1.log 2>&1 &
```

The optimizer checkpoints every batch into SQLite, so if the laptop sleeps,
reboots, or you stop the process, rerun the same command with the same
`--run-id` to resume without recomputing completed rows.

Default DB path:

```text
~/Library/Application Support/TriedingView/optimizer/trend_ribbon.sqlite3
```

## 4) Export the current best configs

```bash
python3 scripts/optimize_trend_ribbon.py export \
  --run-id ribbon-v1 \
  --top-n 50
```

Default export path:

```text
~/Library/Application Support/TriedingView/optimizer/trend_ribbon_rankings.csv
```

## Defaults

- Strategy grid: 2,187 valid `ribbon` configs
- Tickers: `BTC-USD`, `ETH-USD`, `SPX`, `VGT`, `TLT`, `NVDA`, `AAPL`,
  `TSLA`, `XLE`, `MU`, `MRVL`, `AMD`, `AVGO`, `AMAT`, `LRCX`, `TSM`,
  `ASML`, `QCOM`, `SMH`
- Intervals: `1d`, `1wk`, `1mo`
- Trade cap: configs averaging more than 6 round-trip trades/year are excluded
  from the rankings
- Score: `net_profit_pct - 0.45 * max_drawdown_pct`

## Useful overrides

```bash
python3 scripts/optimize_trend_ribbon.py run \
  --run-id ribbon-custom \
  --as-of 2026-04-02 \
  --tickers AAPL,NVDA,MU,MRVL,SMH \
  --intervals 1d,1wk \
  --max-round-trips-per-year 5 \
  --drawdown-weight 0.6 \
  --workers 1 \
  --batch-size 64
```

## Macro Regime Research

Use the macro CLI to test whether falling short-end yields and election-cycle phases
actually line up with better forward portfolio conditions on the retained research baskets.

```bash
source venv/bin/activate
TRIEDINGVIEW_USER_DATA_DIR=/tmp/tv_user_macro python3 scripts/analyze_macro_regime_hypotheses.py \
  --start 2012-01-01 \
  --forward-days 126
```

Default local outputs:

```text
.planning/phases/62-build-empirical-macro-regime-research-harness/macro-regime-hypotheses.json
.planning/phases/62-build-empirical-macro-regime-research-harness/macro-regime-hypotheses.md
```

Run the canonical macro-overlay parameter sweep after the feature layer is in place:

```bash
source venv/bin/activate
TRIEDINGVIEW_USER_DATA_DIR=/tmp/tv_user_macro_overlay python3 scripts/run_macro_overlay_matrix.py
```

Default local outputs:

```text
.planning/phases/64-run-macro-aware-overlay-matrix/macro-overlay-matrix-results.json
.planning/phases/64-run-macro-aware-overlay-matrix/macro-overlay-matrix-results.md
```
