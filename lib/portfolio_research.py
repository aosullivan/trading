"""Canonical portfolio research matrix definitions for v1.18."""

from __future__ import annotations

from collections.abc import Iterable

from lib.synthetic_stress import DEFAULT_SYNTHETIC_STRESS_SCENARIOS

RESEARCH_MATRIX_VERSION = "portfolio_rotation_matrix_v1"
DEFAULT_RESEARCH_HEAT_LIMIT = 0.20
DEFAULT_RESEARCH_TAGS = ["research", "v1.18", "portfolio-rotation"]
DEFAULT_RESEARCH_STRATEGIES = [
    "ribbon",
    "corpus_trend",
    "cci_hysteresis",
]
DEFAULT_RESEARCH_ALLOCATOR_POLICIES = [
    "signal_flip_v1",
    "signal_equal_weight_redeploy_v1",
    "signal_top_n_strength_v1",
    "core_plus_rotation_v1",
]
DEFAULT_RESEARCH_MONEY_MANAGEMENT = {
    "sizing_method": "fixed_fraction",
    "stop_type": "atr",
    "stop_atr_period": 20,
    "stop_atr_multiple": 3.0,
    "initial_capital": 10000,
}

RESEARCH_BASKETS = {
    "focus_7": {
        "label": "Focus 7",
        "tickers": ["BTC-USD", "ETH-USD", "COIN", "TSLA", "AAPL", "NVDA", "GOOG"],
        "purpose": "Continuity with the mixed crypto and growth focus basket.",
    },
    "growth_5": {
        "label": "Growth 5",
        "tickers": ["AAPL", "MSFT", "NVDA", "AMZN", "META"],
        "purpose": "Concentrated large-cap growth portfolio.",
    },
    "diversified_10": {
        "label": "Diversified 10",
        "tickers": ["AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA", "JPM", "XOM", "COST", "UNH"],
        "purpose": "Broader equity portfolio with more sector spread.",
    },
}

RESEARCH_WINDOWS = {
    "crash_recovery_2020_2021": {
        "label": "Crash And Recovery (2020-2021)",
        "start": "2020-01-01",
        "end": "2021-12-31",
        "purpose": "Crisis shock plus strong recovery.",
    },
    "drawdown_chop_2022": {
        "label": "Drawdown Chop (2022)",
        "start": "2022-01-01",
        "end": "2022-12-31",
        "purpose": "Weak and choppy drawdown regime.",
    },
    "bull_recovery_2023_2025": {
        "label": "Bull Recovery (2023-2025)",
        "start": "2023-01-01",
        "end": "2025-12-31",
        "purpose": "Recent broad recovery and upside participation window.",
    },
}

