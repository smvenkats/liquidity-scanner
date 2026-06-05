import pytest
from execution.execute.ticket import build_ticket, OrderTicket


class _Sig:
    """Minimal Signal stand-in carrying only the fields build_ticket reads."""
    def __init__(self, direction, entry, stop, target, risk, symbol="NVDA"):
        self.symbol = symbol; self.direction = direction
        self.entry_price = entry; self.stop_price = stop
        self.target_price = target; self.risk = risk


def _ticket(direction="long", entry=214.66, stop=214.41, target=222.82, risk=0.25,
            risk_usd=100, max_notional=5000, max_qty=10000):
    return build_ticket(_Sig(direction, entry, stop, target, risk),
                        risk_usd=risk_usd, max_notional=max_notional, max_qty=max_qty)


def test_long_maps_to_buy_and_wires_prices():
    t = _ticket(direction="long")
    assert isinstance(t, OrderTicket)
    assert t.side == "buy" and t.order_type == "limit"
    assert t.limit_price == 214.66 and t.stop_price == 214.41 and t.target_price == 222.82
    assert t.risk_per_share == 0.25


def test_short_maps_to_sell():
    assert _ticket(direction="short").side == "sell"


def test_qty_is_risk_based_and_notional_computed():
    t = _ticket(risk=0.25, risk_usd=100)        # 100 / 0.25 = 400 shares
    assert t.qty == 400
    assert t.est_notional == pytest.approx(400 * 214.66)


def test_notional_cap_warning_fires_over_limit():
    t = _ticket(risk=0.25, risk_usd=100, max_notional=5000)   # ~$85,864 notional
    assert any("exceeds max $5,000" in w for w in t.warnings)


def test_no_notional_warning_when_within_cap():
    t = _ticket(risk=0.25, risk_usd=100, max_notional=200000)  # well above ~$86k
    assert not any("notional" in w for w in t.warnings)


def test_qty_cap_warning_fires():
    t = _ticket(risk=0.01, risk_usd=100, max_qty=100)   # 100/0.01 = 10000 > 100
    assert any("qty 10000 exceeds max 100" in w for w in t.warnings)


def test_sub_one_share_warning_and_zero_qty():
    t = _ticket(risk=1000, risk_usd=100)   # stop wider than budget -> 0 shares
    assert t.qty == 0
    assert any("too small for one share" in w for w in t.warnings)


def test_execution_caps_present_in_params():
    from execution.config import load_params
    e = load_params()["execution"]
    assert e["per_order_max_notional_usd"] == 5000
    assert e["per_order_max_qty"] == 10000
