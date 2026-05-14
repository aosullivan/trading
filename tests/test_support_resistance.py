import numpy as np
import pandas as pd
from unittest.mock import patch

from lib.support_resistance import body_extremes, classify_level_type, compute_support_resistance


class TestSupportResistanceClassification:
    def test_broken_resistance_below_price_becomes_support(self):
        level_type = classify_level_type(
            level_price=6127,
            current_price=6575,
            zone_width=90,
            sup_bounces=[1, 2],
            res_bounces=[3, 4, 5],
        )
        assert level_type == "support"

    def test_near_current_price_uses_bounce_dominance(self):
        level_type = classify_level_type(
            level_price=6539,
            current_price=6575,
            zone_width=90,
            sup_bounces=[1],
            res_bounces=[2, 3],
        )
        assert level_type == "resistance"

    def test_above_price_is_resistance(self):
        level_type = classify_level_type(
            level_price=6800,
            current_price=6575,
            zone_width=90,
            sup_bounces=[1],
            res_bounces=[2, 3],
        )
        assert level_type == "resistance"


class TestSupportResistanceDetection:
    def test_body_extremes_ignore_wicks(self):
        df = pd.DataFrame(
            {
                "Open": [100, 108],
                "High": [115, 118],
                "Low": [90, 92],
                "Close": [105, 102],
            }
        )

        body_highs, body_lows = body_extremes(df)

        assert list(body_highs) == [105, 108]
        assert list(body_lows) == [100, 102]

    def test_returns_zone_bounds_and_respects_limit(self, sample_df):
        levels = compute_support_resistance(sample_df, max_levels=4)
        assert len(levels) == 4
        for level in levels:
            assert level["zone_low"] < level["price"] < level["zone_high"]
            assert level["type"] in {"support", "resistance"}
            assert 0 <= level["respect"] <= 1
            assert level["touch_times"] == sorted(level["touch_times"])
            assert level["pivot_times"] == sorted(level["pivot_times"])

    def test_returns_empty_for_short_series(self, small_df):
        assert compute_support_resistance(small_df.head(25), max_levels=5) == []

    def test_support_levels_anchor_to_candle_bodies_not_long_lower_wicks(self):
        """Verify support anchors to body cluster (~100), not wick extremes (~85)."""
        dates = pd.date_range("2023-01-06", periods=120, freq="W-FRI")
        rows = []
        support_touch_indices = set(range(8, 112, 8))

        for i, dt in enumerate(dates):
            base = 113 + np.sin(i / 5) * 3
            open_price = base - 0.6
            close_price = base + 0.6
            low = min(open_price, close_price) - 1.5
            high = max(open_price, close_price) + 1.5

            if i in support_touch_indices:
                open_price = 102.0
                close_price = 100.5
                low = 85.0
                high = 104.0
            elif i - 1 in support_touch_indices:
                open_price = 101.5
                close_price = 107.0
                low = 100.0
                high = 108.0
            elif i + 1 in support_touch_indices:
                open_price = 108.0
                close_price = 104.0
                low = 103.0
                high = 109.0

            rows.append(
                {
                    "Open": open_price,
                    "High": high,
                    "Low": low,
                    "Close": close_price,
                    "Volume": 1_000_000 + i * 10_000,
                }
            )

        df = pd.DataFrame(rows, index=dates)

        levels = compute_support_resistance(df, max_levels=8)
        supports = [level for level in levels if level["type"] == "support"]

        assert supports, "Expected to detect at least one support level"
        nearest_support = max(
            (level for level in supports if level["price"] < float(df["Close"].iloc[-1])),
            key=lambda level: level["price"],
        )
        assert nearest_support["price"] > 95
        assert nearest_support["price"] < 110

    def test_recent_body_cluster_can_mark_weak_support_after_breakout(self):
        """Recent consolidation near prior resistance should survive as weak support."""
        dates = pd.date_range("2023-01-06", periods=140, freq="W-FRI")
        rows = []

        for i in range(100):
            base = 100 + i * 0.9 + np.sin(i / 4) * 2
            rows.append(
                {
                    "Open": base - 1,
                    "High": base + 3,
                    "Low": base - 3,
                    "Close": base + 1,
                    "Volume": 1_000_000,
                }
            )

        for open_price, close_price in [
            (238, 248),
            (250, 244),
            (243, 251),
            (252, 246),
            (245, 250),
            (249, 245),
            (246, 252),
            (253, 249),
        ]:
            rows.append(
                {
                    "Open": open_price,
                    "High": max(open_price, close_price) + 4,
                    "Low": min(open_price, close_price) - 4,
                    "Close": close_price,
                    "Volume": 1_200_000,
                }
            )

        for j, close_price in enumerate([260, 272, 285, 294, 292, 296, 294]):
            open_price = close_price - 5 if j % 2 == 0 else close_price + 4
            rows.append(
                {
                    "Open": open_price,
                    "High": max(open_price, close_price) + 5,
                    "Low": min(open_price, close_price) - 5,
                    "Close": close_price,
                    "Volume": 1_300_000,
                }
            )

        while len(rows) < len(dates):
            close_price = 294 + np.sin(len(rows)) * 2
            rows.append(
                {
                    "Open": close_price - 1,
                    "High": close_price + 3,
                    "Low": close_price - 3,
                    "Close": close_price,
                    "Volume": 900_000,
                }
            )

        df = pd.DataFrame(rows, index=dates)
        levels = compute_support_resistance(df, max_levels=8)
        supports = [level for level in levels if level["type"] == "support"]

        assert any(245 <= level["price"] <= 255 for level in supports)


class TestSupportResistanceRoutePayload:
    @patch("lib.cache.yf.download")
    def test_chart_payload_includes_zone_bounds(self, mock_download, client, sample_df):
        mock_download.return_value = sample_df

        response = client.get("/api/chart?ticker=TEST&start=2023-01-01")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["sr_levels"], "Expected chart payload to include support/resistance levels"
        sample_level = payload["sr_levels"][0]
        assert "zone_low" in sample_level
        assert "zone_high" in sample_level
        assert sample_level["zone_low"] < sample_level["zone_high"]
