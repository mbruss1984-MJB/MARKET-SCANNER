from scoring import Bar, analyze

def test_no_signal():
    bars = [Bar(1,1,1,1,100) for _ in range(7)]
    assert analyze(bars,bars)["state"] == "NO_SIGNAL"

def test_early_starter():
    bars = [Bar(1,1,1,1,100) for _ in range(6)] + [Bar(1,1.01,1,1.01,500)]
    five = [Bar(1,1,1,1,100) for _ in range(7)]
    result = analyze(bars,five)
    assert result["state"] == "REJECTED_ENTRY"
    assert result["raw_volume_state"] == "EARLY_STARTER_CANDIDATE"
    assert not result["quality_gate_passed"]

def test_insufficient():
    assert analyze([],[])["state"] == "INSUFFICIENT_DATA"

def test_early_2x_volume_detected_with_three_completed_five_minute_bars():
    one = [Bar(1, 1, 1, 1, 100) for _ in range(7)]
    five = [Bar(1, 1, 1, 1, 100) for _ in range(2)] + [Bar(1, 1.005, 1, 1.004, 250)]
    result = analyze(one, five)
    assert result["state"] == "REJECTED_ENTRY"
    assert result["raw_volume_state"] == "EARLY_VOLUME_WATCH_2X"
    assert result["discovery_tier"] is None
    assert result["five_minute_baseline_bars"] == 2

def test_4x_ignition_does_not_require_previous_one_minute_4x():
    one = [Bar(1, 1, 1, 1, 100) for _ in range(7)]
    five = [Bar(1, 1, 1, 1, 100) for _ in range(2)] + [Bar(1, 1.01, 1, 1.006, 500)]
    result = analyze(one, five)
    assert result["state"] == "REJECTED_ENTRY"
    assert result["raw_volume_state"] == "VOLUME_IGNITION_4X"
    assert result["discovery_tier"] is None

def test_quality_gate_allows_sustained_climb_with_volume():
    one = [Bar(10,10.02,9.98,10,1000) for _ in range(6)] + [
        Bar(10,10.06,10,10.05,3000),
        Bar(10.05,10.11,10.03,10.09,6000),
        Bar(10.10,10.19,10.07,10.18,9000)]
    five = [Bar(10,10.02,9.98,10,1000) for _ in range(2)] + [
        Bar(10,10.20,10,10.15,5000)]
    result = analyze(one, five)
    assert result["state"] == "CONFIRMED_STARTER"
    assert result["quality_gate_passed"]
    assert result["discovery_tier"] == "IGNITION_4X"

def test_first_completed_five_minute_bar_can_support_early_detection():
    one = [Bar(10,10.02,9.98,10,1000) for _ in range(6)] + [
        Bar(10,10.06,10,10.05,3000),
        Bar(10.05,10.11,10.03,10.09,6000),
        Bar(10.10,10.19,10.07,10.18,9000)]
    result = analyze(one, [Bar(10,10.2,10,10.15,5000)])
    assert result["state"] == "EARLY_STARTER_CANDIDATE"
    assert result["quality_gate_passed"]
    assert result["volume_ratio_5m"] is None

def test_rejects_weakening_high_volume_candle():
    one = [Bar(10,10.02,9.98,10,1000) for _ in range(6)] + [
        Bar(10,10.2,10,10.18,3000),
        Bar(10.18,10.30,10.15,10.27,6000),
        Bar(10.27,10.35,10.12,10.19,9000)]
    five = [Bar(10,10.02,9.98,10,1000) for _ in range(2)] + [
        Bar(10,10.35,10,10.19,5000)]
    result = analyze(one, five)
    assert result["state"] == "REJECTED_ENTRY"
    assert "price_lows_or_closes_not_rising" in result["quality_rejections"]
