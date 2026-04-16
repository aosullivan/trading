import json
import shutil
import subprocess
from pathlib import Path

import pytest


HELPER_PATH = Path(__file__).resolve().parents[1] / "static" / "js" / "trend_pulse_helpers.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def run_js(script_body: str):
    script = f"""
const helpers = require({json.dumps(str(HELPER_PATH))});
const result = (() => {{
{script_body}
}})();
console.log(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


class TestTrendPulseHelpers:
    def test_flip_tone_meta_penalizes_sparse_coverage_in_score(self):
        result = run_js(
            """
return {
  sparse: helpers.flipToneMeta(2, 0, 16),
  broad: helpers.flipToneMeta(14, 0, 16),
};
"""
        )

        assert result["sparse"]["tone"] == "bullish"
        assert result["sparse"]["coveragePct"] == 13
        assert result["sparse"]["score"] == 13
        assert result["broad"]["coveragePct"] == 88
        assert result["broad"]["score"] == 88

    def test_frame_summary_uses_total_possible_weight_for_strength(self):
        result = run_js(
            """
const frameFlips = {
  alpha: { dir: 'bullish', date: '2026-04-10' },
};
const keys = ['alpha', 'beta', 'gamma', 'delta'];
const weights = { alpha: 1, beta: 1, gamma: 1, delta: 1 };
return helpers.frameSummary(frameFlips, keys, weights, () => 4);
"""
        )

        assert result["bullish"] == 1
        assert result["bearish"] == 0
        assert result["possibleTotal"] == 4
        assert result["meta"]["coveragePct"] == 25
        assert result["meta"]["score"] == 25
