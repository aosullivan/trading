import math

import pandas as pd

from lib.strategy_preferences import preferred_strategy_for_ticker
from lib.support_resistance import compute_support_resistance


TRADE_STRATEGY_WEIGHTS = {
    "ribbon": 24,
    "corpus_trend": 18,
    "corpus_trend_layered": 14,
    "cci_hysteresis": 14,
    "weekly_core_overlay_v1": 12,
    "bb_breakout": 8,
    "ema_crossover": 7,
    "ema_9_26": 8,
    "cci_trend": 5,
    "semis_persist_v1": 10,
    "polymarket": 12,
}

TRADE_SCORE_FORMULA = (
    "50% trend bias + 20% nearest support/resistance proximity + 15% nearest moving average"
    " + 15% upside/downside room, plus a 10-point confluence bonus when the anchor level"
    " and nearest moving average sit within 1 ATR."
)

DAILY_MA_SPECS = (
    ("SMA 50", 50),
    ("SMA 100", 100),
    ("SMA 200", 200),
)

WEEKLY_MA_SPECS = (
    ("50W MA", 50),
    ("100W MA", 100),
    ("200W MA", 200),
)


def _last_float(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    value = series.iloc[-1]
    if pd.isna(value):
        return None
    return float(value)


def _atr(df: pd.DataFrame, period: int = 14) -> float | None:
    if df is None or df.empty or len(df) < 2:
        return None
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    value = tr.rolling(period).mean().iloc[-1]
    if pd.isna(value) or float(value) <= 0:
        return None
    return float(value)


def _pct_distance(current_price: float, target_price: float | None) -> float | None:
    if current_price <= 0 or target_price is None:
        return None
    return abs(float(target_price) - current_price) / current_price * 100.0


def _atr_distance(current_price: float, target_price: float | None, atr_value: float | None) -> float | None:
    if atr_value is None or atr_value <= 0 or target_price is None:
        return None
    return abs(float(target_price) - current_price) / atr_value


def _distance_label(current_price: float, target_price: float | None) -> str | None:
    if target_price is None:
        return None
    if float(target_price) < current_price:
        return "below"
    if float(target_price) > current_price:
        return "above"
    return "at"


def _nearest_level(levels: list[dict], current_price: float, side: str) -> dict | None:
    if side == "support":
        candidates = [level for level in levels if float(level.get("price", 0)) < current_price]
        if not candidates:
            return None
        return max(candidates, key=lambda level: float(level.get("price", 0)))
    candidates = [level for level in levels if float(level.get("price", 0)) > current_price]
    if not candidates:
        return None
    return min(candidates, key=lambda level: float(level.get("price", 0)))


def _moving_average_levels(df_d: pd.DataFrame, df_w: pd.DataFrame, current_price: float, atr_value: float | None) -> list[dict]:
    levels = []
    close_d = df_d["Close"] if df_d is not None and not df_d.empty else pd.Series(dtype=float)
    close_w = df_w["Close"] if df_w is not None and not df_w.empty else pd.Series(dtype=float)

    for label, period in DAILY_MA_SPECS:
        value = _last_float(close_d.rolling(window=period).mean())
        if value is None:
            continue
        levels.append(
            {
                "label": label,
                "price": round(value, 2),
                "distance_pct": round(_pct_distance(current_price, value), 2),
                "distance_atr": round(_atr_distance(current_price, value, atr_value), 2)
                if _atr_distance(current_price, value, atr_value) is not None
                else None,
                "position": _distance_label(current_price, value),
            }
        )

    for label, period in WEEKLY_MA_SPECS:
        value = _last_float(close_w.rolling(window=period).mean())
        if value is None:
            continue
        levels.append(
            {
                "label": label,
                "price": round(value, 2),
                "distance_pct": round(_pct_distance(current_price, value), 2),
                "distance_atr": round(_atr_distance(current_price, value, atr_value), 2)
                if _atr_distance(current_price, value, atr_value) is not None
                else None,
                "position": _distance_label(current_price, value),
            }
        )
    return levels


def _nearest_ma(levels: list[dict]) -> dict | None:
    if not levels:
        return None
    return min(
        levels,
        key=lambda level: (
            float(level.get("distance_pct") if level.get("distance_pct") is not None else 999999),
            level.get("label", ""),
        ),
    )


def _closeness_score(distance_atr: float | None, max_distance: float = 4.0) -> float:
    if distance_atr is None:
        return 0.0
    clipped = min(max(distance_atr, 0.0), max_distance)
    return round((1.0 - (clipped / max_distance)) * 100.0, 2)


def _room_score(upside_atr: float | None, downside_atr: float | None, side: str) -> float:
    if upside_atr is None or downside_atr is None:
        return 50.0
    delta = upside_atr - downside_atr if side == "bullish" else downside_atr - upside_atr
    return round((math.tanh(delta / 2.0) + 1.0) * 50.0, 2)


def _frame_side(trend_bias: int) -> str:
    if trend_bias >= 15:
        return "bullish"
    if trend_bias <= -15:
        return "bearish"
    return "mixed"


def _trend_bias(frame_flips: dict) -> int:
    if not isinstance(frame_flips, dict) or not frame_flips:
        return 0
    available_keys = [key for key in TRADE_STRATEGY_WEIGHTS if key in frame_flips]
    if not available_keys:
        return 0
    possible_total = sum(TRADE_STRATEGY_WEIGHTS[key] for key in available_keys)
    if possible_total <= 0:
        return 0
    weighted_sum = 0.0
    for key in available_keys:
        direction = (frame_flips.get(key) or {}).get("current_dir") or (frame_flips.get(key) or {}).get("dir")
        if direction == "bullish":
            weighted_sum += TRADE_STRATEGY_WEIGHTS[key]
        elif direction == "bearish":
            weighted_sum -= TRADE_STRATEGY_WEIGHTS[key]
    return int(round((weighted_sum / possible_total) * 100.0))


def _strategy_direction(frame_flips: dict, strategy_key: str | None) -> str | None:
    if not strategy_key or not isinstance(frame_flips, dict):
        return None
    payload = frame_flips.get(strategy_key) or {}
    return payload.get("current_dir") or payload.get("dir")


def _preferred_strategy_bias(frame_flips: dict, strategy_key: str | None) -> int:
    direction = _strategy_direction(frame_flips, strategy_key)
    if direction == "bullish":
        return 100
    if direction == "bearish":
        return -100
    return 0


def _level_payload(current_price: float, atr_value: float | None, level: dict | None) -> dict | None:
    if level is None:
        return None
    price = float(level["price"])
    distance_pct = _pct_distance(current_price, price)
    distance_atr = _atr_distance(current_price, price, atr_value)
    return {
        "price": round(price, 2),
        "distance_pct": round(distance_pct, 2) if distance_pct is not None else None,
        "distance_atr": round(distance_atr, 2) if distance_atr is not None else None,
        "position": _distance_label(current_price, price),
        "touches": int(level.get("touches", 0)),
        "respect": level.get("respect"),
    }


def _confluence_label(anchor_level: dict | None, ma_level: dict | None, atr_value: float | None, side: str) -> str | None:
    if anchor_level is None or ma_level is None or atr_value is None or atr_value <= 0:
        return None
    if abs(float(anchor_level["price"]) - float(ma_level["price"])) > atr_value:
        return None
    anchor = "Support" if side == "bullish" else "Resistance"
    return f"{anchor} + {ma_level['label']}"


def _format_signed(value: float | int | None, digits: int = 0) -> str:
    if value is None:
        return "--"
    number = float(value)
    if digits <= 0:
        text = str(int(round(number)))
    else:
        text = f"{number:.{digits}f}"
    return f"+{text}" if number > 0 else text


def _strength_label(score: int | None, side: str) -> str:
    magnitude = abs(int(score or 0))
    if side == "mixed" or magnitude < 20:
        return "Low conviction"
    if magnitude < 45:
        return "Moderate conviction"
    if magnitude < 70:
        return f"Strong {side}"
    return f"High-conviction {side}"


def _component_payload(label: str, component_score: float, weight: float, detail: str) -> dict:
    return {
        "label": label,
        "component_score": round(float(component_score), 2),
        "weight_pct": int(round(weight * 100)),
        "weighted_contribution": round(float(component_score) * weight, 2),
        "detail": detail,
    }


def _level_detail(level: dict | None, side: str) -> str:
    anchor = "support" if side == "bullish" else "resistance"
    if level is None:
        return f"No nearby {anchor} was found, so this factor adds no edge."
    distance_pct = "--" if level.get("distance_pct") is None else f"{level['distance_pct']}%"
    distance_atr = "--" if level.get("distance_atr") is None else f"{level['distance_atr']} ATR"
    touches = level.get("touches")
    touch_text = f" with {touches} touches" if touches else ""
    respect = level.get("respect")
    respect_text = ""
    if respect is not None:
        respect_text = f" and respect {round(float(respect), 2)}"
    return (
        f"Price is {distance_pct} ({distance_atr}) from the nearest {anchor} at {level['price']}"
        f"{touch_text}{respect_text}."
    )


def _ma_detail(nearest_ma: dict | None, side: str) -> str:
    if nearest_ma is None:
        return "No moving average was available, so this factor stays neutral."
    position = nearest_ma.get("position") or "at"
    distance_pct = "--" if nearest_ma.get("distance_pct") is None else f"{nearest_ma['distance_pct']}%"
    distance_atr = "--" if nearest_ma.get("distance_atr") is None else f"{nearest_ma['distance_atr']} ATR"
    aligned = (side == "bullish" and position in {"below", "at"}) or (side == "bearish" and position in {"above", "at"})
    alignment_text = "aligned with the setup" if aligned else "working against the setup"
    return (
        f"Nearest MA is {nearest_ma['label']} at {nearest_ma['price']}, {distance_pct} ({distance_atr})"
        f" {position} price and {alignment_text}."
    )


def _room_detail(structure: dict, side: str) -> str:
    upside_atr = structure.get("upside_room_atr")
    downside_atr = structure.get("downside_room_atr")
    if upside_atr is None or downside_atr is None:
        return "Room is neutral because one side of the range is missing."
    if side == "bullish":
        balance = "more upside room than downside air pocket" if upside_atr >= downside_atr else "less upside room than downside support"
    else:
        balance = "more downside room than upside squeeze risk" if downside_atr >= upside_atr else "less downside room than upside squeeze risk"
    return (
        f"Upside room is {structure['upside_room_pct']}% ({upside_atr} ATR) while downside room is"
        f" {structure['downside_room_pct']}% ({downside_atr} ATR), leaving {balance}."
    )


def _mixed_highlights(trend_bias: int) -> list[str]:
    bias_text = _format_signed(trend_bias)
    return [
        f"Trend bias is {bias_text}, which is too close to neutral to form a directional setup.",
        "Support, resistance, and moving averages are still tracked, but they are not allowed to overpower a mixed trend regime.",
    ]


def _directional_highlights(side: str, structure: dict, level_component: float, ma_component: float, room_component: float) -> list[str]:
    highlights = []
    level = structure.get("nearest_support") if side == "bullish" else structure.get("nearest_resistance")
    if level is not None:
        anchor = "support" if side == "bullish" else "resistance"
        distance_atr = level.get("distance_atr")
        if distance_atr is not None:
            if level_component >= 65:
                highlights.append(f"Price is sitting close to {anchor} at {level['price']}, which boosts the setup.")
            elif level_component <= 30:
                highlights.append(f"Price is stretched away from nearby {anchor}, so this factor contributes less.")
    nearest_ma = structure.get("nearest_ma")
    if nearest_ma is not None:
        aligned = (side == "bullish" and nearest_ma.get("position") in {"below", "at"}) or (
            side == "bearish" and nearest_ma.get("position") in {"above", "at"}
        )
        if ma_component >= 60 and aligned:
            highlights.append(f"{nearest_ma['label']} is close and aligned with the {side} setup.")
        elif ma_component <= 30 or not aligned:
            highlights.append(f"{nearest_ma['label']} is not offering strong confirmation for this setup.")
    upside_atr = structure.get("upside_room_atr")
    downside_atr = structure.get("downside_room_atr")
    if upside_atr is not None and downside_atr is not None:
        if side == "bullish" and room_component >= 55:
            highlights.append("There is more room into resistance than room down to support.")
        elif side == "bearish" and room_component >= 55:
            highlights.append("There is more room down into support than room back up into resistance.")
        elif room_component <= 45:
            highlights.append("Risk/reward room is not especially favorable here.")
    confluence = structure.get("confluence", {}).get(side)
    if confluence:
        highlights.append(f"Confluence bonus applied because {confluence.lower()} are clustered together.")
    return highlights


def _build_breakdown(
    side: str,
    trend_bias: int,
    score: int,
    structure: dict,
    trend_component: float,
    level_component: float,
    ma_component: float,
    room_component: float,
    confluence_bonus: float,
    trend_source_label: str,
) -> dict:
    if side == "mixed":
        return {
            "formula": TRADE_SCORE_FORMULA,
            "strength_label": _strength_label(score, side),
            "summary": f"Trade score stays muted because {trend_source_label.lower()} is mixed.",
            "components": [
                _component_payload(
                    "Trend bias",
                    abs(trend_bias),
                    0.50,
                    f"{trend_source_label} is {_format_signed(trend_bias)}.",
                ),
                _component_payload("Support / resistance", 0.0, 0.20, "Directional level scoring is disabled while bias is mixed."),
                _component_payload("Nearest moving average", 0.0, 0.15, "Moving-average scoring is disabled while bias is mixed."),
                _component_payload("Room to target", 50.0, 0.15, "Room stays neutral until bias turns clearly bullish or bearish."),
            ],
            "bonus": None,
            "highlights": _mixed_highlights(trend_bias),
            "raw_score": round(abs(score), 2),
        }

    level = structure.get("nearest_support") if side == "bullish" else structure.get("nearest_resistance")
    nearest_ma = structure.get("nearest_ma")
    components = [
        _component_payload(
            "Trend bias",
            trend_component,
            0.50,
            f"{trend_source_label} is {_format_signed(trend_bias)}, which sets the {side} direction.",
        ),
        _component_payload(
            "Support / resistance",
            level_component,
            0.20,
            _level_detail(level, side),
        ),
        _component_payload(
            "Nearest moving average",
            ma_component,
            0.15,
            _ma_detail(nearest_ma, side),
        ),
        _component_payload(
            "Room to target",
            room_component,
            0.15,
            _room_detail(structure, side),
        ),
    ]
    raw_score = sum(component["weighted_contribution"] for component in components) + confluence_bonus
    confluence_label = structure.get("confluence", {}).get(side)
    highlights = _directional_highlights(side, structure, level_component, ma_component, room_component)
    summary_bits = [f"{_strength_label(score, side)} setup driven first by {_format_signed(trend_bias)} from {trend_source_label.lower()}."]
    if highlights:
        summary_bits.append(highlights[0])
    if len(highlights) > 1:
        summary_bits.append(highlights[1])
    return {
        "formula": TRADE_SCORE_FORMULA,
        "strength_label": _strength_label(score, side),
        "summary": " ".join(summary_bits),
        "components": components,
        "bonus": {
            "label": "Confluence bonus",
            "points": round(confluence_bonus, 2),
            "detail": f"{confluence_label} are within 1 ATR of each other."
            if confluence_label
            else "No confluence bonus was applied.",
        }
        if confluence_bonus or confluence_label
        else None,
        "highlights": highlights,
        "raw_score": round(min(raw_score, 100.0), 2),
    }


def _frame_setup(
    trend_bias: int,
    structure: dict,
    *,
    trend_source_label: str = "Weighted strategy bias",
) -> dict:
    side = _frame_side(trend_bias)
    if side == "mixed":
        score = int(round(trend_bias * 0.4))
        payload = {
            "side": "mixed",
            "trend_bias": trend_bias,
            "score": score,
            "trend_component": abs(trend_bias),
            "level_component": 0.0,
            "ma_component": 0.0,
            "room_component": 50.0,
            "trend_source_label": trend_source_label,
        }
        payload["breakdown"] = _build_breakdown(
            side,
            trend_bias,
            score,
            structure,
            float(abs(trend_bias)),
            0.0,
            0.0,
            50.0,
            0.0,
            trend_source_label,
        )
        return payload

    level = structure.get("nearest_support") if side == "bullish" else structure.get("nearest_resistance")
    level_component = _closeness_score(level.get("distance_atr") if level else None)
    nearest_ma = structure.get("nearest_ma")
    ma_component = _closeness_score(nearest_ma.get("distance_atr") if nearest_ma else None)
    if nearest_ma is not None:
        if side == "bullish" and nearest_ma.get("position") in {"below", "at"}:
            ma_component = min(100.0, ma_component + 12.0)
        elif side == "bearish" and nearest_ma.get("position") in {"above", "at"}:
            ma_component = min(100.0, ma_component + 12.0)
        else:
            ma_component = max(0.0, ma_component - 10.0)
    room_component = _room_score(
        structure.get("upside_room_atr"),
        structure.get("downside_room_atr"),
        side,
    )
    confluence_bonus = 10.0 if structure.get("confluence", {}).get(side) else 0.0
    raw = (
        0.50 * abs(trend_bias)
        + 0.20 * level_component
        + 0.15 * ma_component
        + 0.15 * room_component
        + confluence_bonus
    )
    signed_score = int(round(min(raw, 100.0))) * (1 if side == "bullish" else -1)
    payload = {
        "side": side,
        "trend_bias": trend_bias,
        "score": signed_score,
        "trend_component": round(abs(trend_bias), 2),
        "level_component": round(level_component, 2),
        "ma_component": round(ma_component, 2),
        "room_component": round(room_component, 2),
        "trend_source_label": trend_source_label,
    }
    payload["breakdown"] = _build_breakdown(
        side,
        trend_bias,
        signed_score,
        structure,
        payload["trend_component"],
        payload["level_component"],
        payload["ma_component"],
        payload["room_component"],
        confluence_bonus,
        trend_source_label,
    )
    return payload


def compute_trade_setup(
    df_d: pd.DataFrame,
    df_w: pd.DataFrame,
    daily_flips: dict,
    weekly_flips: dict,
    ticker: str | None = None,
) -> dict:
    if df_d is None or df_d.empty:
        return {"daily": _frame_setup(0, {}), "weekly": _frame_setup(0, {}), "shared": {}}

    current_price = float(df_d["Close"].iloc[-1])
    atr_value = _atr(df_d)
    sr_levels = compute_support_resistance(df_d, max_levels=20)
    nearest_support = _level_payload(current_price, atr_value, _nearest_level(sr_levels, current_price, "support"))
    nearest_resistance = _level_payload(current_price, atr_value, _nearest_level(sr_levels, current_price, "resistance"))

    ma_levels = _moving_average_levels(df_d, df_w, current_price, atr_value)
    nearest_ma = _nearest_ma(ma_levels)

    upside_room_pct = nearest_resistance.get("distance_pct") if nearest_resistance else None
    upside_room_atr = nearest_resistance.get("distance_atr") if nearest_resistance else None
    downside_room_pct = nearest_support.get("distance_pct") if nearest_support else None
    downside_room_atr = nearest_support.get("distance_atr") if nearest_support else None

    confluence = {
        "bullish": _confluence_label(nearest_support, nearest_ma, atr_value, "bullish"),
        "bearish": _confluence_label(nearest_resistance, nearest_ma, atr_value, "bearish"),
    }
    structure = {
        "price": round(current_price, 2),
        "atr": round(atr_value, 2) if atr_value is not None else None,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "nearest_ma": nearest_ma,
        "upside_room_pct": round(upside_room_pct, 2) if upside_room_pct is not None else None,
        "upside_room_atr": round(upside_room_atr, 2) if upside_room_atr is not None else None,
        "downside_room_pct": round(downside_room_pct, 2) if downside_room_pct is not None else None,
        "downside_room_atr": round(downside_room_atr, 2) if downside_room_atr is not None else None,
        "confluence": confluence,
    }

    preferred_meta = preferred_strategy_for_ticker(ticker) if ticker else None
    if preferred_meta:
        structure["preferred_strategy"] = preferred_meta
        daily_bias = _preferred_strategy_bias(daily_flips, preferred_meta["strategy_key"])
        weekly_bias = _preferred_strategy_bias(weekly_flips, preferred_meta["strategy_key"])
        trend_source_label = f"Preferred strategy bias ({preferred_meta['strategy_label']})"
    else:
        daily_bias = _trend_bias(daily_flips)
        weekly_bias = _trend_bias(weekly_flips)
        trend_source_label = "Weighted strategy bias"
    return {
        "daily": _frame_setup(daily_bias, structure, trend_source_label=trend_source_label),
        "weekly": _frame_setup(weekly_bias, structure, trend_source_label=trend_source_label),
        "shared": structure,
    }
