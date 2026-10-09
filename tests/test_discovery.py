from types import SimpleNamespace
from discovery import screen_snapshot

def test_liquid_quote():
    q = SimpleNamespace(last_done='4.5', volume=100000, turnover='450000')
    assert screen_snapshot(q)

def test_zero_volume_rejected():
    q = SimpleNamespace(last_done='4.5', volume=0, turnover='450000')
    assert not screen_snapshot(q)

def test_missing_quote_rejected():
    assert not screen_snapshot(SimpleNamespace())

from discovery import is_common_equity

def test_common_stock_allowed():
    assert is_common_equity({"Symbol":"AAPL","Security Name":"Apple Inc. Common Stock","ETF":"N","Test Issue":"N"})

def test_security_classes_excluded():
    for name in ("Example Corp Warrants", "Example Corp Units", "Example Corp Rights", "Example Corp Preferred Stock", "Example Corp Depositary Shares", "Example Corp Convertible Notes"):
        assert not is_common_equity({"Symbol":"ABCD","Security Name":name})
    assert not is_common_equity({"Symbol":"ABCD","Security Name":"Example ETF","ETF":"Y"})
    assert not is_common_equity({"Symbol":"ABCD","Security Name":"Example Common Stock","Test Issue":"Y"})

def test_no_unintended_price_floor():
    q = SimpleNamespace(last_done="0.39", volume=300000, turnover=117000)
    assert screen_snapshot(q)
