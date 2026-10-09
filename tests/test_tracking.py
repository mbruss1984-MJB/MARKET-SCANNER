from datetime import datetime, timedelta, timezone
from tracking import SignalTracker

def test_signal_lifecycle_and_excursions(tmp_path):
    tracker = SignalTracker(str(tmp_path / "signals.db"))
    now = datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc)
    active = {"state": "EARLY_STARTER_CANDIDATE"}
    tracker.observe("TEST.US", active, 10.0, "bar-1", now)
    assert tracker.summary() == {"ACTIVE": 1}
    tracker.observe("TEST.US", active, 11.0, "bar-1", now)
    assert len(tracker.recent()) == 1
    tracker.observe("TEST.US", active, 12.0, "bar-2", now + timedelta(minutes=1))
    tracker.observe("TEST.US", {"state": "NO_SIGNAL"}, 9.0, "bar-3", now + timedelta(minutes=2))
    result = tracker.recent()[0]
    assert result["lifecycle"] == "INVALIDATED"
    assert result["peak_gain_pct"] == 20.0
    assert result["max_drawdown_pct"] == -10.0

def test_unobserved_signal_expires(tmp_path):
    tracker = SignalTracker(str(tmp_path / "signals.db"))
    now = datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc)
    tracker.observe("TEST.US", {"state": "CONFIRMED_STARTER"}, 4, "bar-1", now)
    tracker.expire(now + timedelta(minutes=11))
    assert tracker.summary() == {"EXPIRED": 1}

def test_no_signal_does_not_create_entry(tmp_path):
    tracker = SignalTracker(str(tmp_path / "signals.db"))
    tracker.observe("TEST.US", {"state": "NO_SIGNAL"}, 5, "bar-1")
    assert tracker.recent() == []
