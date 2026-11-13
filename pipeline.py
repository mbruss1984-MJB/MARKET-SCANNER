"""Read-only momentum discovery from quote snapshots, with no trade execution."""
from datetime import datetime, timezone

def _float(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def day_gain_pct(quote):
    last = _float(getattr(quote, "last_done", 0))
    previous = _float(getattr(quote, "prev_close", 0))
    return 100 * (last / previous - 1) if previous > 0 and last > 0 else 0

def quote_strength(quote):
    """Same-day change is a discovery hint, not evidence of fresh ignition."""
    change = day_gain_pct(quote)
    turnover = _float(getattr(quote, "turnover", 0))
    # Prefer emerging 0.5%-8% moves rather than ranking 30%-100% spikes
    # at the top of discovery just because of their existing daily gains.
    participation = min(10, max(0, turnover / 1_000_000))
    emerging = max(-20, min(8, change)) * 3
    extension_penalty = max(0, change - 8) * 4
    return emerging + participation - extension_penalty

def select_candidates(snapshots, history, screen, limit=12, now=None):
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    ranked = []
    rates = history.setdefault("__rates__", {})
    for quote in snapshots:
        symbol = str(quote.symbol)
        if not screen(quote):
            continue
        price = _float(getattr(quote, "last_done", 0))
        volume = _float(getattr(quote, "volume", 0))
        prior = history.get(symbol)
        history[symbol] = (price, volume, now)
        if prior is None:
            continue
        old_price, old_volume, old_time = prior
        elapsed = now - old_time
        # Ignore restarts, stale data, nonmonotonic session volume, and old comparisons.
        if elapsed < 15 or elapsed > 900 or volume < old_volume or old_price <= 0:
            rates.pop(symbol, None)
            continue
        volume_delta = volume - old_volume
        price_pct = 100 * (price / old_price - 1)
        velocity = volume_delta / max(1, elapsed)
        old_rate = rates.get(symbol)
        rates[symbol] = velocity
        volume_acceleration = old_rate is not None and old_rate > 0 and velocity >= old_rate * 2
        buildup = (old_rate is not None and old_rate > 0 and velocity >= old_rate * 1.5
                   and -0.1 <= price_pct < 0.1 and volume_delta * price >= 10000)
        early_acceleration = (volume_acceleration and price_pct >= 0.05
                              and volume_delta * price >= 10000)
        # A single tiny print can move an illiquid quote; require notional
        # turnover for an ordinary positive-price discovery event.
        price_move_candidate = (0.1 <= price_pct <= 3.0 and volume_delta * price >= 5000)
        if price_move_candidate or buildup or early_acceleration:
            score = price_pct * 8 + min(velocity / 100, 20) + (5 if buildup else 0) + (8 if early_acceleration else 0)
            ranked.append((score, symbol, {"price_change_since_seen_pct":round(price_pct, 3),
                "buildup_candidate": buildup, "early_acceleration_2x": early_acceleration,
                "volume_acceleration_ratio": round(velocity / old_rate, 2) if old_rate and old_rate > 0 else None,
                "volume_since_seen":int(volume_delta), "volume_per_second":round(velocity, 2)}))
    ranked.sort(reverse=True)
    return ranked[:limit]

def discover_initial(snapshots, screen, limit=16):
    """Select market-wide first sightings before they become fully extended.

    Reserve slots for early +0.5%-to-2% gainers and still-quiet names.
    This is discovery only: spread, float, catalyst, and VWAP are later gates.
    There is deliberately no upper gain ceiling on discovery.
    """
    eligible = [q for q in snapshots if screen(q)]
    movers = [q for q in eligible if day_gain_pct(q) >= 2]
    early = [q for q in eligible if 0.5 <= day_gain_pct(q) < 2]
    quiet = [q for q in eligible if day_gain_pct(q) < 0.5]
    movers.sort(key=quote_strength, reverse=True)
    early.sort(key=lambda q: (day_gain_pct(q), _float(getattr(q, "turnover", 0))), reverse=True)
    quiet.sort(key=lambda q: (day_gain_pct(q), min(_float(getattr(q, "turnover", 0)), 1_000_000)), reverse=True)
    # Avoid a crowded already-rallied bucket consuming the entire hot-watch queue.
    mover_slots = max(1, limit * 3 // 8)
    early_slots = max(1, limit * 3 // 8)
    quiet_slots = max(1, limit - mover_slots - early_slots)
    selected = movers[:mover_slots] + early[:early_slots] + quiet[:quiet_slots]
    # Fill unused slots, preserving each symbol only once.
    selected += [q for q in movers[mover_slots:] + early[early_slots:] + quiet[quiet_slots:]
                 if q not in selected][:max(0, limit - len(selected))]
    return [str(q.symbol) for q in selected[:limit]]
