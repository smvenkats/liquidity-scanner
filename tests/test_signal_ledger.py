from datetime import datetime, timezone

from execution.scanner.ledger import enrich_signal_record, is_active_today, market_date_et


def test_market_date_et_uses_new_york_date():
    assert market_date_et("2026-06-25T13:30:00+00:00") == "2026-06-25"


def test_enrich_signal_record_adds_metadata_to_current_flat_row():
    created = datetime(2026, 6, 25, 14, 0, tzinfo=timezone.utc)
    row = enrich_signal_record({
        "signal_id": "AAPL-PDL-20260625T0930",
        "symbol": "AAPL",
        "reentry_time": "2026-06-25T09:30:00-04:00",
        "qualified": True,
    }, created_at=created)

    assert row["source"] == "equities_sweep_python"
    assert row["asset_type"] == "equity"
    assert row["market_date"] == "2026-06-25"
    assert row["created_at"] == "2026-06-25T14:00:00+00:00"
    assert row["triggered_at"] == "2026-06-25T09:30:00-04:00"
    assert row["status"] == "active"
    assert row["outcome"] is None
    assert row["evaluated_at"] is None
    assert row["symbol"] == "AAPL"


def test_enrich_signal_record_preserves_existing_metadata():
    row = enrich_signal_record({
        "signal_id": "MSFT-PDL-20260625T0930",
        "symbol": "MSFT",
        "reentry_time": "2026-06-25T09:30:00-04:00",
        "source": "custom_source",
        "asset_type": "evm_token",
        "market_date": "2026-06-24",
        "created_at": "2026-06-25T14:00:00+00:00",
        "triggered_at": "2026-06-25T13:30:00+00:00",
        "status": "resolved",
        "outcome": "target",
        "evaluated_at": "2026-06-25T15:00:00+00:00",
    })

    assert row["source"] == "custom_source"
    assert row["asset_type"] == "evm_token"
    assert row["market_date"] == "2026-06-24"
    assert row["status"] == "resolved"
    assert row["outcome"] == "target"


def test_is_active_today_excludes_old_resolved_and_malformed_rows():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=timezone.utc)

    assert is_active_today({
        "reentry_time": "2026-06-25T09:30:00-04:00",
        "status": "active",
    }, now=now)
    assert not is_active_today({
        "reentry_time": "2026-06-24T09:30:00-04:00",
        "status": "active",
    }, now=now)
    assert not is_active_today({
        "reentry_time": "2026-06-25T09:30:00-04:00",
        "status": "resolved",
    }, now=now)
    assert not is_active_today({
        "reentry_time": "not-a-date",
        "status": "active",
    }, now=now)
