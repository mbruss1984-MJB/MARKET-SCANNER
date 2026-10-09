"""Read-only market-data scanner prototype. No brokerage order methods."""
import logging
import os
import threading
import time
from datetime import datetime, timezone
from fastapi import FastAPI
from scoring import Bar, analyze

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("ignition")
app = FastAPI(title="Longbridge Ignition Scanner", version="0.1.0")
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
    symbols = [s.strip().upper() for s in os.getenv("SYMBOLS", "WFF.US,VEEA.US,OFAL.US,MRNA.US").split(",") if s.strip()]
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
    while True:
        signals = {}
        for symbol in symbols:
            try:
                one = fetch_completed(ctx, symbol, Period.Min_1, 15)
                five = fetch_completed(ctx, symbol, Period.Min_5, 10)
                signals[symbol] = analyze(one, five)
            except Exception as exc:
                log.warning("Market-data fetch failed for %s: %s", symbol, type(exc).__name__)
                signals[symbol] = {"state": "DATA_ERROR", "error_type": type(exc).__name__}
        update(signals=signals, last_poll_utc=datetime.now(timezone.utc).isoformat())
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
