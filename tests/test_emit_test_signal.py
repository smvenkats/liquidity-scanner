from datetime import datetime, timezone
from execution.scanner.emit_test_signal import make_test_signal


def test_make_test_signal_has_dashboard_fields():
    s = make_test_signal(datetime(2026, 6, 4, 15, 30, tzinfo=timezone.utc))
    for k in ("signal_id", "symbol", "direction", "entry_price", "stop_price", "target_price",
              "rr", "rs_score", "spread_bps", "volume_context", "killzone", "qualified"):
        assert k in s
    assert s["signal_id"].startswith("TEST-")
    assert s["symbol"] == "TEST" and s["direction"] == "long" and s["rr"] == 10.0
