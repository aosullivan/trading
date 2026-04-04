---
status: testing
phase: 02-implement-corpus-derived-strategy
source:
  - .planning/phases/02-implement-corpus-derived-strategy/02-01-SUMMARY.md
  - .planning/phases/02-implement-corpus-derived-strategy/02-02-SUMMARY.md
started: 2026-04-04T19:50:07Z
updated: 2026-04-04T19:50:07Z
---

## Current Test

number: 1
name: Strategy Selector Shows Corpus Trend Without Changing Default
expected: |
  Open the Backtest report. The strategy selector still shows Trend-Driven first,
  and Corpus Trend (Donchian/ATR) appears as an additional selectable option.
awaiting: user response

## Tests

### 1. Strategy Selector Shows Corpus Trend Without Changing Default
expected: Open the Backtest report. The strategy selector still shows Trend-Driven first, and Corpus Trend (Donchian/ATR) appears as an additional selectable option.
result: [pending]

### 2. Corpus Trend Report Renders Trades and Stats
expected: Select Corpus Trend (Donchian/ATR). The Strategy Report updates without errors and shows an equity curve, summary stats, and trades table data for the selected ticker/range.
result: [pending]

### 3. Switching Back To Trend-Driven Still Works
expected: Switch the selector back to Trend-Driven. The report still refreshes correctly and the existing default strategy behavior appears intact.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps

[none yet]
