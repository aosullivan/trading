"""Backtest the MU ATR Outer-Threshold Mean-Reversion strategy on SPY daily."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.backtesting import backtest_direction
from lib.data_fetching import cached_download
from lib.mu_atr_mr_strategy import (
    MU_ATR_MR_LABEL,
    MU_ATR_MR_LOOKBACK,
    MU_ATR_MR_LOWER_THRESHOLD,
    MU_ATR_MR_UPPER_THRESHOLD,
    compute_mu_atr_mr_strategy,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--lookback", type=int, default=MU_ATR_MR_LOOKBACK)
    parser.add_argument("--lower", type=float, default=MU_ATR_MR_LOWER_THRESHOLD)
    parser.add_argument("--upper", type=float, default=MU_ATR_MR_UPPER_THRESHOLD)
    parser.add_argument("--show-trades", action="store_true")
    args = parser.parse_args()

    df = cached_download(args.ticker, start=args.start, end=args.end, interval="1d")
    if df is None or df.empty:
        print(f"No data for {args.ticker}", file=sys.stderr)
        return 1

    indicators = compute_mu_atr_mr_strategy(
        df,
        lookback=args.lookback,
        lower_threshold=args.lower,
        upper_threshold=args.upper,
    )
    direction = indicators["daily_direction"]
    trades, summary, _equity = backtest_direction(df, direction)

    print(f"=== {MU_ATR_MR_LABEL} on {args.ticker} ===")
    print(f"Period: {df.index[0].date()} → {df.index[-1].date()} ({len(df)} bars)")
    print(
        f"Params: lookback={args.lookback} lower={args.lower} upper={args.upper}"
    )
    print()
    print("Summary metrics:")
    for key in [
        "total_trades",
        "open_trades",
        "win_rate",
        "winners",
        "losers",
        "total_pnl",
        "realized_pnl",
        "open_pnl",
        "net_profit_pct",
        "avg_pnl",
        "best_trade",
        "worst_trade",
        "profit_factor",
        "max_drawdown_pct",
        "sharpe_ratio",
        "sortino_ratio",
        "ending_equity",
    ]:
        print(f"  {key:>20}: {summary[key]}")

    if args.show_trades:
        print()
        print("Trades:")
        for t in trades:
            tag = " [open]" if t.get("open") else ""
            print(
                f"  {t['entry_date']} → {t['exit_date']}  "
                f"entry={t['entry_price']:.2f} exit={t['exit_price']:.2f}  "
                f"pnl={t['pnl']:.2f} ({t['pnl_pct']:.2f}%){tag}"
            )

    print()
    print(json.dumps({"summary": summary, "n_trades": len(trades)}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