MACRO_OVERLAY_MATRIX_VERSION = "macro_regime_overlay_matrix_v1"
SYNTHETIC_STRESS_MATRIX_VERSION = "synthetic_stress_matrix_v1"
DEFAULT_MACRO_OVERLAY_TAGS = ["research", "v1.19", "macro-overlay"]
DEFAULT_MACRO_OVERLAY_STRATEGIES = list(DEFAULT_RESEARCH_STRATEGIES)
DEFAULT_MACRO_OVERLAY_ALLOCATOR_POLICIES = [
    "signal_top_n_strength_v1",
    "core_plus_rotation_v1",
]
V18_BEST_PAIR = {
    "strategy": "cci_hysteresis",
    "allocator_policy": "signal_top_n_strength_v1",
}
V19_BEST_NEAR_MISS = {
    "strategy": "ribbon",
    "allocator_policy": "signal_top_n_strength_v1",
    "config_id": "macro63_high_core",
}
DEFAULT_MACRO_OVERLAY_CONFIGS = [
    {
        "id": "macro63_balanced",
        "label": "63d Balanced",
        "macro_config": {
            "yield_lookback_bars": 63,
            "yield_good_bps": -20.0,
            "yield_bad_bps": 25.0,
            "yield_weight": 0.55,
            "election_weight": 0.25,
            "breadth_weight": 0.85,
            "breadth_good_pct": 0.67,
            "breadth_bad_pct": 0.34,
            "risk_on_threshold": 0.75,
            "risk_off_threshold": -0.35,
            "risk_on_core_pct": 0.90,
            "neutral_core_pct": 0.60,
            "risk_off_core_pct": 0.30,
        },
    },
    {
        "id": "macro63_cut_sensitive",
        "label": "63d Cut Sensitive",
        "macro_config": {
            "yield_lookback_bars": 63,
            "yield_good_bps": -10.0,
            "yield_bad_bps": 20.0,
            "yield_weight": 0.70,
            "election_weight": 0.15,
            "breadth_weight": 0.80,
            "breadth_good_pct": 0.65,
            "breadth_bad_pct": 0.35,
            "risk_on_threshold": 0.70,
            "risk_off_threshold": -0.30,
            "risk_on_core_pct": 0.92,
            "neutral_core_pct": 0.58,
            "risk_off_core_pct": 0.25,
        },
    },
    {
        "id": "macro63_breadth_guarded",
        "label": "63d Breadth Guarded",
        "macro_config": {
            "yield_lookback_bars": 63,
            "yield_good_bps": -20.0,
            "yield_bad_bps": 25.0,
            "yield_weight": 0.45,
            "election_weight": 0.20,
            "breadth_weight": 1.10,
            "breadth_good_pct": 0.70,
            "breadth_bad_pct": 0.40,
            "risk_on_threshold": 0.85,
            "risk_off_threshold": -0.20,
            "risk_on_core_pct": 0.88,
            "neutral_core_pct": 0.55,
            "risk_off_core_pct": 0.35,
        },
    },
    {
        "id": "macro21_fast_macro",
        "label": "21d Fast Macro",
        "macro_config": {
            "yield_lookback_bars": 21,
            "yield_good_bps": -10.0,
            "yield_bad_bps": 15.0,
            "yield_weight": 0.65,
            "election_weight": 0.20,
            "breadth_weight": 0.85,
            "breadth_good_pct": 0.67,
            "breadth_bad_pct": 0.34,
            "risk_on_threshold": 0.75,
            "risk_off_threshold": -0.30,
            "risk_on_core_pct": 0.90,
            "neutral_core_pct": 0.58,
            "risk_off_core_pct": 0.28,
        },
    },
    {
        "id": "macro126_slow_macro",
        "label": "126d Slow Macro",
        "macro_config": {
            "yield_lookback_bars": 126,
            "yield_good_bps": -30.0,
            "yield_bad_bps": 30.0,
            "yield_weight": 0.45,
            "election_weight": 0.30,
            "breadth_weight": 0.90,
            "breadth_good_pct": 0.67,
            "breadth_bad_pct": 0.34,
            "risk_on_threshold": 0.70,
            "risk_off_threshold": -0.35,
            "risk_on_core_pct": 0.88,
            "neutral_core_pct": 0.62,
            "risk_off_core_pct": 0.32,
        },
    },
    {
        "id": "macro63_high_core",
        "label": "63d High Core",
        "macro_config": {
            "yield_lookback_bars": 63,
            "yield_good_bps": -20.0,
            "yield_bad_bps": 25.0,
            "yield_weight": 0.55,
            "election_weight": 0.25,
            "breadth_weight": 0.85,
            "breadth_good_pct": 0.67,
            "breadth_bad_pct": 0.34,
            "risk_on_threshold": 0.65,
            "risk_off_threshold": -0.45,
            "risk_on_core_pct": 0.98,
            "neutral_core_pct": 0.78,
            "risk_off_core_pct": 0.45,
        },
    },
    {
        "id": "macro21_high_core",
        "label": "21d High Core",
        "macro_config": {
            "yield_lookback_bars": 21,
            "yield_good_bps": -10.0,
            "yield_bad_bps": 15.0,
            "yield_weight": 0.65,
            "election_weight": 0.20,
            "breadth_weight": 0.85,
            "breadth_good_pct": 0.67,
            "breadth_bad_pct": 0.34,
            "risk_on_threshold": 0.65,
            "risk_off_threshold": -0.45,
            "risk_on_core_pct": 0.98,
            "neutral_core_pct": 0.76,
            "risk_off_core_pct": 0.42,
        },
    },
    {
        "id": "macro63_very_high_core",
        "label": "63d Very High Core",
        "macro_config": {
            "yield_lookback_bars": 63,
            "yield_good_bps": -20.0,
            "yield_bad_bps": 25.0,
            "yield_weight": 0.55,
            "election_weight": 0.25,
            "breadth_weight": 0.85,
            "breadth_good_pct": 0.67,
            "breadth_bad_pct": 0.34,
            "risk_on_threshold": 0.65,
            "risk_off_threshold": -0.50,
            "risk_on_core_pct": 1.00,
            "neutral_core_pct": 0.88,
            "risk_off_core_pct": 0.60,
        },
    },
    {
        "id": "macro63_crash_guard_balanced",
        "label": "63d Crash Guard Balanced",
        "macro_config": {
            "yield_lookback_bars": 63,
            "yield_good_bps": -20.0,
            "yield_bad_bps": 25.0,
            "yield_weight": 0.35,
            "election_weight": 0.10,
            "breadth_weight": 0.70,
            "breadth_good_pct": 0.67,
            "breadth_bad_pct": 0.34,
            "benchmark_weight": 1.10,
            "benchmark_lookback_bars": 63,
            "benchmark_good_pct": 6.0,
            "benchmark_bad_pct": -6.0,
            "risk_on_threshold": 0.60,
            "risk_off_threshold": -0.10,
            "risk_on_core_pct": 0.96,
            "neutral_core_pct": 0.68,
            "risk_off_core_pct": 0.22,
        },
    },
    {
        "id": "macro63_crash_guard_hard",
        "label": "63d Crash Guard Hard",
        "macro_config": {
            "yield_lookback_bars": 63,
            "yield_good_bps": -20.0,
            "yield_bad_bps": 25.0,
            "yield_weight": 0.25,
            "election_weight": 0.10,
            "breadth_weight": 0.80,
            "breadth_good_pct": 0.67,
            "breadth_bad_pct": 0.34,
            "benchmark_weight": 1.25,
            "benchmark_lookback_bars": 42,
            "benchmark_good_pct": 5.0,
            "benchmark_bad_pct": -5.0,
            "risk_on_threshold": 0.55,
            "risk_off_threshold": -0.05,
            "risk_on_core_pct": 0.94,
            "neutral_core_pct": 0.60,
            "risk_off_core_pct": 0.10,
        },
    },
]
DEFAULT_SYNTHETIC_STRESS_STRATEGIES = ["ribbon"]
DEFAULT_SYNTHETIC_STRESS_ALLOCATOR_POLICIES = ["signal_top_n_strength_v1"]
DEFAULT_SYNTHETIC_STRESS_CONFIG_IDS = [
    "macro63_high_core",
    "macro63_very_high_core",
    "macro63_crash_guard_balanced",
    "macro63_crash_guard_hard",
]
DEFAULT_SYNTHETIC_STRESS_UPSIDE_WINDOWS = [
    "crash_recovery_2020_2021",
    "bull_recovery_2023_2025",
]

