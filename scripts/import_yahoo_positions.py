#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.paths import get_user_data_path
from lib.positions import load_yahoo_positions_export, summarize_positions


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import Yahoo Finance portfolio holdings from a saved HTML page."
    )
    parser.add_argument(
        "html",
        nargs="?",
        default="posn.html",
        help="Path to the saved Yahoo Finance portfolio HTML file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=get_user_data_path("positions.json"),
        help="Output positions JSON path. Defaults to the app user-data positions.json.",
    )
    args = parser.parse_args()

    rows = load_yahoo_positions_export(args.html)
    if not rows:
        raise SystemExit(f"No Yahoo holdings rows found in {args.html}")

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, indent=2) + "\n")

    summary = summarize_positions(rows)
    print(f"Wrote {len(rows)} positions to {output}")
    print(f"Market value: ${summary['market_value']:,.2f}")
    print(f"Cost basis: ${summary['cost_basis']:,.2f}")
    print(f"Daily PnL: ${summary['day_change']:,.2f}")
    print(f"Total PnL: ${summary['unrealized_gain_loss']:,.2f}")
    print(f"Accounts: {summary['account_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
