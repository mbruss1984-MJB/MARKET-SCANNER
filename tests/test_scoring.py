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
