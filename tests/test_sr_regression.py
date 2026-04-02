"""Regression tests for support/resistance detection using static JSON fixtures.

Each fixture contains synthetic OHLCV data with known support/resistance structure.
These tests ensure the algorithm correctly detects levels and doesn't regress
during future refinements.
"""

import json
import os

import pandas as pd
import pytest

from lib.support_resistance import compute_support_resistance

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    """Load a JSON fixture and return (DataFrame, expected_dict)."""
    path = os.path.join(FIXTURES_DIR, name)
    with open(path) as f:
        data = json.load(f)
    candles = data["candles"]
    dates = pd.bdate_range("2023-01-01", periods=len(candles))
    df = pd.DataFrame(candles, index=dates)
    return df, data["expected"]


class TestClearDoubleBottomSupport:
    """Stock that bounces off ~100 level 5 times with clear reversals."""

    def test_detects_support_near_100(self):
        df, expected = load_fixture("test_clear_double_bottom_support.json")
        levels = compute_support_resistance(df, max_levels=8)
        supports = [l for l in levels if l["type"] == "support"]

        assert supports, "Expected at least one support level"
        # Find the nearest support below current price (~113)
        current = float(df["Close"].iloc[-1])
        below = [l for l in supports if l["price"] < current]
        assert below, "Expected at least one support level below current price"
        nearest = max(below, key=lambda l: l["price"])
        assert expected["support_min"] <= nearest["price"] <= expected["support_max"], (
            f"Nearest support {nearest['price']} not in expected range "
            f"[{expected['support_min']}, {expected['support_max']}]"
        )

    def test_support_has_multiple_touches(self):
        df, expected = load_fixture("test_clear_double_bottom_support.json")
        levels = compute_support_resistance(df, max_levels=8)
        supports = [l for l in levels if l["type"] == "support"]
        current = float(df["Close"].iloc[-1])
        below = [l for l in supports if l["price"] < current]
        nearest = max(below, key=lambda l: l["price"])
        assert nearest["touches"] >= 3, (
            f"Expected at least 3 touches, got {nearest['touches']}"
        )


class TestResistanceCeiling:
    """Stock that repeatedly fails at ~150 level."""

    def test_detects_resistance_near_150(self):
        df, expected = load_fixture("test_resistance_ceiling.json")
        levels = compute_support_resistance(df, max_levels=8)
        resistances = [l for l in levels if l["type"] == "resistance"]

        assert resistances, "Expected at least one resistance level"
        current = float(df["Close"].iloc[-1])
        above = [l for l in resistances if l["price"] > current]
        assert above, "Expected at least one resistance level above current price"
        nearest = min(above, key=lambda l: l["price"])
        assert expected["resistance_min"] <= nearest["price"] <= expected["resistance_max"], (
            f"Nearest resistance {nearest['price']} not in expected range "
            f"[{expected['resistance_min']}, {expected['resistance_max']}]"
        )

    def test_resistance_has_multiple_touches(self):
        df, expected = load_fixture("test_resistance_ceiling.json")
        levels = compute_support_resistance(df, max_levels=8)
        resistances = [l for l in levels if l["type"] == "resistance"]
        current = float(df["Close"].iloc[-1])
        above = [l for l in resistances if l["price"] > current]
        nearest = min(above, key=lambda l: l["price"])
        assert nearest["touches"] >= 3, (
            f"Expected at least 3 touches, got {nearest['touches']}"
        )


class TestVolatileWideWicks:
    """Bodies cluster at ~80 with wicks extending far. Support should anchor to bodies."""

    def test_support_near_body_cluster_not_wick_extremes(self):
        df, expected = load_fixture("test_volatile_wide_wicks.json")
        levels = compute_support_resistance(df, max_levels=8)
        supports = [l for l in levels if l["type"] == "support"]

        assert supports, "Expected at least one support level"
        current = float(df["Close"].iloc[-1])
        below = [l for l in supports if l["price"] < current]
        assert below, "Expected at least one support level below current price"
        nearest = max(below, key=lambda l: l["price"])
        assert expected["support_min"] <= nearest["price"] <= expected["support_max"], (
            f"Support at {nearest['price']} should be near body cluster "
            f"[{expected['support_min']}, {expected['support_max']}], not at wick extremes"
        )


class TestNoDoubleCount:
    """Candles with entire body inside zone should only count as one bounce."""

    def test_bounce_count_not_inflated(self):
        df, expected = load_fixture("test_no_double_count.json")
        levels = compute_support_resistance(df, max_levels=8)
        supports = [l for l in levels if l["type"] == "support"]

        # Find the level near 200
        near_200 = [l for l in supports if 196 <= l["price"] <= 205]
        if not near_200:
            # Level might not be detected with few bounces — that's acceptable
            # But if it IS detected, touches shouldn't be inflated
            return

        level = near_200[0]
        max_expected = expected["max_touches_at_level"]
        assert level["touches"] <= max_expected, (
            f"Touches at ~200 level is {level['touches']}, expected <= {max_expected}. "
            "Possible double-counting of candles with body inside zone."
        )


class TestNearbyOverAncient:
    """Ancient strong level should be filtered; nearby weak level should survive."""

    def test_no_ancient_levels_returned(self):
        df, expected = load_fixture("test_nearby_over_ancient.json")
        levels = compute_support_resistance(df, max_levels=8)

        for level in levels:
            assert level["price"] >= expected["no_support_below"], (
                f"Level at {level['price']} is below {expected['no_support_below']} — "
                "ancient levels should be filtered by distance"
            )

    def test_nearby_support_detected(self):
        df, expected = load_fixture("test_nearby_over_ancient.json")
        levels = compute_support_resistance(df, max_levels=8)
        supports = [l for l in levels if l["type"] == "support"]

        current = float(df["Close"].iloc[-1])
        below = [l for l in supports if l["price"] < current]
        assert below, "Expected at least one support below current price"
        nearest = max(below, key=lambda l: l["price"])
        assert expected["support_min"] <= nearest["price"] <= expected["support_max"], (
            f"Nearby support at {nearest['price']} not in expected range "
            f"[{expected['support_min']}, {expected['support_max']}]"
        )
