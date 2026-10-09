"""Broad US screener discovery. Gracefully falls back to directory rotation."""
import logging
import re

log = logging.getLogger("ignition.screener")
TICKER = re.compile(r"^[A-Z]{1,5}\\.US$")

def extract_symbols(payload, allowed, limit=60):
    """Accept SDK response .data, or decoded JSON dict. Reject non-listed symbols."""
    data = getattr(payload, "data", payload)
    if not isinstance(data, dict):
        return []
    items = data.get("items", [])
    if not isinstance(items, list):
        return []
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = item.get("symbol") or item.get("code") or ""
        if not isinstance(raw, str):
            continue
        symbol = raw.upper().strip()
        if not symbol.endswith(".US"):
            symbol += ".US"
        if TICKER.fullmatch(symbol) and symbol in allowed and symbol not in results:
            results.append(symbol)
        if len(results) >= limit:
            break
    return results

def discover(ctx, allowed, size=100):
    from longport.openapi import ScreenerCondition
    # This is a day-change discovery filter, not a minute-level ignition signal.
    # Real-time 1m/5m validation remains in the quote/candle pipeline.
    response = ctx.screener_search(
        market="US", conditions=[ScreenerCondition("prevchg", min="2")],
        page=0, size=size
    )
    return extract_symbols(response, allowed)
