"""Persistent user settings for portfolio sizing and signal generation."""

import json
import os
import threading

from lib.paths import get_user_data_path

_SETTINGS_FILE = get_user_data_path("settings.json")
_lock = threading.Lock()

DEFAULTS = {
    "portfolio_capital": 100_000.0,
    "sizing_model": "vol",
    "vol_scale_factor": 0.001,
    "risk_fraction": 0.01,
    "stop_type": "atr",
    "stop_atr_multiple": 3.0,
    "stop_pct": 0.05,
    "heat_limit": 0.20,
}


def load_settings() -> dict:
    with _lock:
        if os.path.exists(_SETTINGS_FILE):
            try:
                with open(_SETTINGS_FILE, encoding="utf-8") as f:
                    saved = json.load(f)
                merged = {**DEFAULTS, **saved}
                return merged
            except Exception:
                pass
        return dict(DEFAULTS)


def save_settings(settings: dict) -> dict:
    merged = {**DEFAULTS, **settings}
    for key in list(merged.keys()):
        if key not in DEFAULTS:
            del merged[key]
    with _lock:
        os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
    return merged
