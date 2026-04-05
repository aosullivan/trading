# Benchmark backtests (CI)

This repo pins a **historical BTC-USD** window and asserts that selected strategies **beat buy-and-hold** and stay **at or above recorded net PnL %** on that window. If a code change weakens performance, **`pytest` fails** and the GitHub Actions **CI** job fails (when branch protection requires it).

## What is being tested

- **Endpoint behavior:** Tests call **`GET /api/chart`** with fixed query parameters (same engine as the chart and standalone backtest report).
- **Strategies under guard:** `ribbon` (weekly-confirmed regime when daily data allows), `cb50`, `ema_trend`, `parabolic_sar`.
- **Assertions for each strategy:**
  1. **`net_profit_pct` > HODL** — HODL is derived from `buy_hold_equity_curve` in the same JSON response (first visible bar open, full capital, mark-to-market on close), consistent with the UI comparison.
  2. **`net_profit_pct` ≥ floor** — Floors are stored in JSON so small intentional improvements do not require a file edit; regressions fail immediately.

## Files

| File | Role |
|------|------|
| `tests/fixtures/btc_usd_1d_benchmark.csv` | Frozen daily OHLCV (Yahoo `BTC-USD`). CI does **not** download live data. |
| `tests/fixtures/btc_benchmark_backtests.json` | Chart query params, expected HODL % (sanity check), per-strategy `min_net_profit_pct`, original backtest URLs in `source_url`. |
| `tests/test_btc_benchmark_backtests.py` | Mocks `routes.chart.cached_download` from the CSV, hits `/api/chart`, runs assertions. |
| `scripts/regen_btc_benchmark_fixture.py` | Regenerates the CSV from Yahoo using the same warmup rule as `/api/chart`. |

## URL parameters vs `/api/chart`

The standalone backtest page may include `domain_start` / `domain_end` for loading a wider range into the **range slider**. **Report statistics** use the **`start` and `end`** query parameters passed to **`/api/chart`**. The benchmark test uses those same `start` / `end` values from `btc_benchmark_backtests.json` → `chart_request`.

Warmup for indicator history matches **`routes/chart.py`**: download starts at **`chart_request.start` minus `DAILY_WARMUP_DAYS`** (see `lib/settings.py`).

## Regenerating the CSV

From the repository root (venv activated, network available):

```bash
python scripts/regen_btc_benchmark_fixture.py
```

Defaults read `tests/fixtures/btc_benchmark_backtests.json` and overwrite `tests/fixtures/btc_usd_1d_benchmark.csv`.

Optional paths:

```bash
python scripts/regen_btc_benchmark_fixture.py --spec path/to/spec.json -o path/to/output.csv
```

## After regenerating the CSV

Yahoo’s history and splits can shift; **PnL numbers will change**. Update **`tests/fixtures/btc_benchmark_backtests.json`**:

1. Run `pytest tests/test_btc_benchmark_backtests.py` — failures print actual vs expected.
2. Set **`expected_hodl_net_profit_pct`** to the new HODL net % (two decimals is enough; the test allows a tiny tolerance).
3. Set each strategy’s **`min_net_profit_pct`** to the new **actual** values (or slightly lower if you want minor float noise only).

Commit **both** the CSV and the JSON in the same change so CI stays green and the pin is explainable in one commit.

## Running tests locally

```bash
pytest tests/test_btc_benchmark_backtests.py
```

Full suite (default `pytest.ini` skips Playwright UI tests unless you run `tests/test_ui.py` explicitly):

```bash
pytest
```

## Related: synthetic regression tests

`tests/test_strategy_regression.py` and `tests/fixtures/strategy_regression_thresholds.json` guard **deterministic** ribbon behavior on **`sample_df`** from `conftest.py` (no market file). That complements but does not replace the BTC benchmark tests.

## CI

`.github/workflows/ci.yml` runs `pytest` on pushes and pull requests to `main`. The benchmark test uses only the committed CSV, so it is suitable for GitHub-hosted runners without API keys.