PORTFOLIO_PRESET_BASKETS = {
    "focus": RESEARCH_BASKETS["focus_7"]["tickers"],
    **{key: value["tickers"] for key, value in RESEARCH_BASKETS.items()},
}


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for item in values:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _select_keys(
    requested,
    allowed_order: list[str],
    *,
    label: str,
) -> list[str]:
    if requested in (None, "", []):
        return list(allowed_order)
    values = requested
    if isinstance(values, str):
        values = [part.strip() for part in values.split(",")]
    selected = _dedupe_preserve_order(values)
    unknown = [value for value in selected if value not in allowed_order]
    if unknown:
        raise ValueError(
            f"Unsupported {label}: {', '.join(unknown)}. "
            f"Supported: {', '.join(allowed_order)}"
        )
    return selected


def research_matrix_catalog(*, strategies=None, allocator_policies=None) -> dict:
    strategy_order = _select_keys(
        strategies,
        list(DEFAULT_RESEARCH_STRATEGIES),
        label="research strategies",
    )
    allocator_order = _select_keys(
        allocator_policies,
        list(DEFAULT_RESEARCH_ALLOCATOR_POLICIES),
        label="allocator policies",
    )
    baskets = [
        {
            "key": key,
            "label": value["label"],
            "tickers": list(value["tickers"]),
            "purpose": value["purpose"],
        }
        for key, value in RESEARCH_BASKETS.items()
    ]
    windows = [
        {
            "key": key,
            "label": value["label"],
            "start": value["start"],
            "end": value["end"],
            "purpose": value["purpose"],
        }
        for key, value in RESEARCH_WINDOWS.items()
    ]
    return {
        "version": RESEARCH_MATRIX_VERSION,
        "strategies": strategy_order,
        "allocator_policies": allocator_order,
        "baskets": baskets,
        "windows": windows,
        "run_count": len(strategy_order) * len(allocator_order) * len(baskets) * len(windows),
    }


