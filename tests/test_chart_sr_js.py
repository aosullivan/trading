import json
import shutil
import subprocess
from pathlib import Path

import pytest


HELPER_PATH = Path(__file__).resolve().parents[1] / "static" / "chart_support_resistance.js"
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


class TestChartSupportResistanceHelpers:
    def test_visible_candle_range_uses_logical_window(self):
        result = run_js(
            """
const candles = [
  { time: 1, low: 100, high: 120 },
  { time: 2, low: 90, high: 130 },
  { time: 3, low: 80, high: 140 },
];
return helpers.getVisibleCandleRange(candles, { from: 0, to: 1 });
"""
        )
        assert result["low"] == 90
        assert result["high"] == 130

    def test_level_affects_autoscale_only_when_near_visible_range(self):
        result = run_js(
            """
const visibleRange = { low: 6200, high: 6800, span: 600 };
return {
  near: helpers.levelAffectsAutoscale({ price: 6127, zone_low: 6037, zone_high: 6218 }, visibleRange, 0.12),
  far: helpers.levelAffectsAutoscale({ price: 4200, zone_low: 4104, zone_high: 4285 }, visibleRange, 0.12),
};
"""
        )
        assert result["near"] is True
        assert result["far"] is False

    def test_select_visible_levels_excludes_overlapping_current_price_zone(self):
        result = run_js(
            """
const candles = [
  { time: 100, low: 6200, high: 6500 },
  { time: 200, low: 6300, high: 6600 },
  { time: 300, low: 6400, high: 6800 },
  { time: 400, low: 6300, high: 6700 },
];
const levels = [
  { type: 'support', price: 6539.17, zone_low: 6448.79, zone_high: 6629.55, touches: 8, touch_times: [350], pivot_times: [360] },
  { type: 'support', price: 6127.27, zone_low: 6036.89, zone_high: 6217.65, touches: 14, touch_times: [320], pivot_times: [330] },
  { type: 'support', price: 5704.82, zone_low: 5614.44, zone_high: 5795.20, touches: 15, touch_times: [340], pivot_times: [345] },
];
return helpers.selectVisibleLevels(levels, 'support', candles, { from: 0, to: 3 }, 6575.32, { bufferRatio: 0.12, maxVisible: 2 });
"""
        )
        assert [level["price"] for level in result] == [6127.27]

    def test_select_visible_levels_orders_by_recent_touch_before_window_end(self):
        result = run_js(
            """
const candles = [
  { time: 100, low: 5600, high: 6200 },
  { time: 200, low: 5750, high: 6350 },
  { time: 300, low: 5900, high: 6500 },
  { time: 400, low: 6000, high: 6650 },
];
const levels = [
  { type: 'support', price: 5900, zone_low: 5820, zone_high: 5980, touches: 6, touch_times: [210], pivot_times: [220] },
  { type: 'support', price: 6127.27, zone_low: 6036.89, zone_high: 6217.65, touches: 14, touch_times: [320], pivot_times: [330] },
];
return helpers.selectVisibleLevels(levels, 'support', candles, { from: 0, to: 3 }, 6500, { bufferRatio: 0.12, maxVisible: 2 });
"""
        )
        assert [level["price"] for level in result] == [6127.27, 5900]

    def test_get_level_render_start_time_prefers_latest_pivot_before_visible_end(self):
        result = run_js(
            """
const level = {
  pivot_times: [100, 220, 340],
  touch_times: [90, 210, 330],
};
return {
  beforeEnd: helpers.getLevelRenderStartTime(level, { from: 150, to: 300 }),
  afterEndFallback: helpers.getLevelRenderStartTime(level, { from: 150, to: 80 }),
};
"""
        )
        assert result["beforeEnd"] == 220
        assert result["afterEndFallback"] == 340

    def test_get_level_render_start_time_falls_back_to_touch_times(self):
        result = run_js(
            """
const level = {
  touch_times: [120, 260, 420],
};
return helpers.getLevelRenderStartTime(level, { from: 150, to: 300 });
"""
        )
        assert result == 260
