# TriedingView

Local backtesting and charting tool for stocks, crypto, and ETFs. Computes signals from OHLCV data, runs historical simulations of trading strategies, and renders them on TradingView Lightweight Charts.

## Language

### Strategies and signals

**Strategy**:
A registered direction-emitter — given price data, produces a series of long/short/flat decisions. Each Strategy declares its paired Backtest Engine. Lives under `lib/strategies/` and is reachable through the Strategy Registry.
_Avoid_: model, system, algo, signal generator.

**StrategyDef**:
The registry record for a Strategy — its key, label, compute function, paired Backtest Engine, default Params, and confirmation-mode opt-in.

**StrategyResult**:
The uniform return shape of every Strategy's compute: `(direction, overlays, metadata)`. `direction` is a `pd.Series` of {-1, 0, 1}, `overlays` is JSON-renderable strategy-specific chart data, `metadata` is internal.

**Strategy Registry**:
The single source of truth that maps a strategy key to its `StrategyDef`. Located at `lib/strategies/__init__.py`. Adding a Strategy means adding one file + one registry entry.

**Direction**:
A `pd.Series` aligned to the price index with values in {-1, 0, 1} (short/flat/long). The fundamental output of compute.
_Avoid_: signal (overloaded with "the latest direction value"), position (means open allocation in money management).

**Indicator**:
Pure math over price data — produces lines/columns (ATR, SMA, supertrend bands, MACD histogram, etc.). Lives in `lib/indicators.py`. An Indicator is a building block; a Strategy may use one or many. Indicators do not emit directions on their own anymore — direction-emitting wrappers live in `lib/strategies/`.
_Avoid_: study, overlay (overlay means the chart payload).

**Overlay**:
JSON-renderable strategy-specific chart data returned in `StrategyResult.overlays` — e.g., ribbon bands for the Ribbon strategy, levels for Trend SR Macro, probability lines for Polymarket. Distinct from user-toggled chart overlays (SMA 50, MACD) which are part of the Indicator Bundle.

### Backtesting

**Backtest Engine**:
The simulation routine paired with a Strategy by its `StrategyDef`. One of a closed set (e.g., `DIRECTION`, `CORPUS_TREND`, `CORPUS_TREND_LAYERED`, `RIBBON_REGIME`, `RIBBON_ACCUMULATION`, `MANAGED`, `CONFIRMATION_LAYERED`, `WEEKLY_CORE_DAILY_OVERLAY`). Lives in `lib/backtesting.py`.

**Backtest Result**:
The output of running a Backtest Engine: trades, equity curve, summary metrics. The Money Management Config governs how trades are sized.

**Money Management Config**:
The position-sizing rules (initial capital, max risk per trade, stop type, etc.) — a `MoneyManagementConfig` dataclass, orthogonal to Strategy.

**Confirmation Mode**:
An entry-layering modifier that stages capital across daily and weekly signals (`Daily 30 / Weekly 70`, `Daily 50 / Weekly 50`). Applies only to Strategies whose `StrategyDef` opts in. Implemented inside the Backtest Engine, not the Strategy.

### Chart payload

**Indicator Bundle**:
The per-request package of user-toggled chart Indicators (SMA 50, MACD, supertrend lines, etc.) computed for a ticker. Distinct from Strategy Overlays. Owned by the chart route.

**Chart Payload**:
The JSON response of `/api/chart` — OHLCV + Indicator Bundle + the selected Strategy's Backtest Result + that Strategy's Overlays.

### Portfolio

**Portfolio**:
A multi-strategy multi-ticker basket simulation. Runs Strategies across a watchlist and blends their equity curves.

**Watchlist**:
The user's saved list of tickers, with cached quotes and trend snapshots.

**Position**:
An imported holding from a Yahoo-style portfolio export (used in `/positions.html`). Distinct from a Trade (an open lot inside a Backtest Result).

**Regime**:
A market-state classification. Two distinct uses live in the codebase today (live regime detection vs. macro overlay for backtests); see flagged ambiguity.

## Relationships

- A **Strategy** has exactly one paired **Backtest Engine**.
- A **Strategy** produces one **StrategyResult** per ticker per request.
- A **StrategyResult** + **Money Management Config** + **Backtest Engine** → one **Backtest Result**.
- A **Chart Payload** = OHLCV + **Indicator Bundle** + **Backtest Result** + **Overlays**.
- An **Indicator** is a building block of one or many **Strategies**.
- A **Confirmation Mode** transforms how a **Backtest Engine** stages entries; it does not change the **Strategy**'s direction.

## Example dialogue

> **Dev:** Where do I add the new mean-reversion strategy?
> **Domain expert:** New file under `lib/strategies/`, then one entry in the **Strategy Registry**. The file exports a compute function returning a **StrategyResult** and declares its **Backtest Engine** in the **StrategyDef**.

> **Dev:** Does the strategy compute the supertrend line for the chart?
> **Domain expert:** No — the supertrend line is an **Indicator** in `lib/indicators.py`, included in the **Indicator Bundle** when the user toggles it. The **Strategy** only emits the direction. If the **Strategy** needs strategy-specific chart data (like ribbon bands for the ribbon strategy), it returns those in `StrategyResult.overlays`.

> **Dev:** What if my strategy needs daily and weekly confirmation?
> **Domain expert:** Declare `supports_confirmation=True` in your **StrategyDef**. The **Confirmation Mode** logic lives in the paired **Backtest Engine**, not in your compute function.

## Flagged ambiguities

- **Regime** has two uses: real-time market-state scoring (`lib/regime.py`, consumed by `/positions.html`) and a feature-built macro overlay for backtests (`lib/macro_regime.py`, consumed by portfolio backtesting). These are distinct concepts that share a word. Resolution pending — likely rename to `LiveRegime` and `RegimeOverlay`. Tracked as a separate deepening candidate.
- "Signal" was previously used for both `StrategyResult` (whole output) and "the latest direction value." Resolved: `StrategyResult` is the full output; "latest signal" or just `direction.iloc[-1]` for the most recent decision.