def macro_overlay_matrix_catalog(
    *,
    strategies=None,
    allocator_policies=None,
    config_ids=None,
) -> dict:
    strategy_order = _select_keys(
        strategies,
        list(DEFAULT_MACRO_OVERLAY_STRATEGIES),
        label="macro overlay strategies",
    )
    allocator_order = _select_keys(
        allocator_policies,
        list(DEFAULT_MACRO_OVERLAY_ALLOCATOR_POLICIES),
        label="macro overlay allocator policies",
    )
    config_order = _select_keys(
        config_ids,
        [item["id"] for item in DEFAULT_MACRO_OVERLAY_CONFIGS],
        label="macro overlay configs",
    )
    baskets = [
        {
            "key": key,
            "label": value["label"],
            "tickers": list(value["tickers"]),
            "purpose": value["purpose"],
        }
        for key, value in RESEARCH_BASKETS.items()
    ]
    windows = [
        {
            "key": key,
            "label": value["label"],
            "start": value["start"],
            "end": value["end"],
            "purpose": value["purpose"],
        }
        for key, value in RESEARCH_WINDOWS.items()
    ]
    configs = [
        item
        for item in DEFAULT_MACRO_OVERLAY_CONFIGS
        if item["id"] in config_order
    ]
    return {
        "version": MACRO_OVERLAY_MATRIX_VERSION,
        "strategies": strategy_order,
        "allocator_policies": allocator_order,
        "configs": configs,
        "baskets": baskets,
        "windows": windows,
        "run_count": len(strategy_order) * len(allocator_order) * len(configs) * len(baskets) * len(windows),
        "baseline": V18_BEST_PAIR,
    }


def synthetic_stress_matrix_catalog(
    *,
    strategies=None,
    allocator_policies=None,
    config_ids=None,
    scenario_ids=None,
    upside_windows=None,
) -> dict:
    strategy_order = _select_keys(
        strategies,
        list(DEFAULT_SYNTHETIC_STRESS_STRATEGIES),
        label="synthetic stress strategies",
    )
    allocator_order = _select_keys(
        allocator_policies,
        list(DEFAULT_SYNTHETIC_STRESS_ALLOCATOR_POLICIES),
        label="synthetic stress allocator policies",
    )
    config_order = _select_keys(
        config_ids,
        list(DEFAULT_SYNTHETIC_STRESS_CONFIG_IDS),
        label="synthetic stress configs",
    )
    scenario_order = _select_keys(
        scenario_ids,
        [item.id for item in DEFAULT_SYNTHETIC_STRESS_SCENARIOS],
        label="synthetic stress scenarios",
    )
    upside_window_order = _select_keys(
        upside_windows,
        list(DEFAULT_SYNTHETIC_STRESS_UPSIDE_WINDOWS),
        label="synthetic stress upside windows",
    )
    baskets = [
        {
            "key": key,
            "label": value["label"],
            "tickers": list(value["tickers"]),
            "purpose": value["purpose"],
        }
        for key, value in RESEARCH_BASKETS.items()
    ]
    configs = [
        item
        for item in DEFAULT_MACRO_OVERLAY_CONFIGS
        if item["id"] in config_order
    ]
    scenarios = [
        item.to_dict()
        for item in DEFAULT_SYNTHETIC_STRESS_SCENARIOS
        if item.id in scenario_order
    ]
    windows = [
        {
            "key": key,
            "label": RESEARCH_WINDOWS[key]["label"],
            "start": RESEARCH_WINDOWS[key]["start"],
            "end": RESEARCH_WINDOWS[key]["end"],
            "purpose": RESEARCH_WINDOWS[key]["purpose"],
        }
        for key in upside_window_order
    ]
    return {
        "version": SYNTHETIC_STRESS_MATRIX_VERSION,
        "strategies": strategy_order,
        "allocator_policies": allocator_order,
        "configs": configs,
        "scenarios": scenarios,
        "baskets": baskets,
        "upside_windows": windows,
        "run_count": len(strategy_order) * len(allocator_order) * len(configs) * len(scenarios) * len(baskets),
        "upside_run_count": len(strategy_order) * len(allocator_order) * len(configs) * len(windows) * len(baskets),
        "baseline": V19_BEST_NEAR_MISS,
    }


