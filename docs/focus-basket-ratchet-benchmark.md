# Focus-Basket Ratchet Benchmark

Phase 3 promotes one shared regression benchmark for `BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, and `GOOG`. The benchmark uses the live app contract, not a second scoring engine: every assertion goes through `GET /api/chart` and reads the currently promoted strategy payload plus the same `buy_hold_equity_curve` the UI compares against.

## Spec

The machine-readable source of truth is [`tests/fixtures/focus_basket_benchmarks.json`](/Users/adrianosullivan/projects/trading/tests/fixtures/focus_basket_benchmarks.json).

It pins:

- `tickers`: the seven-ticker basket in fixed order
- `chart_request`: `interval=1d`, `start=2020-01-01`, `end=2026-04-04`, `period=10`, `multiplier=2.5`
- `strategy_key`: `cci_hysteresis`
- `score_formula`: `score = net_profit_pct - 0.35 * max_drawdown_pct - max(0, buy_hold_net_profit_pct - net_profit_pct)`
- `aggregate_score_floor`: the promoted basket-average score floor
- `approved_policy`: the currently approved promotion contract
  - `min_tickers_improved`: the 5-of-7 promotion gate
  - `base_drawdown_regression_limit_pct`: the starting allowed per-ticker drawdown slippage
  - `moderate_overshoot_limit_pct`: how much overshoot still counts as a moderate blocker
  - `max_moderate_violations`: how many moderate blockers are tolerated
  - `max_severe_violations`: how many severe blockers are tolerated
  - `buy_hold_gap_regression_limit_pct`: allowed per-ticker buy-and-hold-relative slippage before the ratchet fails

## Why This Is A Ratchet

This guard is stricter than a single-ticker "beat HODL" test:

- it measures the same seven names every time instead of cherry-picking the one symbol that likes a change
- it requires the basket-average score to stay at or above the promoted floor
- it requires at least 5 of 7 tickers to match or improve their promoted score
- it still blocks major per-ticker regressions in drawdown and buy-and-hold-relative performance even if the basket average still looks okay
- it now distinguishes moderate drawdown drift from severe drawdown drift instead of treating every overshoot as the same kind of veto

That combination makes it suitable for strategy promotion: future changes only become the new baseline when they improve the agreed scorecard instead of shifting risk into one or two lucky tickers.

## Frozen Fixtures

The committed CSV fixtures live under [`tests/fixtures/focus_basket`](/Users/adrianosullivan/projects/trading/tests/fixtures/focus_basket). They are downloaded with the same warmup rule as `/api/chart`: `DAILY_WARMUP_DAYS` before the requested `start` date, with an exclusive-end download one day past the chart `end`.

Regenerate them from the repo root:

```bash
python scripts/regen_focus_basket_benchmark_fixtures.py
```

Validate the committed set without downloading anything:

```bash
python scripts/regen_focus_basket_benchmark_fixtures.py --check
```

## Regression Test

[`tests/test_focus_basket_benchmark_backtests.py`](/Users/adrianosullivan/projects/trading/tests/test_focus_basket_benchmark_backtests.py) patches `routes.chart.cached_download` to read only the frozen CSVs, then requests `/api/chart` once per basket ticker. The test computes:

- `net_profit_pct` from `strategies[spec["strategy_key"]]["summary"]`
- `max_drawdown_pct` from the same summary
- `buy_hold_net_profit_pct` from `strategies[spec["strategy_key"]]["buy_hold_equity_curve"]`
- `score` using `score = net_profit_pct - 0.35 * max_drawdown_pct - max(0, buy_hold_net_profit_pct - net_profit_pct)`

Promotion workflow:

1. Regenerate fixtures if the market window intentionally changes.
2. Run `pytest tests/test_focus_basket_benchmark_backtests.py`.
3. Update the pinned metrics in the JSON and the promoted baseline summary in `.planning/` only when you intentionally accept a stronger baseline.

## Latest Promotion Decision

The latest formal promotion decision evaluated a genuinely new CCI-family mechanic, `cci_hysteresis`, on the same frozen basket under the approved policy `tiered_drawdown_v1`.

Outcome:

- it improved score on `7 of 7` tickers versus the previously promoted `corpus_trend` floor
- its aggregate candidate score is `311.52` versus the previous promoted floor `-479.94`
- it has no buy-and-hold-gap violations
- it has no severe drawdown blockers
- it has exactly three moderate drawdown blockers: `ETH-USD`, `COIN`, and `NVDA`
- the approved policy allows up to three moderate blockers, so the candidate clears the fixed contract

So the ratchet outcome is currently:

- approved policy: `tiered_drawdown_v1`
- promoted baseline: `cci_hysteresis`
- current promoted floor: `311.52`
- strongest known failing comparison under the new floor: `weekly_core_overlay_v1`

This is the benchmark doing the job it was designed for: a new family is only promoted once it clears the same contract cleanly enough to become the new shared floor for future work.

## Alternative Architecture Search

After the weekly-core/daily-overlay line was exhausted, the repo ran a v1.5 architecture scan across the currently supported built-in families on the same frozen basket.

That scan did **not** produce a promotion-ready successor yet, but it did narrow the next branch cleanly:

- best new alternative-family continuation candidate: `bb_breakout`
- family read: volatility-band breakout
- current blocker story:
  - buy-and-hold gap violation on `COIN`
  - severe drawdown blockers on `ETH-USD`, `COIN`, and `GOOG`

So the benchmark posture is now more specific:

- overall promoted baseline remains `corpus_trend`
- strongest historical non-promoted comparison candidate remains `tsla_donchian_keltner_70_30_v1`
- strongest new alternative-family continuation lead is `bb_breakout`

## Breakout Family Final Reduction

After `bb_breakout` and then `coin_goog_keltner_v1` narrowed the alternative-family search, the repo ran one final breakout-family reduction pass in v1.7.

That pass also did **not** produce a promotion-ready successor, but it finished the branch cleanly:

- strongest final breakout-family candidate: `coin_goog_keltner_coin_esc50_v1`
- basket read:
  - aggregate candidate score: `319.36`
  - improved tickers: `6 of 7`
  - buy-and-hold gap violation: `COIN`
  - moderate drawdown blockers: `NVDA`, `GOOG`
  - severe drawdown blocker: `ETH-USD`

The decisive result is what happened when the repo tried to remove the final `ETH-USD` severe blocker inside the same family:

- a same-family `ETH-USD` confirmation probe did remove the severe drawdown label
- but it also turned `ETH-USD` into a buy-and-hold-gap violation and pushed aggregate score below `0`
- the combined `COIN` + `ETH-USD` probe cleared the severe set entirely, but still failed badly on participation and score

So the benchmark posture is now:

- approved policy still fixed at `tiered_drawdown_v1`
- promoted baseline still retained at `corpus_trend`
- breakout-family line exhausted under the fixed contract

## Post-Breakout Family Search

After the breakout family was exhausted, the repo reopened the search across the strongest remaining confirmation-aware regime families.

That v1.8 shortlist did not produce a promotion-ready winner either, but it did narrow the next live branch:

- best remaining family lead: `ema_crossover`
- best same-family hardening probe: `ema_crossover__layered_50_50`

Current family read:

- raw `ema_crossover` has aggregate score `533.18`
- it improves all `7 of 7` basket tickers
- it has no buy-and-hold-gap violations
- it is still blocked by concentrated severe drawdown on `ETH-USD`, `COIN`, `TSLA`, and `GOOG`

Why the family remains interesting:

- `ema_crossover__layered_50_50` reduces the severe set from `4` names to `2`
- it keeps buy-and-hold-gap posture clean
- but it gives up too much aggregate score today, so it is hardening evidence rather than a replacement lead

So the benchmark posture is now even narrower:

- promoted baseline remains `corpus_trend`
- weekly-core/daily-overlay is exhausted
- breakout family is exhausted
- `ema_crossover` is the strongest remaining continuation-worthy family

## EMA Family First Hardening Pass

The first dedicated EMA-family hardening pass also closed with a clear result:

- strongest active EMA-family candidate: `ema_equity_confirmed_v1`
- construction: raw `ema_crossover` plus ticker-scoped `layered_50_50` confirmation only on `TSLA`, `NVDA`, and `GOOG`

Current read:

- aggregate score: `164.65`
- improved tickers: `7 of 7`
- buy-and-hold-gap violations: none
- moderate blocker: `GOOG`
- severe blockers: `ETH-USD`, `COIN`

That means the first EMA hardening pass materially improved the family:

- severe blocker count fell from `4` to `2`
- equity-side blocker work is mostly done for now
- the remaining family question is now crypto-specific

So the benchmark posture is now:

- promoted baseline remains `corpus_trend`
- strongest active continuation branch is the EMA family
- strongest active EMA candidate is `ema_equity_confirmed_v1`
- the next serious question is whether the EMA family can solve `ETH-USD` and `COIN` without giving back its equity-side gains

## EMA Crypto Control Exhaustion

The next EMA milestone answered that supported-control question directly.

Representative crypto-focused EMA prototypes showed:

- clean `COIN` confirmation controls barely changed the contract read at all
- stronger `COIN` controls removed the severe blocker only by turning `COIN` into a buy-and-hold-gap failure
- stronger `ETH-USD` controls removed the severe blocker only by turning `ETH-USD` into a buy-and-hold-gap failure and driving the basket score negative
- combined crypto controls cleared the severe set only by failing the broader contract badly

So the benchmark posture is now:

- promoted baseline remains `corpus_trend`
- weekly-core/daily-overlay is exhausted
- breakout family is exhausted
- the current EMA confirmation line is also exhausted
- `ema_equity_confirmed_v1` remains the strongest current EMA-family candidate, but moving past it now requires new EMA-family mechanics or a fresh architecture search

## Post-EMA Family Search

After the current EMA confirmation line was exhausted, the repo reopened the family search across the strongest remaining non-exhausted built-in branches.

That v1.11 pass did not produce a promotion-ready winner either, but it selected one clean continuation branch:

- best remaining family lead: `cci_trend`
- best bounded hardening probe: `cci_trend__layered_50_50`

Current family read:

- raw `cci_trend` aggregate score: `740.62`
- raw `cci_trend` improves `6 of 7` basket tickers
- raw `cci_trend` has one buy-and-hold-gap violation on `COIN`
- raw `cci_trend` is still blocked by a very broad severe set: `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, `GOOG`

