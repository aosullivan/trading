from unittest.mock import patch

from support_resistance import classify_level_type, compute_support_resistance


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


class TestSupportResistanceRoutePayload:
    @patch("app.yf.download")
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
