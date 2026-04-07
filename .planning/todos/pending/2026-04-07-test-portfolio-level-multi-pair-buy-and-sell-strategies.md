---
created: 2026-04-07T01:28:00.000Z
title: Test portfolio-level multi-pair buy and sell strategies
area: testing
files:
  - lib/portfolio_backtesting.py
  - tests/
---

## Problem

Portfolio backtesting should be verified when strategies fire buy and sell across multiple instruments (pairs) and multiple open positions, not only single-symbol paths. We lack explicit tests that exercise cross-pair allocation, simultaneous or staggered entries/exits, and correct cash/position accounting when more than one leg is active.

## Solution

Add integration-style tests against `lib/portfolio_backtesting.py` (and any strategy hooks) that simulate multi-symbol portfolios: orders that span pairs, multiple holdings, and asserts on fills, balances, and realized behavior. Reuse existing test fixtures/mocks where possible; extend serialization or chart routes only if needed for regression coverage.
