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
