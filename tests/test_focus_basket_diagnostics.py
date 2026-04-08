"""Deterministic checks for the focus-basket diagnostics artifact generator."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

EXPECTED_VARIANT_IDS = {
    "baseline_none",
    "vol_trade",
    "vol_monthly",
    "vol_capped",
    "fixed_fraction_trade",
    "fixed_fraction_monthly",
    "fixed_fraction_atr_stop",
}
EXPECTED_TOP_LEVEL_KEYS = {
    "variants",
    "aggregate_rankings",
    "underperformance_findings",
    "phase4_implications",
}


def test_focus_basket_diagnostics_script_emits_expected_variants_and_sections(tmp_path):
    output_json = tmp_path / "focus-basket-diagnostics.json"
    env = os.environ.copy()
    env.setdefault("TRIEDINGVIEW_USER_DATA_DIR", tempfile.mkdtemp())

    subprocess.run(
        [
            sys.executable,
            "scripts/analyze_focus_basket_diagnostics.py",
            "--output-json",
            str(output_json),
            "--output-md",
            str(tmp_path / "focus-basket-diagnostics.md"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=True,
    )

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert set(payload) == EXPECTED_TOP_LEVEL_KEYS
    assert set(payload["variants"]) == EXPECTED_VARIANT_IDS
