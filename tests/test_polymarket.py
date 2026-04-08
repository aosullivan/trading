"""Tests for Polymarket history bootstrap and signal fallbacks."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import lib.polymarket as polymarket


def test_load_probability_history_auto_seeds_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(polymarket, "_POLYMARKET_DISK_CACHE_DIR", str(tmp_path))

    seeded = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-01-01"),
                "skew_ratio": 1.25,
                "bull_probability": 0.4,
                "bear_probability": 0.32,
                "spot_price": 70000.0,
            }
        ]
    ).set_index("date")

    def fake_seed():
        history_file = Path(tmp_path) / "probability_history.json"
        history_file.write_text(
            json.dumps(
                [
                    {
                        "date": "2026-01-01",
                        "skew_ratio": 1.25,
                        "bull_probability": 0.4,
                        "bear_probability": 0.32,
                        "spot_price": 70000.0,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return seeded

    monkeypatch.setattr(polymarket, "seed_probability_history", fake_seed)

    loaded = polymarket.load_probability_history(auto_seed=True)

    assert len(loaded) == 1
    assert round(float(loaded.iloc[0]["skew_ratio"]), 2) == 1.25


def test_compute_polymarket_direction_series_uses_seeded_history_shape():
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    ohlcv = pd.DataFrame(
        {
            "Open": [1, 1, 1, 1, 1],
            "High": [1, 1, 1, 1, 1],
            "Low": [1, 1, 1, 1, 1],
            "Close": [1, 1, 1, 1, 1],
            "Volume": [1, 1, 1, 1, 1],
        },
        index=idx,
    )
    history = pd.DataFrame(
        {
            "skew_ratio": [1.25, 1.3, 0.75, 0.7, 0.72],
            "bull_probability": [0.4, 0.41, 0.2, 0.19, 0.2],
            "bear_probability": [0.3, 0.31, 0.35, 0.36, 0.35],
        },
        index=idx,
    )

    direction = polymarket.compute_polymarket_direction_series(
        ohlcv,
        probability_history_df=history,
        momentum_window=2,
    )

    assert direction.tolist()[0] == 1
    assert direction.tolist()[-1] == -1


def test_parse_price_markets_excludes_non_price_questions():
    raw_markets = [
        {
            "id": "1",
            "question": "Will Bitcoin reach $100,000 by December 31, 2026?",
            "outcomePrices": "[\"0.35\",\"0.65\"]",
            "volumeNum": 1000,
            "liquidityNum": 100,
            "clobTokenIds": "[\"tok-1\"]",
            "endDateIso": "2026-12-31T00:00:00Z",
            "bestBid": 0.34,
            "bestAsk": 0.36,
        },
        {
            "id": "2",
            "question": "Will El Salvador hold $1b+ of BTC by December 31, 2026?",
            "outcomePrices": "[\"0.33\",\"0.67\"]",
            "volumeNum": 1000,
            "liquidityNum": 100,
            "clobTokenIds": "[\"tok-2\"]",
            "endDateIso": "2026-12-31T00:00:00Z",
            "bestBid": 0.32,
            "bestAsk": 0.34,
        },
    ]

    parsed = polymarket._parse_price_markets(raw_markets)

    assert len(parsed) == 1
    assert parsed[0]["question"] == "Will Bitcoin reach $100,000 by December 31, 2026?"
    assert parsed[0]["strike_price"] == 100000.0
