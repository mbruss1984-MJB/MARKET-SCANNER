"""Pure scoring logic; does not send orders or make trading decisions."""
from dataclasses import dataclass
from statistics import median

@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float

def analyze(one_minute: list[Bar], five_minute: list[Bar]) -> dict:
    """Bars must be completed and ordered oldest first. At least 7 of each."""
    if len(one_minute) < 7 or len(five_minute) < 7:
        return {"state": "INSUFFICIENT_DATA", "reason": "Need 7 completed bars of each timeframe"}
    a, b = one_minute[-1], five_minute[-1]
    v1 = median(x.volume for x in one_minute[-7:-1])
    v5 = median(x.volume for x in five_minute[-7:-1])
    r1 = a.volume / v1 if v1 > 0 else None
    r5 = b.volume / v5 if v5 > 0 else None
    p1 = 100 * (a.close / a.open - 1) if a.open > 0 else 0
    p5 = 100 * (b.close / b.open - 1) if b.open > 0 else 0
    p15 = 100 * (b.close / five_minute[-3].open - 1) if five_minute[-3].open > 0 else 0
    early = (r1 is not None and r1 >= 4 and p1 >= 0.5)
    confirmed = early and (r5 is not None and r5 >= 4 and p15 >= 0.25)
    state = "CONFIRMED_STARTER" if confirmed else "EARLY_STARTER_CANDIDATE" if early else "WATCH" if ((r5 or 0) >= 2 and p5 > 0) else "NO_SIGNAL"
    return {"state": state, "volume_ratio_1m": round(r1, 2) if r1 is not None else None,
            "volume_ratio_5m": round(r5, 2) if r5 is not None else None,
            "price_change_1m_pct": round(p1, 2), "price_change_5m_pct": round(p5, 2),
            "price_change_15m_pct": round(p15, 2),
            "provisional": True, "executable": False,
            "reason": "Requires separate bid/ask, liquidity, catalyst and supply-risk checks before any entry"}
