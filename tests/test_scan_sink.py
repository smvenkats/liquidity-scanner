# tests/test_scan_sink.py
import json
from datetime import datetime
from execution.detect import SweepCandidate
from execution.filters import RSResult, LiquidityResult, RRResult
from execution.signals import build_signal
from execution.scanner.sink import emit_signals

def _sig():
    ts = datetime.fromisoformat("2026-06-04T14:20:00-04:00")
    c = SweepCandidate(direction="long", level_type="PDL", level_price=99.0, sweep_index=0,
                       sweep_ts=ts, reentry_index=0, reentry_ts=ts, wick_extreme=98.5,
                       reentry_close=99.7, reentry_volume=2_000_000)
    rs = RSResult(0.004, 0.005, 0.001, True, False)
    liq = LiquidityResult(True, {})
    rr = RRResult(99.7, 98.48, 110.0, 0.02, 1.22, 10.3, 8.4, True)
    return build_signal(candidate=c, symbol="ABC", rs=rs, liquidity=liq, rr=rr, benchmark="SPY",
                        rs_window_min=20, spread_abs=0.01, spread_bps=1.0,
                        volume_context={"rvol": 1.9}, alt_targets={}, killzone="ny_open",
                        mode="live", htf_trend="up")

def test_emit_appends_jsonl(tmp_path):
    path = tmp_path / "signals.jsonl"
    emit_signals([_sig()], path)
    emit_signals([_sig()], path)             # append, not overwrite
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["symbol"] == "ABC" and rec["qualified"] is True and rec["target_price"] == 110.0
    assert rec["source"] == "equities_sweep_python"
    assert rec["asset_type"] == "equity"
    assert rec["market_date"] == "2026-06-04"
    assert rec["triggered_at"] == "2026-06-04T14:20:00-04:00"
    assert rec["status"] == "active"
    assert rec["outcome"] is None
    assert rec["evaluated_at"] is None
