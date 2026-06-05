from execution.scanner.tiers import split_tiers, position_size


class _Sig:
    def __init__(self, sid):
        self.signal_id = sid


def test_split_tiers_separates_reversal_from_aligned():
    a, b = _Sig("AL"), _Sig("REV")
    A, B = split_tiers([a], [a, b])  # aligned set vs full core-passing set
    assert [s.signal_id for s in A] == ["AL"]
    assert [s.signal_id for s in B] == ["REV"]


def test_split_tiers_all_aligned_means_empty_reversal():
    a = _Sig("AL")
    A, B = split_tiers([a], [a])
    assert len(A) == 1 and B == []


def test_position_size_floors_to_whole_shares():
    assert position_size(0.25, 100) == 400   # 100 / 0.25
    assert position_size(0.30, 100) == 333   # floor(333.3)


def test_position_size_guards_nonpositive_risk():
    assert position_size(0.0, 100) == 0
    assert position_size(-1.0, 100) == 0
    assert position_size(0.25, -100) == 0   # negative risk budget -> 0, never negative shares
    assert position_size(0.25, 0) == 0


def test_annotate_trend_sets_real_1h_bias():
    from datetime import datetime, timezone, timedelta
    from execution.scanner.tiers import annotate_trend

    class _Bar:
        def __init__(self, ts, c): self.ts, self.c = ts, c

    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    rising = [_Bar(base + timedelta(hours=i), 100 + i) for i in range(30)]  # uptrending 1h closes

    class _Feed:
        def bars(self, sym, tf): return rising if tf == "1h" else []

    class _Sig:
        symbol = "X"; reentry_time = base + timedelta(hours=40); htf_bias = None

    params = {"trend": {"htf_ema_len": 20, "htf_require_slope": False}}
    out = annotate_trend([_Sig()], _Feed(), params)
    assert out[0].htf_bias == "up"


def test_dedupe_setups_keeps_earliest_per_setup():
    from datetime import datetime, timezone
    from execution.scanner.tiers import dedupe_setups

    class _S:
        def __init__(self, sym, lvl, d, minute):
            self.symbol, self.level_type, self.direction = sym, lvl, d
            self.reentry_time = datetime(2026, 6, 4, 10, minute, tzinfo=timezone.utc)

    sigs = [_S("NVDA", "PDL", "long", 45), _S("NVDA", "PDL", "long", 40),
            _S("NVDA", "PDL", "long", 50), _S("AMD", "PDL", "long", 30)]
    out = dedupe_setups(sigs)
    assert {(s.symbol, s.level_type, s.direction) for s in out} == {
        ("NVDA", "PDL", "long"), ("AMD", "PDL", "long")}
    nvda = next(s for s in out if s.symbol == "NVDA")
    assert nvda.reentry_time.minute == 40  # earliest trigger kept


def test_render_shows_both_tiers_and_a_sized_ticket():
    from datetime import datetime, timezone
    from execution.scanner.daily import render

    class _FullSig:
        signal_id = "x"; symbol = "NVDA"; direction = "long"; level_type = "PDL"
        reentry_time = datetime(2026, 6, 4, 10, 40, tzinfo=timezone.utc)
        killzone = "midday"; entry_price = 214.66; stop_price = 214.41
        target_price = 222.82; rr = 31.98; rs_score = 0.0059; risk = 0.25; htf_bias = "up"

    out = render([_FullSig()], [], session="2026-06-04", risk_usd=100,
                 max_notional=5000, max_qty=10000)
    assert "TIER A" in out and "aligned with 1h trend (1)" in out
    assert "TIER B" in out and "(none)" in out
    assert "NVDA" in out
    assert "BUY 400 sh" in out                  # long -> BUY, 100/0.25 = 400
    assert "exceeds max $5,000" in out           # ~$85,864 notional trips the default cap
