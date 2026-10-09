"""Read-only market-data scanner prototype. No brokerage order methods."""
import logging
import os
import threading
import time
from datetime import datetime, timezone
from fastapi import FastAPI
from scoring import Bar, analyze
from tracking import SignalTracker
from discovery import configured_universe, screen_snapshot
from pipeline import select_candidates, discover_initial, quote_strength

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("ignition")
app = FastAPI(title="Longbridge Ignition Scanner", version="0.8.0")
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
    from longport.openapi import AdjustType, Period
    bars = list(ctx.candlesticks(symbol, period, count, AdjustType.NoAdjust))
    bars.sort(key=lambda b: b.timestamp)
    now = datetime.now(timezone.utc)
    minutes = 1 if period == Period.Min_1 else 5
    completed = []
    last_bar_utc = None
    for b in bars:
        ts = b.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if (now - ts.astimezone(timezone.utc)).total_seconds() >= minutes * 60:
            completed.append(bar_from_sdk(b))
            last_bar_utc = ts.astimezone(timezone.utc).isoformat()
    return completed, last_bar_utc

def worker():
    symbols, universe_source = configured_universe()
    update(symbols=symbols[:20], universe_size=len(symbols), universe_source=universe_source, mode="rotating_universe_polling", alerts_enabled=False)
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
    tracker = SignalTracker()
    cursor = 0
    last_candidates = {}
    quote_history = {}
    priority = []
    hot_watch = []
    watch_age = {}
    cycle = 0
    while True:
        signals = {}
        # Rotate through the configured universe to avoid an unbounded API burst.
        batch_size = max(1, min(100, int(os.getenv("BATCH_SIZE", "80"))))
        batch = [symbols[(cursor + i) % len(symbols)] for i in range(min(batch_size, len(symbols)))] if symbols else []
        cursor = (cursor + len(batch)) % len(symbols) if symbols else 0
        # Revisit previously active names every minute while sweeping the rest.
        revisit = hot_watch[:20]
        quote_batch = list(dict.fromkeys(revisit + batch))[:100]
        cycle += 1
        try:
            snapshots = ctx.quote(quote_batch) if quote_batch else []
            # Stage 1: cheap quote snapshots; candle requests are only for
            # candidates showing *new* volume and positive price acceleration.
            ranked = select_candidates(snapshots, quote_history, screen_snapshot, limit=12)
            discovered = discover_initial(snapshots, screen_snapshot, limit=16)
            priority = list(dict.fromkeys([s for _, s, _ in ranked] + discovered))[:24]
            screened = {str(s.symbol) for s in snapshots if screen_snapshot(s)}
            # Keep existing active names, plus promising first-seen movers.
            # Rank on price strength, not turnover alone.
            pool = {str(s.symbol): s for s in snapshots if screen_snapshot(s)}
            for symbol in discovered + [s for _, s, _ in ranked]:
                watch_age[symbol] = cycle
            # Retain active movers for at most 10 cycles without fresh qualification.
            watch_age = {s: age for s, age in watch_age.items() if cycle - age <= 10}
            hot_watch = list(dict.fromkeys([s for _, s, _ in ranked] + discovered + list(watch_age)))[:20]
        except Exception as exc:
            log.warning("Quote pre-screen unavailable: %s", type(exc).__name__)
            ranked, screened, discovered = [], set(), []
            update(last_quote_error=type(exc).__name__)
        # Stage 2: recheck high-priority names, then fetch completed candles.
        # Keep a small bootstrap watchlist active even before two observations.
        bootstrap = [s.strip().upper() for s in os.getenv("SYMBOLS", "WFF.US,VEEA.US,OFAL.US,MRNA.US").split(",") if s.strip()]
        targets = list(dict.fromkeys([s for _,s,_ in ranked][:8] + discovered[:8] + [s for s in bootstrap if s in screened]))[:16]
        for symbol in targets:
            try:
                one, bar_utc = fetch_completed(ctx, symbol, Period.Min_1, 15)
                five, _ = fetch_completed(ctx, symbol, Period.Min_5, 10)
                signals[symbol] = analyze(one, five)
                if one:
                    tracker.observe(symbol, signals[symbol], one[-1].close, bar_utc)
            except Exception as exc:
                log.warning("Market-data fetch failed for %s: %s", symbol, type(exc).__name__)
                signals[symbol] = {"state": "DATA_ERROR", "error_type": type(exc).__name__}
        tracker.expire()
        # Current candidates expire when no longer seen; avoid a permanently stale count.
        last_candidates = {s: (v, cycle) for s, (v, age) in last_candidates.items() if cycle - age <= 10}
        last_candidates.update({s: (v, cycle) for s, v in signals.items() if v.get("state") in ("EARLY_STARTER_CANDIDATE", "CONFIRMED_STARTER")})
        if len(last_candidates) > 100:
            last_candidates = dict(list(last_candidates.items())[-100:])
        update(signal_lifecycle=tracker.summary(), signal_history=tracker.recent(30), signal_storage="ephemeral_sqlite", signals=signals, last_poll_utc=datetime.now(timezone.utc).isoformat(), scanned_batch=batch, universe_size=len(symbols), candidate_count=len(last_candidates), recent_candidates={s: v for s, (v, age) in last_candidates.items()}, quote_candidates=[{"symbol": s, "score": round(score,2), **details} for score,s,details in ranked], candle_targets=targets, quote_history_size=len(quote_history), discovered_day_movers=discovered, hot_watch=hot_watch, quote_batch_size=len(quote_batch), sweep_progress_pct=round(100*cursor/len(symbols),1) if symbols else 0, cycle=cycle)
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
