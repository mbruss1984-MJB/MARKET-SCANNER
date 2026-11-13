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
    """Use completed bars only. Seven 1m bars and three 5m bars allow early detection."""
    if len(one_minute) < 7 or len(five_minute) < 1:
        return {"state": "INSUFFICIENT_DATA", "reason": "Need 7 completed 1m bars and at least 1 completed 5m bar"}
    a, b = one_minute[-1], five_minute[-1]
    v1 = median(x.volume for x in one_minute[-7:-1])
    # Compare with up to six *prior* completed 5m candles. At the open,
    # two prior bars suffice to avoid waiting 35 minutes for seven candles.
    prior_five = five_minute[-7:-1]
    v5 = median(x.volume for x in prior_five) if prior_five else 0
    r1 = a.volume / v1 if v1 > 0 else None
    r5 = b.volume / v5 if v5 > 0 else None
    p1 = 100 * (a.close / a.open - 1) if a.open > 0 else 0
    p5 = 100 * (b.close / b.open - 1) if b.open > 0 else 0
    p15 = (100 * (b.close / five_minute[-3].open - 1)
           if len(five_minute) >= 3 and five_minute[-3].open > 0 else 0)
    early = (r1 is not None and r1 >= 4 and p1 >= 0.5)
    confirmed = early and (r5 is not None and r5 >= 4 and p15 >= 0.25)
    volume_watch_2x = r5 is not None and r5 >= 2 and p5 >= 0.25
    volume_ignition_4x = r5 is not None and r5 >= 4 and p5 >= 0.25 and p15 >= 0.4
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
    # A large volume print alone is not a qualified long entry. Reject fading
    # candles, late vertical extensions, and entries far from a viable stop.
    recent_peak = max(x.high for x in one_minute[-6:])
    candle_range = max(0, a.high - a.low)
    upper_wick_share = ((a.high - max(a.open, a.close)) / candle_range
                        if candle_range > 0 else 0)
    vwap_extension_pct = (100 * (a.close / rolling_vwap - 1)
                          if rolling_vwap and rolling_vwap > 0 else None)
    stop_distance_pct = (100 * max(0, a.close - invalidation) / a.close
                         if a.close > 0 else None)
    higher_closes = recent[-3].close <= recent[-2].close <= recent[-1].close
    quality_rejections = []
    if not higher_lows or not higher_closes:
        quality_rejections.append("price_lows_or_closes_not_rising")
    if a.close < a.open:
        quality_rejections.append("last_minute_selling")
    if not above_vwap:
        quality_rejections.append("below_recent_vwap")
    if recent_peak > 0 and a.close < recent_peak * 0.985:
        quality_rejections.append("pulled_back_over_1_5pct_from_peak")
    if upper_wick_share > 0.4:
        quality_rejections.append("large_upper_wick")
    if vwap_extension_pct is not None and vwap_extension_pct > 6:
        quality_rejections.append("more_than_6pct_above_vwap")
    if stop_distance_pct is not None and stop_distance_pct > 5.5:
        quality_rejections.append("stop_too_far_over_5_5pct")
    if dollar_volume < 20000:
        quality_rejections.append("thin_three_minute_turnover")
    quality_passed = not quality_rejections

    pre = (buildup_ratio is not None and buildup_ratio >= 1.5
           and dollar_volume >= 10000 and rising_volume
           and above_vwap and (compression or higher_lows or reclaim)
           and a.close <= resistance * 1.005 and risk > 0)
    raw_state = ("CONFIRMED_STARTER" if confirmed else
                 "EARLY_STARTER_CANDIDATE" if early else
                 "VOLUME_IGNITION_4X" if volume_ignition_4x else
                 "EARLY_VOLUME_WATCH_2X" if volume_watch_2x else
                 "PRE_IGNITION" if pre else
                 "WATCH" if ((r5 or 0) >= 2 and p5 > 0) else "NO_SIGNAL")
    state = (raw_state if quality_passed or raw_state in ("WATCH", "NO_SIGNAL")
             else "REJECTED_ENTRY")
    return {"state": state,
            "discovery_tier": ("IGNITION_4X" if volume_ignition_4x else "EARLY_WATCH_2X" if volume_watch_2x else None) if quality_passed else None,
            "five_minute_baseline_bars": len(prior_five),
            "buildup_volume_ratio": round(buildup_ratio, 3) if buildup_ratio is not None else None,
            "dollar_volume_3m": round(dollar_volume, 2),
            "compression": compression, "higher_lows": higher_lows,
            "rising_volume": rising_volume, "vwap_reclaim": reclaim,
            "higher_closes": higher_closes, "quality_gate_passed": quality_passed,
            "quality_rejections": quality_rejections, "raw_volume_state": raw_state,
            "upper_wick_share": round(upper_wick_share, 3),
            "vwap_extension_pct": round(vwap_extension_pct, 2) if vwap_extension_pct is not None else None,
            "stop_distance_pct": round(stop_distance_pct, 2) if stop_distance_pct is not None else None,
            "rolling_vwap_15m": rolling_vwap, "above_rolling_vwap": above_vwap,
            "setup_trigger": resistance, "setup_invalidation": invalidation,
            "setup_no_chase": resistance + risk * 0.25 if risk > 0 else None,
            "probability": None, "probability_status": "uncalibrated",
            "setup_type": "rejected" if state == "REJECTED_ENTRY" else ("buildup" if pre and not early else "ignition"),
 "volume_ratio_1m": round(r1, 2) if r1 is not None else None,
            "volume_ratio_5m": round(r5, 2) if r5 is not None else None,
            "price_change_1m_pct": round(p1, 2), "price_change_5m_pct": round(p5, 2),
            "price_change_15m_pct": round(p15, 2),
            "provisional": True, "executable": False,
            "reason": ("Rejected: " + ", ".join(quality_rejections) if state == "REJECTED_ENTRY" else
                       "Research only: verify spreads, liquidity, catalyst and supply risk before entry")}

