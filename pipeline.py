"""Two-stage scanner helpers. Quote sweeps precede expensive candle calls."""
from collections import deque
from datetime import datetime, timezone

def select_candidates(snapshots, history, screen, limit=12):
    ranked = []
    for quote in snapshots:
        symbol = str(quote.symbol)
        if not screen(quote):
            continue
        price = float(quote.last_done)
        volume = float(quote.volume)
        turnover = float(quote.turnover)
        prior = history.get(symbol)
        history[symbol] = (price, volume, datetime.now(timezone.utc).timestamp())
        if prior is None:
            continue  # no false acceleration on first observation
        old_price, old_volume, old_time = prior
        elapsed = max(1, datetime.now(timezone.utc).timestamp() - old_time)
        volume_delta = max(0, volume - old_volume)
        price_pct = 100 * (price / old_price - 1) if old_price > 0 else 0
        velocity = volume_delta / elapsed
        score = price_pct * 8 + min(velocity / 100, 20)
        if price_pct > 0.1 and volume_delta > 0:
            ranked.append((score, symbol, {"price_change_since_seen_pct":round(price_pct, 3),
                                          "volume_since_seen":int(volume_delta),
                                          "volume_per_second":round(velocity, 2)}))
    ranked.sort(reverse=True)
    return ranked[:limit]
