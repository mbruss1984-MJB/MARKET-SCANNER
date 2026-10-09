"""Read-only market-data scanner prototype. No brokerage order methods."""
import logging
import os
import threading
import time
from datetime import datetime, timezone
from fastapi import FastAPI
from scoring import Bar, analyze
from discovery import configured_universe, screen_snapshot

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("ignition")
app = FastAPI(title="Longbridge Ignition Scanner", version="0.2.0")
lock = threading.Lock()
state = {"connected": False, "symbols": [], "last_poll_utc": None, "signals": {}, "error": None,
         "mode": "watchlist_polling", "trading_enabled": False}

def update(**kwargs):
    with lock:
        state.update(kwargs)

def bar_from_sdk(x):
    return Bar(open=float(x.open), high=float(x.high), low=float(x.low),
               close=float(x.close), volume=float(x.volume))

def fetch_completed(ctx, symbol, period, count):
    from longport.openapi import AdjustType
    bars = list(ctx.candlesticks(symbol, period, count, AdjustType.NoAdjust))
    bars.sort(key=lambda b: b.timestamp)
    now = datetime.now(timezone.utc)
    minutes = 1 if str(period).endswith("Min_1") else 5
    completed = []
    for b in bars:
        ts = b.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if (now - ts.astimezone(timezone.utc)).total_seconds() >= minutes * 60:
            completed.append(bar_from_sdk(b))
    return completed

def worker():
    symbols = configured_universe()
    update(symbols=symbols)
    if not all(os.getenv(k) for k in ("LONGPORT_APP_KEY", "LONGPORT_APP_SECRET", "LONGPORT_ACCESS_TOKEN")):
        update(error="Missing Longport SDK credentials; scanner is not connected")
        return
    try:
        from longport.openapi import Config, QuoteContext, Period
        config = Config.from_env()
        ctx = QuoteContext(config)
        update(connected=True, error=None)
    except Exception as exc:
        log.exception("Longport connection failed")
        update(error=f"Longport connection failed: {type(exc).__name__}")
        return
    cursor = 0
    while True:
        signals = {}
        # Rotate through the configured universe to avoid an unbounded API burst.
        batch_size = max(1, min(40, int(os.getenv("BATCH_SIZE", "20"))))
        batch = [symbols[(cursor + i) % len(symbols)] for i in range(min(batch_size, len(symbols)))] if symbols else []
        cursor = (cursor + len(batch)) % len(symbols) if symbols else 0
        try:
            snapshots = ctx.quote(batch) if batch else []
            eligible = {str(s.symbol) for s in snapshots if screen_snapshot(s)}
        except Exception as exc:
            log.warning("Quote pre-screen unavailable: %s", type(exc).__name__)
            eligible = set()
        for symbol in batch:
            if symbol not in eligible:
                signals[symbol] = {"state": "FILTERED", "reason": "Missing data, price, volume, or turnover threshold"}
                continue
            try:
                one = fetch_completed(ctx, symbol, Period.Min_1, 15)
                five = fetch_completed(ctx, symbol, Period.Min_5, 10)
                signals[symbol] = analyze(one, five)
            except Exception as exc:
                log.warning("Market-data fetch failed for %s: %s", symbol, type(exc).__name__)
                signals[symbol] = {"state": "DATA_ERROR", "error_type": type(exc).__name__}
        update(signals=signals, last_poll_utc=datetime.now(timezone.utc).isoformat(), scanned_batch=batch, universe_size=len(symbols))
        for symbol, result in signals.items():
            if result.get("state") in ("EARLY_STARTER_CANDIDATE", "CONFIRMED_STARTER"):
                log.warning("PROVISIONAL IGNITION %s %s", symbol, result)
        time.sleep(max(60, int(os.getenv("POLL_SECONDS", "60"))))

@app.on_event("startup")
def start():
    threading.Thread(target=worker, daemon=True, name="market-scanner").start()

@app.get("/")
def root():
    return {"name": "Longbridge Ignition Scanner", "status_endpoint": "/status", "orders": "disabled"}

@app.get("/health")
def health():
    return {"service": "up"}

@app.get("/status")
def status():
    with lock:
        return dict(state)
