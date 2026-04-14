"""Canonical portfolio research matrix definitions for v1.18."""

from __future__ import annotations

from collections.abc import Iterable

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
