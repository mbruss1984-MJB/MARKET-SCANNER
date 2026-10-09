"""Read-only momentum discovery from quote snapshots, with no trade execution."""
from datetime import datetime, timezone

def _float(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def quote_strength(quote):
    """Same-day change is a discovery hint, not evidence of fresh ignition."""
    last = _float(getattr(quote, "last_done", 0))
    previous = _float(getattr(quote, "prev_close", 0))
    change = 100 * (last / previous - 1) if previous > 0 else 0
    turnover = _float(getattr(quote, "turnover", 0))
    # Favor meaningful upside and participation; cap large-cap turnover advantage.
    participation = min(10, max(0, turnover / 1_000_000))
    return max(-20, min(30, change)) * 3 + participation

def select_candidates(snapshots, history, screen, limit=12, now=None):
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    ranked = []
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
            continue
        volume_delta = volume - old_volume
        price_pct = 100 * (price / old_price - 1)
        velocity = volume_delta / max(1, elapsed)
        if price_pct >= 0.1 and volume_delta > 0:
            score = price_pct * 8 + min(velocity / 100, 20)
            ranked.append((score, symbol, {"price_change_since_seen_pct":round(price_pct, 3),
                "volume_since_seen":int(volume_delta), "volume_per_second":round(velocity, 2)}))
    ranked.sort(reverse=True)
    return ranked[:limit]

def discover_initial(snapshots, screen, limit=16):
    """Provisional day-mover discovery even on first encounter."""
    candidates = [q for q in snapshots if screen(q) and quote_strength(q) >= 6]
    candidates.sort(key=quote_strength, reverse=True)
    return [str(q.symbol) for q in candidates[:limit]]
