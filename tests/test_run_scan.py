import json
from execution.scanner.run_scan import (
    filter_fresh, existing_signal_ids, write_scan_status, load_scan_status, run_scan)


class _S:
    def __init__(self, sid):
        self.signal_id = sid


def test_existing_signal_ids_reads_jsonl(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"signal_id": "A"}) + "\n" + json.dumps({"signal_id": "B"}) + "\n")
    assert existing_signal_ids(p) == {"A", "B"}


def test_existing_signal_ids_missing_file_is_empty(tmp_path):
    assert existing_signal_ids(tmp_path / "none.jsonl") == set()


def test_existing_signal_ids_skips_bad_lines(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"signal_id": "A"}) + "\n{ broken json\n" + json.dumps({"signal_id": "B"}) + "\n")
    assert existing_signal_ids(p) == {"A", "B"}


def test_filter_fresh_excludes_already_emitted(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"signal_id": "A"}) + "\n")
    fresh = filter_fresh([_S("A"), _S("B"), _S("C")], p)
    assert [s.signal_id for s in fresh] == ["B", "C"]


def test_scan_status_roundtrip_creates_parent(tmp_path):
    p = tmp_path / "data" / "scan_status.json"
    write_scan_status(p, {
        "raw_candidates": 8,
        "emitted": 4,
        "benchmark_latest_5m": "2026-06-18T16:55:00-04:00",
        "failed_backfills": {"SPY_5m": "failed"},
    })

    got = load_scan_status(p)
    assert got["raw_candidates"] == 8
    assert got["emitted"] == 4
    assert got["failed_backfills"] == {"SPY_5m": "failed"}


def test_run_scan_writes_abort_status_when_benchmark_missing(tmp_path):
    status = tmp_path / "scan_status.json"
    signals = tmp_path / "signals.jsonl"
    bars = tmp_path / "bars"

    n = run_scan({"data": {"universe": []}}, out_dir=bars, signals_path=signals,
                 benchmark="SPY", do_backfill=False, status_path=status)

    got = load_scan_status(status)
    assert n == 0
    assert got["abort"] == "no_benchmark_5m"
    assert got["benchmark"] == "SPY"
    assert got["benchmark_5m_rows"] == 0
    assert got["raw_candidates"] == 0
    assert got["emitted"] == 0
