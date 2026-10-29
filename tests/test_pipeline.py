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

def test_catalyst_bonus_never_creates_signal_without_momentum():
    history = {}
    assert select_candidates([quote()], history, lambda q: True, now=1000,
                             catalyst_bonus=lambda s: 6) == []
    # Flat price & flat volume still cannot qualify.
    assert select_candidates([quote()], history, lambda q: True, now=1060,
                             catalyst_bonus=lambda s: 6) == []


def test_catalyst_bonus_only_reorders_existing_candidates():
    history = {}
    a = quote(symbol="A.US", price=5, prev=4, volume=100000)
    b = quote(symbol="B.US", price=5, prev=4, volume=100000)
    select_candidates([a,b], history, lambda q: True, now=1000)
    second = [quote(symbol="A.US", price=5.10, prev=4, volume=110000),
              quote(symbol="B.US", price=5.09, prev=4, volume=110000)]
    ranked = select_candidates(second, history, lambda q: True, now=1060,
                               catalyst_bonus=lambda s: 6 if s=="B.US" else 0)
    assert len(ranked) == 2
    assert ranked[0][1] == "B.US"
    assert ranked[0][2]["catalyst_priority_bonus"] == 6
