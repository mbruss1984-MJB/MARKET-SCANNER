from scoring import Bar, analyze

def test_no_signal():
    bars = [Bar(1,1,1,1,100) for _ in range(7)]
    assert analyze(bars,bars)["state"] == "NO_SIGNAL"

def test_early_starter():
    bars = [Bar(1,1,1,1,100) for _ in range(6)] + [Bar(1,1.01,1,1.01,500)]
    five = [Bar(1,1,1,1,100) for _ in range(7)]
    assert analyze(bars,five)["state"] == "EARLY_STARTER_CANDIDATE"

def test_insufficient():
    assert analyze([],[])["state"] == "INSUFFICIENT_DATA"

def test_early_2x_volume_detected_with_three_completed_five_minute_bars():
    one = [Bar(1, 1, 1, 1, 100) for _ in range(7)]
    five = [Bar(1, 1, 1, 1, 100) for _ in range(2)] + [Bar(1, 1.005, 1, 1.004, 250)]
    result = analyze(one, five)
    assert result["state"] == "EARLY_VOLUME_WATCH_2X"
    assert result["discovery_tier"] == "EARLY_WATCH_2X"
    assert result["five_minute_baseline_bars"] == 2

def test_4x_ignition_does_not_require_previous_one_minute_4x():
    one = [Bar(1, 1, 1, 1, 100) for _ in range(7)]
    five = [Bar(1, 1, 1, 1, 100) for _ in range(2)] + [Bar(1, 1.01, 1, 1.006, 500)]
    result = analyze(one, five)
    assert result["state"] == "VOLUME_IGNITION_4X"
    assert result["discovery_tier"] == "IGNITION_4X"
