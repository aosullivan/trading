---
created: 2026-04-07T01:28:00.000Z
title: Test index tracker parking when out of market vs cash
area: testing
files:
  - lib/portfolio_backtesting.py
  - lib/backtesting.py
  - tests/
---

## Problem

When the strategy is flat or "out of the market," capital may be modeled as idle cash today. We want the option to park proceeds in a broad index tracker (synthetic or second symbol) instead of cash, and we need tests that define expected returns, rebalancing, and edge cases (full exit, partial size, fees) for that mode.

## Solution

Specify or implement a "parking" instrument (e.g. SPY/VTI proxy in tests with mocked series), add portfolio/backtest parameters for cash vs index parking, and write tests that compare equity paths and position state when flat: cash baseline vs index-held baseline. TBD exact API; align with existing portfolio backtest interfaces.
