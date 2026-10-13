"""Pure scoring logic; does not send orders or make trading decisions."""
from dataclasses import dataclass
from statistics import median, mean

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
    # Buildup is a research alert, not an order: rising participation before 4x.
    recent = one_minute[-3:]
    baseline = mean(x.volume for x in one_minute[-9:-3]) if len(one_minute) >= 9 else 0
    recent_rate = mean(x.volume for x in recent)
    buildup_ratio = recent_rate / baseline if baseline > 0 else None
    dollar_volume = sum(x.volume * x.close for x in recent)
    prior = one_minute[-6:-3]
    recent_range = max(x.high for x in recent) - min(x.low for x in recent)
    prior_range = max(x.high for x in prior) - min(x.low for x in prior)
    compression = prior_range > 0 and recent_range <= prior_range * 0.8
    higher_lows = recent[0].low <= recent[1].low <= recent[2].low
    rising_volume = recent[0].volume < recent[1].volume <= recent[2].volume
    total_volume = sum(x.volume for x in one_minute[-15:])
    rolling_vwap = (sum((x.high + x.low + x.close) / 3 * x.volume
                        for x in one_minute[-15:]) / total_volume) if total_volume > 0 else None
    above_vwap = rolling_vwap is not None and a.close >= rolling_vwap
    reclaim = above_vwap and one_minute[-2].close < rolling_vwap
    resistance = max(x.high for x in one_minute[-6:-1])
    invalidation = min(x.low for x in recent)
    risk = max(0, resistance - invalidation)
    pre = (buildup_ratio is not None and buildup_ratio >= 1.5
           and dollar_volume >= 10000 and rising_volume
           and above_vwap and (compression or higher_lows or reclaim)
           and a.close <= resistance * 1.005 and risk > 0)
    state = "CONFIRMED_STARTER" if confirmed else "EARLY_STARTER_CANDIDATE" if early else "PRE_IGNITION" if pre else "WATCH" if ((r5 or 0) >= 2 and p5 > 0) else "NO_SIGNAL"
    return {"state": state,
            "buildup_volume_ratio": round(buildup_ratio, 3) if buildup_ratio is not None else None,
            "dollar_volume_3m": round(dollar_volume, 2),
            "compression": compression, "higher_lows": higher_lows,
            "rising_volume": rising_volume, "vwap_reclaim": reclaim,
            "rolling_vwap_15m": rolling_vwap, "above_rolling_vwap": above_vwap,
            "setup_trigger": resistance, "setup_invalidation": invalidation,
            "setup_no_chase": resistance + risk * 0.25 if risk > 0 else None,
            "probability": None, "probability_status": "uncalibrated",
            "setup_type": "buildup" if pre and not early else "ignition",
 "volume_ratio_1m": round(r1, 2) if r1 is not None else None,
            "volume_ratio_5m": round(r5, 2) if r5 is not None else None,
            "price_change_1m_pct": round(p1, 2), "price_change_5m_pct": round(p5, 2),
            "price_change_15m_pct": round(p15, 2),
            "provisional": True, "executable": False,
            "reason": "Requires separate bid/ask, liquidity, catalyst and supply-risk checks before any entry"}

