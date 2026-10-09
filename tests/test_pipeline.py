from types import SimpleNamespace
from pipeline import discover_initial, select_candidates

def quote(symbol="TEST.US", price=5, prev=4, volume=100000, turnover=500000):
    return SimpleNamespace(symbol=symbol,last_done=price,prev_close=prev,volume=volume,turnover=turnover)

def test_first_seen_day_mover_is_discovered():
    assert discover_initial([quote()], lambda q: True) == ["TEST.US"]

def test_first_seen_not_false_acceleration():
    history = {}
    assert select_candidates([quote()], history, lambda q: True, now=1000) == []

def test_second_observation_can_accelerate():
    history = {}
    select_candidates([quote()], history, lambda q: True, now=1000)
    results = select_candidates([quote(price=5.1,volume=110000)], history, lambda q: True, now=1060)
    assert results and results[0][1] == "TEST.US"

def test_stale_comparison_rejected():
    history = {}
    select_candidates([quote()], history, lambda q: True, now=1000)
    assert select_candidates([quote(price=6,volume=150000)], history, lambda q: True, now=2000) == []
