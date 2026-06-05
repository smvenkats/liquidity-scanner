import json
from execution.scanner.run_scan import filter_fresh, existing_signal_ids


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