def _matrix_run_name(strategy: str, allocator_policy: str, basket_key: str, window_key: str) -> str:
    basket_label = RESEARCH_BASKETS[basket_key]["label"]
    window_label = RESEARCH_WINDOWS[window_key]["label"]
    return f"{basket_label} · {window_label} · {strategy} · {allocator_policy}"


def build_research_campaign_payload(
    payload: dict | None = None,
    *,
    supported_strategies: list[str],
    supported_allocator_policies: list[str],
) -> dict:
    payload = dict(payload or {})
    strategies = _select_keys(
        payload.get("strategies"),
        [item for item in DEFAULT_RESEARCH_STRATEGIES if item in supported_strategies],
        label="research strategies",
    )
    allocator_policies = _select_keys(
        payload.get("allocator_policies"),
        [item for item in DEFAULT_RESEARCH_ALLOCATOR_POLICIES if item in supported_allocator_policies],
        label="allocator policies",
    )
    basket_keys = _select_keys(
        payload.get("baskets"),
        list(RESEARCH_BASKETS.keys()),
        label="research baskets",
    )
    window_keys = _select_keys(
        payload.get("windows"),
        list(RESEARCH_WINDOWS.keys()),
        label="research windows",
    )
    heat_limit = float(payload.get("heat_limit", DEFAULT_RESEARCH_HEAT_LIMIT))
    tags = _dedupe_preserve_order([*DEFAULT_RESEARCH_TAGS, *(payload.get("tags") or [])])
    schedule = dict(payload.get("schedule") or {})
    money_management = {
        **DEFAULT_RESEARCH_MONEY_MANAGEMENT,
        **dict(payload.get("money_management") or {}),
    }

    runs: list[dict] = []
    for basket_key in basket_keys:
        basket = RESEARCH_BASKETS[basket_key]
        for window_key in window_keys:
            window = RESEARCH_WINDOWS[window_key]
            for strategy in strategies:
                for allocator_policy in allocator_policies:
                    run_tags = _dedupe_preserve_order(
                        [
                            *tags,
                            basket_key,
                            window_key,
                            strategy,
                            allocator_policy,
                        ]
                    )
                    runs.append(
                        {
                            "name": _matrix_run_name(strategy, allocator_policy, basket_key, window_key),
                            "strategy": strategy,
                            "allocator_policy": allocator_policy,
                            "basket_source": "preset",
                            "preset": basket_key,
                            "start": window["start"],
                            "end": window["end"],
                            "heat_limit": heat_limit,
                            "money_management": money_management,
                            "tags": run_tags,
                            "research_context": {
                                "matrix_version": RESEARCH_MATRIX_VERSION,
                                "basket_key": basket_key,
                                "basket_label": basket["label"],
                                "window_key": window_key,
                                "window_label": window["label"],
                            },
                        }
                    )

    default_name = "Portfolio Rotation Research Matrix"
    default_goal = (
        "Compare retained strategies and allocator policies against portfolio "
        "buy-and-hold across the canonical v1.18 baskets and regime windows."
    )
    return {
        "name": payload.get("name") or default_name,
        "goal": payload.get("goal") or default_goal,
        "notes": payload.get("notes") or "",
        "tags": tags,
        "schedule": schedule,
        "runs": runs,
        "matrix": {
            "version": RESEARCH_MATRIX_VERSION,
            "strategies": strategies,
            "allocator_policies": allocator_policies,
            "baskets": basket_keys,
            "windows": window_keys,
            "run_count": len(runs),
        },
    }
