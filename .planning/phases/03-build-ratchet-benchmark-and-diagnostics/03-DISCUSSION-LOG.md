# Phase 3: Build Ratchet Benchmark And Diagnostics - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-07
**Phase:** 03-build-ratchet-benchmark-and-diagnostics
**Areas discussed:** ratchet gate, basket scoring, out-of-market behavior, diagnostic priorities

---

## Ratchet gate

| Option | Description | Selected |
|--------|-------------|----------|
| Aggregate only | Promote any candidate that improves a single basket-wide aggregate score | |
| Aggregate plus guardrails | Promote only if aggregate score improves and no ticker has a major regression in drawdown or buy-and-hold-relative return | ✓ |
| Per-ticker unanimity | Require every ticker to improve on all tracked metrics before promotion | |

**User's choice:** Start with the recommended default: aggregate improvement plus per-ticker guardrails.
**Notes:** The user wants future strategy changes to stop backsliding after a real improvement is found, so the gate should reject obvious regressions even when one or two tickers look better.

---

## Basket scoring

| Option | Description | Selected |
|--------|-------------|----------|
| Best-ticker wins | Judge success mainly by the most improved ticker | |
| Equal-weight broad improvement | Use equal-weight basket scoring, require at least 5 of 7 tickers to improve, and avoid major failures on the rest | ✓ |
| Weighted discretionary basket | Weight the basket manually by conviction or market cap | |

**User's choice:** Start with the recommended equal-weight basket approach.
**Notes:** The focus basket is fixed at `BTC-USD`, `ETH-USD`, `COIN`, `TSLA`, `AAPL`, `NVDA`, and `GOOG`, and the benchmark should mean the same thing every time.

---

## Out-of-market behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Cash baseline | Treat out-of-market capital as cash during benchmarking and diagnostics | ✓ |
| Parking asset now | Add an index or secondary asset parking sleeve as part of Phase 3 | |
| Compare both immediately | Expand Phase 3 to benchmark both cash and parking modes from the start | |

**User's choice:** Start with the recommended cash baseline.
**Notes:** Parking-asset ideas are useful, but they would complicate the benchmark before the current baseline and failure modes are understood.

---

## Diagnostic priorities

| Option | Description | Selected |
|--------|-------------|----------|
| Narrow audit | Focus only on vol-normalized sizing and fixed-fraction sizing | |
| Recommended audit | Audit vol-normalized sizing, fixed-fraction sizing, stop/exit sensitivity, compounding mode, and other churn-inducing backtest knobs | ✓ |
| Broad redesign | Skip diagnostics and jump straight to redesigning strategy logic | |

**User's choice:** Start with the recommended diagnostic set.
**Notes:** The user explicitly wants to know why current backtest parameters make results worse, so diagnostics need to be reproducible and concrete before the next strategy-design phase starts.

---

## the agent's Discretion

- Exact benchmark artifact format
- Exact score formula used inside the ratchet gate
- Whether the benchmark harness is expressed as pytest fixtures, scripts, or both

## Deferred Ideas

- Parking capital in a non-cash sleeve while flat
- Layered in/out position logic for the actual strategy redesign
- New strategy concepts from the general brainstorming todo file
