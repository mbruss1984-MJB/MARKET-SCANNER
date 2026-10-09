"""Public exchange-symbol directory ingestion. Read-only, no paid API.

This provides broad *listed-symbol discovery*, not an exchange-wide real-time
screener. Quotes are sampled in rotating batches; coverage may take hours.
"""
import csv
import io
import os
import re
from urllib.request import Request, urlopen

SOURCES = (
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
)
PATTERN = re.compile(r"^[A-Z]{1,5}$")

def download_universe(timeout=12):
    symbols = []
    for url in SOURCES:
        request = Request(url, headers={"User-Agent": "MarketScanner/0.3 research read-only"})
        with urlopen(request, timeout=timeout) as response:
            text = response.read(2_000_000).decode("utf-8-sig", "replace")
        rows = csv.DictReader(io.StringIO(text), delimiter="|")
        for row in rows:
            ticker = (row.get("Symbol") or row.get("ACT Symbol") or "").strip().upper()
            if not PATTERN.fullmatch(ticker):
                continue
            if row.get("Test Issue", "N").strip() == "Y":
                continue
            if row.get("ETF", "N").strip() == "Y":
                continue
            name = (row.get("Security Name") or row.get("Company Name") or "").upper()
            if any(term in name for term in (" WARRANT", " WTS ", " RIGHTS", " UNIT ", " DEPOSITARY", " PREFERRED")):
                continue
            symbols.append(ticker + ".US")
    if len(set(symbols)) < 1000:
        raise ValueError("Symbol directory unexpectedly small")
    return list(dict.fromkeys(symbols))

def configured_universe():
    raw = os.getenv("UNIVERSE_SYMBOLS") or os.getenv("SYMBOLS", "WFF.US,VEEA.US,OFAL.US,MRNA.US")
    fallback = list(dict.fromkeys(s.strip().upper() for s in raw.split(",") if s.strip()))
    if os.getenv("BROAD_UNIVERSE", "true").lower() not in ("true", "1", "yes"):
        return fallback, "configured"
    try:
        return download_universe(), "nasdaq_trader_directory"
    except Exception:
        return fallback, "configured_fallback"

def screen_snapshot(snapshot, *, min_price=0.0, min_turnover=100000):
    try:
        last = float(snapshot.last_done)
        volume = float(snapshot.volume)
        turnover = float(snapshot.turnover)
        return last > min_price and volume > 0 and turnover >= min_turnover
    except (AttributeError, TypeError, ValueError):
        return False