Why the family still matters:

- `cci_trend__layered_50_50` compresses that severe set down to just `ETH-USD` and `COIN`
- it keeps improved breadth at `6 of 7`
- it does not add any moderate blockers
- it keeps the buy-and-hold-gap issue confined to `COIN`

Why the family is not promoted yet:

- the cleanest current control still fails on the residual crypto pair
- the aggregate score under that bounded control drops too far to treat it as a replacement baseline today

So the benchmark posture is now:

- promoted baseline remains `corpus_trend`
- weekly-core/daily-overlay is exhausted
- breakout family is exhausted
- the current EMA confirmation line is exhausted
- `cci_trend` is the strongest remaining continuation-worthy family
- the next live question is whether targeted CCI hardening can solve `ETH-USD` and `COIN` without giving back the equity cleanup already achieved by `cci_trend__layered_50_50`

## CCI Family Final Hardening Read

The next CCI milestone tested exactly that residual crypto question with bounded targeted follow-ups.

Representative targeted CCI probes showed:

- the best `COIN`-targeted follow-up, `coin_raw_v1`, only improves aggregate score slightly
- but that move leaves the blocker posture unchanged: `COIN` still fails the buy-and-hold-gap test and both `ETH-USD` and `COIN` remain severe drawdown blockers
- the only useful `ETH-USD`-targeted move, `eth_escalation_50_50_v1`, removes `ETH-USD` from the severe set only by turning it into a new buy-and-hold-gap failure and sharply reducing score
- the combined probe, `coin_raw_eth_escalation_50_50_v1`, confirms there is no clean score-preserving route through the residual crypto pair inside the current route-supported CCI surface

## Novel CCI Mechanics Promotion

After the route-supported CCI line was exhausted, the repo introduced genuinely new CCI-family mechanics instead of adding more confirmation remixes.

The decisive mechanic was `cci_hysteresis` with the frozen live-route posture `period=30`, `entry=150`, `exit=-40`.

Current promoted read:

- aggregate score: `311.52`
- improved tickers: `7 of 7`
- buy-and-hold-gap violations: none
- moderate drawdown blockers: `ETH-USD`, `COIN`, `NVDA`
- severe drawdown blockers: none

That means the benchmark posture is now:

- promoted baseline is `cci_hysteresis`
- approved policy remains `tiered_drawdown_v1`
- weekly-core/daily-overlay, breakout, the current EMA confirmation line, and the old route-supported CCI line remain exhausted as promoted-baseline candidates
- `weekly_core_overlay_v1` is the strongest current failing comparison under the new floor
- the next strategy search should start from this stronger promoted baseline rather than reopening older exhausted branches
