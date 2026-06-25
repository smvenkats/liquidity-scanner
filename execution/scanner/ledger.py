# execution/scanner/ledger.py
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
ACTIVE_STATUSES = {"active"}


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def market_date_et(value) -> str | None:
    dt = _parse_dt(value)
    if dt is None:
        return None
    return dt.astimezone(_ET).date().isoformat()


def enrich_signal_record(record: dict, *, created_at: datetime | None = None) -> dict:
    out = dict(record)
    triggered_at = out.get("triggered_at") or out.get("reentry_time")
    created = created_at or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    out.setdefault("source", "equities_sweep_python")
    out.setdefault("asset_type", "equity")
    out.setdefault("market_date", market_date_et(triggered_at))
    out.setdefault("created_at", created.isoformat())
    out.setdefault("triggered_at", triggered_at)
    out.setdefault("status", "active")
    out.setdefault("outcome", None)
    out.setdefault("evaluated_at", None)
    return out


def is_active_today(record: dict, *, now: datetime | None = None) -> bool:
    enriched = enrich_signal_record(record)
    today = market_date_et(now or datetime.now(timezone.utc))
    return bool(
        enriched.get("market_date")
        and enriched.get("market_date") == today
        and enriched.get("status", "active") in ACTIVE_STATUSES
    )
