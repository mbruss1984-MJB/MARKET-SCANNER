"""Read-only candidate discovery and quote filtering.

Universe must be supplied from a licensed, maintained symbol source.
This module does not claim to enumerate all U.S. listings.
"""
import os
from decimal import Decimal

def configured_universe():
    raw = os.getenv("UNIVERSE_SYMBOLS", "") or os.getenv("SYMBOLS", "")
    return list(dict.fromkeys(s.strip().upper() for s in raw.split(",") if s.strip()))

def screen_snapshot(snapshot, *, min_price=0.25, min_turnover=100000, max_spread_pct=3):
    """Conservative gate; absent required market data means reject."""
    try:
        last = float(snapshot.last_done)
        volume = float(snapshot.volume)
        turnover = float(snapshot.turnover)
        if last < min_price or volume <= 0 or turnover < min_turnover:
            return False
        return True
    except (AttributeError, TypeError, ValueError):
        return False
