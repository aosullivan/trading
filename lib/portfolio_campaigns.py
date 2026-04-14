"""Local-first portfolio campaign persistence and queue state."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from lib.paths import get_user_data_path

VALID_RUN_STATUSES = {
    "planned",
    "queued",
    "running",
    "completed",
    "failed",
    "skipped",
}

VALID_SCHEDULE_CADENCES = {
    "manual",
    "hourly",
    "weekly",
}

_WEEKDAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_WEEKDAY_INDEX = {name: idx for idx, name in enumerate(_WEEKDAY_ORDER)}
_DEFAULT_COMPARISON_SORT = "best_gap_vs_buy_hold"
_COMPARISON_SORT_FIELDS = {
    "best_return": ("strategy_return_pct", True),
    "best_gap_vs_buy_hold": ("gap_vs_buy_hold_pct", True),
    "best_return_over_drawdown": ("return_over_drawdown", True),
    "lowest_drawdown": ("max_drawdown_pct", False),
}

_LOCK = threading.Lock()
_ACTIVE_CAMPAIGNS: set[str] = set()


def _campaigns_dir() -> Path:
    path = Path(get_user_data_path("portfolio_campaigns"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path() -> Path:
    return _campaigns_dir() / "index.json"


def _campaign_path(campaign_id: str) -> Path:
    return _campaigns_dir() / f"{campaign_id}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _schedule_now() -> datetime:
    return datetime.now().astimezone().replace(second=0, microsecond=0)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    with path.open() as handle:
        return json.load(handle)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)


def _normalize_tags(tags) -> list[str]:
    if not tags:
        return []
    seen: set[str] = set()
    values: list[str] = []
    for item in tags:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _normalize_manual_tickers(tickers) -> list[str]:
    if not tickers:
        return []
    seen: set[str] = set()
    values: list[str] = []
    for item in tickers:
        value = str(item).upper().strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _normalize_money_management(mm) -> dict:
    if not mm:
        return {}
    allowed = {
        "sizing_method",
        "risk_fraction",
        "stop_type",
        "stop_atr_period",
        "stop_atr_multiple",
        "stop_pct",
        "vol_to_equity_limit",
        "compounding",
        "initial_capital",
    }
    payload = {}
    for key, value in dict(mm).items():
        if key in allowed and value not in (None, ""):
            payload[key] = value
    return payload


def _normalize_research_context(raw) -> dict:
    if not raw:
        return {}
    context = dict(raw)
    payload = {}
    for key in (
        "matrix_version",
        "basket_key",
        "basket_label",
        "window_key",
        "window_label",
    ):
        value = context.get(key)
        if value not in (None, ""):
            payload[key] = str(value)
    return payload


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_schedule_now().tzinfo)
    return dt


def _normalize_weekdays(values) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        values = values.split(",")
    seen: set[str] = set()
    weekdays: list[str] = []
    for item in values:
        value = str(item).strip().lower()[:3]
        if value in _WEEKDAY_INDEX and value not in seen:
            seen.add(value)
            weekdays.append(value)
    weekdays.sort(key=lambda item: _WEEKDAY_INDEX[item])
    return weekdays


def _next_weekly_occurrence(now: datetime, weekdays: list[str], hour: int, minute: int) -> datetime:
    allowed = weekdays or ["mon"]
    for delta_days in range(0, 8):
        candidate = (now + timedelta(days=delta_days)).replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if _WEEKDAY_ORDER[candidate.weekday()] not in allowed:
            continue
        if candidate > now:
            return candidate
    fallback = (now + timedelta(days=7)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return fallback


def _compute_next_run_at(schedule: dict, now: datetime, *, after_queue: bool = False) -> str | None:
    if not schedule.get("enabled"):
        return None
    cadence = schedule.get("cadence", "manual")
    if cadence == "manual":
        return None
    if cadence == "hourly":
        interval_hours = max(1, int(schedule.get("interval_hours", 24)))
        base = now if after_queue or not schedule.get("next_run_at") else _parse_iso_datetime(schedule["next_run_at"]) or now
        return (base + timedelta(hours=interval_hours)).replace(second=0, microsecond=0).isoformat()
    hour = int(schedule.get("hour", 9))
    minute = int(schedule.get("minute", 0))
    weekdays = _normalize_weekdays(schedule.get("weekdays"))
    base = now if after_queue or not schedule.get("next_run_at") else _parse_iso_datetime(schedule["next_run_at"]) or now
    return _next_weekly_occurrence(base, weekdays, hour, minute).isoformat()


def _normalize_schedule(schedule, now: datetime | None = None) -> dict:
    now = now or _schedule_now()
    raw = dict(schedule or {})
    cadence = str(raw.get("cadence", "manual")).strip().lower() or "manual"
    if cadence not in VALID_SCHEDULE_CADENCES:
        cadence = "manual"
    enabled = bool(raw.get("enabled")) and cadence != "manual"
    interval_hours = max(1, int(raw.get("interval_hours", 24) or 24))
    hour = min(23, max(0, int(raw.get("hour", 9) or 9)))
    minute = min(59, max(0, int(raw.get("minute", 0) or 0)))
    weekdays = _normalize_weekdays(raw.get("weekdays"))
    next_run_at = raw.get("next_run_at")
    if enabled and cadence != "manual":
        next_run_at = next_run_at or _compute_next_run_at(
            {
                "enabled": enabled,
                "cadence": cadence,
                "interval_hours": interval_hours,
                "weekdays": weekdays,
                "hour": hour,
                "minute": minute,
            },
            now,
        )
    else:
        next_run_at = None
    return {
        "enabled": enabled,
        "cadence": cadence,
        "interval_hours": interval_hours,
        "weekdays": weekdays,
        "hour": hour,
        "minute": minute,
        "last_queued_at": raw.get("last_queued_at"),
        "next_run_at": next_run_at,
    }


def _normalize_run_spec(raw_run: dict, now: str) -> dict:
    status = str(raw_run.get("status", "planned")).strip() or "planned"
    if status not in VALID_RUN_STATUSES:
        status = "planned"

    return {
        "run_id": raw_run.get("run_id") or uuid4().hex[:12],
        "name": raw_run.get("name") or "Untitled run",
        "strategy": raw_run.get("strategy") or "ribbon",
        "allocator_policy": raw_run.get("allocator_policy") or "signal_flip_v1",
        "basket_source": raw_run.get("basket_source") or "watchlist",
        "tickers": _normalize_manual_tickers(raw_run.get("tickers")),
        "preset": raw_run.get("preset") or None,
        "start": raw_run.get("start") or "2015-01-01",
        "end": raw_run.get("end") or "",
        "money_management": _normalize_money_management(raw_run.get("money_management")),
        "heat_limit": float(raw_run.get("heat_limit", 0.20)),
        "tags": _normalize_tags(raw_run.get("tags")),
        "notes": raw_run.get("notes") or "",
        "research_context": _normalize_research_context(raw_run.get("research_context")),
        "status": status,
        "last_result": raw_run.get("last_result"),
        "last_run_at": raw_run.get("last_run_at"),
        "last_error": raw_run.get("last_error"),
        "created_at": raw_run.get("created_at") or now,
        "updated_at": now,
    }


def _safe_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _comparison_sort_details(sort_by: str | None) -> tuple[str, str, bool]:
    normalized = str(sort_by or _DEFAULT_COMPARISON_SORT).strip().lower() or _DEFAULT_COMPARISON_SORT
    field, descending = _COMPARISON_SORT_FIELDS.get(normalized, _COMPARISON_SORT_FIELDS[_DEFAULT_COMPARISON_SORT])
    return normalized if normalized in _COMPARISON_SORT_FIELDS else _DEFAULT_COMPARISON_SORT, field, descending


def _comparison_row(campaign: dict, run: dict) -> dict:
    result = dict(run.get("last_result") or {})
    initial_capital = _safe_float(run.get("money_management", {}).get("initial_capital")) or 10000.0
    strategy_ending_equity = _safe_float(result.get("strategy_ending_equity"))
    buy_hold_ending_equity = _safe_float(result.get("buy_hold_ending_equity"))
    strategy_return_pct = (
        round(((strategy_ending_equity / initial_capital) - 1) * 100, 2)
        if strategy_ending_equity is not None and initial_capital
        else None
    )
    buy_hold_return_pct = (
        round(((buy_hold_ending_equity / initial_capital) - 1) * 100, 2)
        if buy_hold_ending_equity is not None and initial_capital
        else None
    )
    gap_vs_buy_hold_pct = _safe_float(result.get("return_gap_pct"))
    max_drawdown_pct = _safe_float(result.get("max_drawdown_pct"))
    return_over_drawdown = (
        round(strategy_return_pct / max_drawdown_pct, 4)
        if strategy_return_pct is not None and max_drawdown_pct not in (None, 0)
        else None
    )

    tickers = run.get("tickers") or []
    if run.get("basket_source") == "preset" and run.get("preset"):
        basket_definition = run["preset"]
    elif tickers:
        basket_definition = ", ".join(tickers)
    else:
        basket_definition = "watchlist"

    return {
        "campaign_id": campaign["campaign_id"],
        "campaign_name": campaign.get("name") or "Untitled campaign",
        "campaign_tags": campaign.get("tags", []),
        "run_id": run["run_id"],
        "run_name": run.get("name") or run["run_id"],
        "strategy": run.get("strategy") or "ribbon",
        "allocator_policy": run.get("allocator_policy") or "signal_flip_v1",
        "basket_source": run.get("basket_source") or "watchlist",
        "basket_definition": basket_definition,
        "preset": run.get("preset"),
        "tickers": tickers,
        "status": run.get("status", "planned"),
        "start": run.get("start"),
        "end": run.get("end"),
        "completed_at": result.get("completed_at"),
        "last_run_at": run.get("last_run_at"),
        "winner": result.get("winner"),
        "initial_capital": initial_capital,
        "strategy_ending_equity": strategy_ending_equity,
        "buy_hold_ending_equity": buy_hold_ending_equity,
        "strategy_return_pct": strategy_return_pct,
        "buy_hold_return_pct": buy_hold_return_pct,
        "gap_vs_buy_hold_pct": gap_vs_buy_hold_pct,
        "equity_gap": _safe_float(result.get("equity_gap")),
        "max_drawdown_pct": max_drawdown_pct,
        "buy_hold_max_drawdown_pct": _safe_float(result.get("buy_hold_max_drawdown_pct")),
        "drawdown_gap_pct": _safe_float(result.get("drawdown_gap_pct")),
        "upside_capture_pct": _safe_float(result.get("upside_capture_pct")),
        "return_over_drawdown": return_over_drawdown,
        "avg_invested_pct": _safe_float(result.get("avg_invested_pct")),
        "avg_active_positions": _safe_float(result.get("avg_active_positions")),
        "avg_redeployment_lag_bars": _safe_float(result.get("avg_redeployment_lag_bars")),
        "turnover_pct": _safe_float(result.get("turnover_pct")),
        "max_single_name_weight_pct": _safe_float(result.get("max_single_name_weight_pct")),
        "traded_tickers": result.get("traded_tickers"),
        "order_count": result.get("order_count"),
        "research_context": dict(run.get("research_context") or {}),
        "research_basket_key": (run.get("research_context") or {}).get("basket_key"),
        "research_window_key": (run.get("research_context") or {}).get("window_key"),
    }


def _comparison_matches_filters(row: dict, *, campaign_id=None, strategy=None, basket_source=None, status=None) -> bool:
    if campaign_id and row["campaign_id"] != campaign_id:
        return False
    if strategy and row["strategy"] != strategy:
        return False
    if basket_source and row["basket_source"] != basket_source:
        return False
    if status and row["status"] != status:
        return False
    return True


def _comparison_sort_key(field: str, descending: bool):
    def key(row: dict):
        value = row.get(field)
        missing = value is None
        if isinstance(value, (int, float)):
            normalized = -value if descending else value
        else:
            normalized = value
        return (missing, normalized, row.get("campaign_name", ""), row.get("run_name", ""))

    return key


def _campaign_progress(campaign: dict) -> dict:
    runs = campaign.get("runs", [])
    counts = {status: 0 for status in VALID_RUN_STATUSES}
    for run in runs:
        status = run.get("status", "planned")
        counts[status] = counts.get(status, 0) + 1
    total = len(runs)
    completed = counts.get("completed", 0)
    percent = round((completed / total) * 100, 1) if total else 0.0
    counts["total"] = total
    counts["percent_completed"] = percent
    counts["remaining"] = max(total - completed, 0)
    return counts


def _campaign_status(campaign: dict) -> str:
    progress = _campaign_progress(campaign)
    if progress["total"] == 0:
        return "planned"
    if progress.get("running", 0) > 0:
        return "running"
    if progress.get("queued", 0) > 0:
        return "queued"
    if progress.get("failed", 0) > 0 and progress["remaining"] > 0:
        return "running"
    if progress["completed"] + progress.get("skipped", 0) == progress["total"]:
        return "completed"
    return "planned"


def _campaign_index_entry(campaign: dict) -> dict:
    progress = _campaign_progress(campaign)
    return {
        "campaign_id": campaign["campaign_id"],
        "name": campaign["name"],
        "goal": campaign.get("goal", ""),
        "tags": campaign.get("tags", []),
        "status": campaign["status"],
        "created_at": campaign["created_at"],
        "updated_at": campaign["updated_at"],
        "schedule": campaign.get("schedule"),
        "progress": progress,
    }


def _save_index(campaigns: list[dict]) -> None:
    entries = sorted(
        (_campaign_index_entry(campaign) for campaign in campaigns),
        key=lambda entry: entry["updated_at"],
        reverse=True,
    )
    _write_json(_index_path(), entries)


def _load_all_campaigns() -> list[dict]:
    campaigns = []
    for path in sorted(_campaigns_dir().glob("*.json")):
        if path.name == "index.json":
            continue
        campaigns.append(_read_json(path, {}))
    return [campaign for campaign in campaigns if campaign]


def list_campaigns() -> list[dict]:
    with _LOCK:
        campaigns = _load_all_campaigns()
        _save_index(campaigns)
        return _read_json(_index_path(), [])


def get_campaign(campaign_id: str) -> dict | None:
    with _LOCK:
        campaign = _read_json(_campaign_path(campaign_id), None)
        if not campaign:
            return None
        campaign["schedule"] = _normalize_schedule(campaign.get("schedule"))
        campaign["progress"] = _campaign_progress(campaign)
        return campaign


def create_campaign(payload: dict) -> dict:
    now = _now_iso()
    schedule_now = _schedule_now()
    runs = [_normalize_run_spec(run, now) for run in payload.get("runs", [])]
    campaign = {
        "campaign_id": payload.get("campaign_id") or uuid4().hex[:12],
        "name": payload.get("name") or "Untitled campaign",
        "goal": payload.get("goal") or "",
        "notes": payload.get("notes") or "",
        "tags": _normalize_tags(payload.get("tags")),
        "schedule": _normalize_schedule(payload.get("schedule"), schedule_now),
        "runs": runs,
        "created_at": now,
        "updated_at": now,
    }
    campaign["status"] = _campaign_status(campaign)
    campaign["progress"] = _campaign_progress(campaign)
    with _LOCK:
        _write_json(_campaign_path(campaign["campaign_id"]), campaign)
        _save_index(_load_all_campaigns())
    return campaign


def save_campaign(campaign: dict) -> dict:
    campaign["updated_at"] = _now_iso()
    campaign["schedule"] = _normalize_schedule(campaign.get("schedule"))
    campaign["status"] = _campaign_status(campaign)
    campaign["progress"] = _campaign_progress(campaign)
    with _LOCK:
        _write_json(_campaign_path(campaign["campaign_id"]), campaign)
        _save_index(_load_all_campaigns())
    return campaign


def queue_campaign(campaign_id: str, *, rerun_all: bool = False) -> dict:
    with _LOCK:
        campaign = _read_json(_campaign_path(campaign_id), None)
        if not campaign:
            raise KeyError(campaign_id)
        queued = 0
        now = _now_iso()
        for run in campaign.get("runs", []):
            current_status = run.get("status")
            can_queue = current_status == "planned" or (
                rerun_all and current_status in {"completed", "failed", "skipped"}
            )
            if can_queue:
                run["status"] = "queued"
                run["updated_at"] = now
                run["last_error"] = None
                queued += 1
        schedule = _normalize_schedule(campaign.get("schedule"))
        if queued and schedule.get("enabled"):
            schedule["last_queued_at"] = _schedule_now().isoformat()
            schedule["next_run_at"] = _compute_next_run_at(schedule, _schedule_now(), after_queue=True)
            campaign["schedule"] = schedule
        campaign["updated_at"] = now
        campaign["status"] = _campaign_status(campaign)
        campaign["progress"] = _campaign_progress(campaign)
        _write_json(_campaign_path(campaign_id), campaign)
        _save_index(_load_all_campaigns())
        return {"campaign": campaign, "queued": queued}


def update_campaign_schedule(campaign_id: str, schedule_payload: dict) -> dict:
    with _LOCK:
        campaign = _read_json(_campaign_path(campaign_id), None)
        if not campaign:
            raise KeyError(campaign_id)
        campaign["schedule"] = _normalize_schedule(schedule_payload)
        campaign["updated_at"] = _now_iso()
        campaign["status"] = _campaign_status(campaign)
        campaign["progress"] = _campaign_progress(campaign)
        _write_json(_campaign_path(campaign_id), campaign)
        _save_index(_load_all_campaigns())
        return campaign


def begin_campaign_execution(campaign_id: str) -> bool:
    with _LOCK:
        if campaign_id in _ACTIVE_CAMPAIGNS:
            return False
        _ACTIVE_CAMPAIGNS.add(campaign_id)
        return True


def end_campaign_execution(campaign_id: str) -> None:
    with _LOCK:
        _ACTIVE_CAMPAIGNS.discard(campaign_id)


def queued_run_ids(campaign_id: str) -> list[str]:
    with _LOCK:
        campaign = _read_json(_campaign_path(campaign_id), None)
        if not campaign:
            return []
        return [run["run_id"] for run in campaign.get("runs", []) if run.get("status") == "queued"]


def claim_due_campaigns(now: datetime | None = None) -> list[dict]:
    now = now or _schedule_now()
    due_campaigns: list[dict] = []
    with _LOCK:
        campaigns = _load_all_campaigns()
        changed = False
        for campaign in campaigns:
            schedule = _normalize_schedule(campaign.get("schedule"), now)
            campaign["schedule"] = schedule
            if not schedule.get("enabled") or not schedule.get("next_run_at"):
                continue
            next_run = _parse_iso_datetime(schedule.get("next_run_at"))
            if not next_run or next_run > now:
                continue
            if campaign["campaign_id"] in _ACTIVE_CAMPAIGNS:
                continue
            queued = 0
            for run in campaign.get("runs", []):
                if run.get("status") in {"running", "queued"}:
                    continue
                run["status"] = "queued"
                run["updated_at"] = _now_iso()
                run["last_error"] = None
                queued += 1
            if queued == 0:
                continue
            schedule["last_queued_at"] = now.isoformat()
            schedule["next_run_at"] = _compute_next_run_at(schedule, now, after_queue=True)
            campaign["schedule"] = schedule
            campaign["updated_at"] = _now_iso()
            campaign["status"] = _campaign_status(campaign)
            campaign["progress"] = _campaign_progress(campaign)
            _write_json(_campaign_path(campaign["campaign_id"]), campaign)
            due_campaigns.append({"campaign_id": campaign["campaign_id"], "queued": queued})
            changed = True
        if changed:
            _save_index(_load_all_campaigns())
    return due_campaigns


def list_comparison_runs(
    *,
    campaign_id: str | None = None,
    strategy: str | None = None,
    basket_source: str | None = None,
    status: str | None = "completed",
    sort_by: str | None = None,
) -> dict:
    normalized_sort, field, descending = _comparison_sort_details(sort_by)
    with _LOCK:
        campaigns = _load_all_campaigns()

    rows = []
    for campaign in campaigns:
        for run in campaign.get("runs", []):
            row = _comparison_row(campaign, run)
            if _comparison_matches_filters(
                row,
                campaign_id=campaign_id,
                strategy=strategy,
                basket_source=basket_source,
                status=status,
            ):
                rows.append(row)
    rows.sort(key=_comparison_sort_key(field, descending))
    return {
        "items": rows,
        "sort_by": normalized_sort,
        "filters": {
            "campaign_id": campaign_id,
            "strategy": strategy,
            "basket_source": basket_source,
            "status": status,
        },
    }


def compare_run_ids(run_ids: list[str]) -> dict:
    requested = [str(run_id).strip() for run_id in run_ids if str(run_id).strip()]
    with _LOCK:
        campaigns = _load_all_campaigns()

    row_map = {}
    for campaign in campaigns:
        for run in campaign.get("runs", []):
            row = _comparison_row(campaign, run)
            row_map[row["run_id"]] = row

    items = [row_map[run_id] for run_id in requested if run_id in row_map]
    metric_winners = {}
    metrics = {
        "best_return": ("strategy_return_pct", True),
        "best_gap_vs_buy_hold": ("gap_vs_buy_hold_pct", True),
        "best_return_over_drawdown": ("return_over_drawdown", True),
        "lowest_drawdown": ("max_drawdown_pct", False),
    }
    for label, (field, descending) in metrics.items():
        available = [item for item in items if item.get(field) is not None]
        if not available:
            metric_winners[label] = None
            continue
        best = sorted(available, key=_comparison_sort_key(field, descending))[0]
        metric_winners[label] = {
            "run_id": best["run_id"],
            "run_name": best["run_name"],
            "campaign_id": best["campaign_id"],
            "value": best[field],
        }
    return {"items": items, "metric_winners": metric_winners}


def update_run_state(
    campaign_id: str,
    run_id: str,
    *,
    status: str,
    last_result: dict | None = None,
    last_error: str | None = None,
) -> dict:
    if status not in VALID_RUN_STATUSES:
        raise ValueError(f"Invalid run status '{status}'")

    with _LOCK:
        campaign = _read_json(_campaign_path(campaign_id), None)
        if not campaign:
            raise KeyError(campaign_id)
        target = None
        for run in campaign.get("runs", []):
            if run["run_id"] == run_id:
                target = run
                break
        if target is None:
            raise KeyError(run_id)

        now = _now_iso()
        target["status"] = status
        target["updated_at"] = now
        target["last_run_at"] = now
        target["last_error"] = last_error
        if last_result is not None:
            target["last_result"] = last_result

        campaign["updated_at"] = now
        campaign["status"] = _campaign_status(campaign)
        campaign["progress"] = _campaign_progress(campaign)
        _write_json(_campaign_path(campaign_id), campaign)
        _save_index(_load_all_campaigns())
        return campaign
