"""Read-only market-data scanner prototype. No brokerage order methods."""
import logging
from contextlib import asynccontextmanager
import random
import csv
import io
from fastapi.responses import Response
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from fastapi import FastAPI
from scoring import Bar, analyze
from tracking import SignalTracker
from fast_tracking import FastTracker
from discovery import configured_universe, screen_snapshot
from pipeline import select_candidates, discover_initial, quote_strength
from earnings import EarningsCalendar
from scanner_mcp import mcp

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("ignition")
@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        threading.Thread(target=worker, daemon=True, name="market-scanner").start()
        threading.Thread(target=hot_worker, daemon=True, name="hot-ignition-loop").start()
        yield

app = FastAPI(title="Longbridge Ignition Scanner", version="1.5.0", lifespan=lifespan)
app.mount("/mcp", mcp.streamable_http_app())
# ChatGPT discovery can send a JSON-RPC payload with an octet-stream MIME type.
# Normalize only validated JSON-RPC requests to the MCP mount, never arbitrary binary.
class MCPJsonContentTypeCompatibility:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope.get("method") != "POST"
                or scope.get("path") not in ("/mcp", "/mcp/")):
            return await self.app(scope, receive, send)
        headers = list(scope.get("headers", []))
        mime = next((v.split(b";", 1)[0].strip().lower()
                     for k, v in headers if k.lower() == b"content-type"), b"")
        if mime != b"application/octet-stream":
            return await self.app(scope, receive, send)

        import json
        chunks = []
        size = 0
        while True:
            event = await receive()
            if event["type"] != "http.request":
                return await self.app(scope, receive, send)
            chunk = event.get("body", b"")
            size += len(chunk)
            if size > 65536:
                await send({"type": "http.response.start", "status": 413, "headers": []})
                await send({"type": "http.response.body", "body": b"Payload too large"})
                return
            chunks.append(chunk)
            if not event.get("more_body", False):
                break
        body = b"".join(chunks)
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
                raise ValueError("Not a JSON-RPC request")
        except (ValueError, UnicodeDecodeError) as exc:
            log.warning("MCP discovery rejected: content_type=%s body_bytes=%d parse_error=%s", mime.decode("ascii", "replace"), len(body), type(exc).__name__)
            await send({"type": "http.response.start", "status": 415, "headers": []})
            await send({"type": "http.response.body", "body": b"Expected MCP JSON-RPC"})
            return
        scope = dict(scope)
        scope["headers"] = [(k, b"application/json" if k.lower() == b"content-type" else v) for k, v in headers]
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}
        return await self.app(scope, replay, send)

app.add_middleware(MCPJsonContentTypeCompatibility)

# OAuth 2.0 protected-resource discovery and JWT verification.
# Configure MCP_OAUTH_ISSUER, MCP_OAUTH_AUDIENCE and MCP_OAUTH_JWKS_URL
# in Render. Until configured, MCP access fails closed; scanner routes remain live.
from fastapi.responses import JSONResponse
from urllib.parse import urlparse
import jwt
from jwt import PyJWKClient

MCP_PUBLIC_URL = "https://longbridge-ignition-scanner.onrender.com/mcp/"
MCP_OAUTH_ISSUER = os.getenv("MCP_OAUTH_ISSUER", "").strip()  # Preserve Auth0 issuer trailing slash exactly
MCP_OAUTH_AUDIENCE = os.getenv("MCP_OAUTH_AUDIENCE", "")
MCP_OAUTH_JWKS_URL = os.getenv("MCP_OAUTH_JWKS_URL", "")
_mcp_jwks = PyJWKClient(MCP_OAUTH_JWKS_URL, cache_jwk_set=True, lifespan=300) if MCP_OAUTH_JWKS_URL else None

@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/mcp")
@app.get("/mcp/.well-known/oauth-protected-resource")
def mcp_protected_resource_metadata():
    if not MCP_OAUTH_ISSUER:
        return JSONResponse({"error": "OAuth provider not configured"}, status_code=503)
    return {
        "resource": MCP_PUBLIC_URL,
        "authorization_servers": [MCP_OAUTH_ISSUER],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["scanner:read"],
    }

class MCPBearerAuth:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") not in ("/mcp", "/mcp/"):
            return await self.app(scope, receive, send)
        async def reject(status, message):
            import json
            payload = json.dumps({"error": message}).encode()
            headers = [(b"content-type", b"application/json")]
            if status == 401:
                headers.append((b"www-authenticate", ('Bearer realm="Market Scanner", resource_metadata="https://longbridge-ignition-scanner.onrender.com/.well-known/oauth-protected-resource", scope="scanner:read"').encode()))
            await send({"type": "http.response.start", "status": status, "headers": headers})
            await send({"type": "http.response.body", "body": payload})
        if not (MCP_OAUTH_ISSUER and MCP_OAUTH_AUDIENCE and _mcp_jwks):
            return await reject(503, "OAuth provider not configured")
        authorization = next((v.decode("ascii", "replace") for k, v in scope.get("headers", []) if k.lower() == b"authorization"), "")
        if not authorization.startswith("Bearer "):
            log.warning("MCP OAuth challenge: method=%s path=%s bearer_present=false content_type=%s origin_present=%s",
                        scope.get("method"), scope.get("path"),
                        next((v.decode("ascii", "replace") for k, v in scope.get("headers", []) if k.lower() == b"content-type"), ""),
                        any(k.lower() == b"origin" for k, v in scope.get("headers", [])))
            return await reject(401, "Bearer token required")
        try:
            token = authorization[7:]
            key = _mcp_jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=MCP_OAUTH_AUDIENCE, issuer=MCP_OAUTH_ISSUER, options={"require": ["exp", "iss", "aud"]})
            scopes = set(claims.get("scope", "").split()) | set(claims.get("permissions", []))
            if "scanner:read" not in scopes:
                return await reject(403, "Missing scanner:read scope")
        except (jwt.PyJWTError, ValueError, KeyError):
            return await reject(401, "Invalid bearer token")
        return await self.app(scope, receive, send)

app.add_middleware(MCPBearerAuth)


lock = threading.Lock()
tracker_lock = threading.Lock()
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
    timestamps = []
    for b in bars:
        ts = b.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if (now - ts.astimezone(timezone.utc)).total_seconds() >= minutes * 60:
            completed.append(bar_from_sdk(b))
            timestamps.append(ts.astimezone(timezone.utc))
            last_bar_utc = ts.astimezone(timezone.utc).isoformat()
    # Do not infer fresh ignition from yesterday or gaps between sessions.
    if not timestamps or (now - timestamps[-1]).total_seconds() > minutes * 180:
        return [], None
    start = len(timestamps) - 1
    while start > 0 and (timestamps[start] - timestamps[start-1]).total_seconds() == minutes * 60:
        start -= 1
    return completed[start:], last_bar_utc

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
    app.state.signal_tracker = tracker
    earnings = EarningsCalendar()
    app.state.earnings_calendar = earnings
    # Shuffle sweep order to avoid systematically discovering A-tickers first.
    # This improves fairness, not the total time required for a full sweep.
    rng = random.Random()
    rng.shuffle(symbols)
    cursor = 0
    last_candidates = {}
    quote_history = {}
    priority = []
    hot_watch = []
    watch_age = {}
    cycle = 0
    logged = {}
    while True:
        # At most one external calendar request every 12 hours; no network
        # traffic when the optional key is absent. Failure cannot halt scanning.
        earnings.refresh_if_due()
        signals = {}
        batch_size = max(1, min(100, int(os.getenv("BATCH_SIZE", "80"))))
        discovery_batches = max(1, min(4, int(os.getenv("DISCOVERY_BATCHES", "3"))))
        batch = []
        for _ in range(discovery_batches):
            if not symbols:
                break
            chunk = symbols[cursor:cursor + batch_size]
            batch.extend(chunk)
            cursor += len(chunk)
            if cursor >= len(symbols):
                cursor = 0
                rng.shuffle(symbols)
        revisit = hot_watch[:20]
        quote_batch = list(dict.fromkeys(revisit + batch))
        cycle += 1
        try:
            snapshots = []
            for offset in range(0, len(quote_batch), 100):
                snapshots.extend(ctx.quote(quote_batch[offset:offset + 100]))
                if offset + 100 < len(quote_batch):
                    time.sleep(0.4)
            # Stage 1: cheap quote snapshots; candle requests are only for
            # candidates showing *new* volume and positive price acceleration.
            ranked = select_candidates(snapshots, quote_history, screen_snapshot,
                                       limit=12, catalyst_bonus=earnings.bonus)
            for _, symbol, details in ranked:
                event = earnings.get(symbol)
                if event:
                    details["earnings"] = event
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
            ranked, screened, discovered, pool = [], set(), [], {}
            update(last_quote_error=type(exc).__name__)
        # Stage 2: recheck high-priority names, then fetch completed candles.
        # Keep a small bootstrap watchlist active even before two observations.
        bootstrap = [s.strip().upper() for s in os.getenv("SYMBOLS", "WFF.US,VEEA.US,OFAL.US,MRNA.US").split(",") if s.strip()]
        targets = list(dict.fromkeys([s for _,s,_ in ranked][:8] + discovered[:8] + discovered[-4:] + hot_watch[:8] + [s for s in bootstrap if s in screened]))[:24]
        for symbol in targets:
            try:
                one, bar_utc = fetch_completed(ctx, symbol, Period.Min_1, 20)
                five, _ = fetch_completed(ctx, symbol, Period.Min_5, 10)
                signals[symbol] = analyze(one, five)
                snap = pool.get(symbol)
                if snap is not None:
                    previous = float(snap.prev_close)
                    day_gain = 100 * (float(snap.last_done) / previous - 1) if previous > 0 else None
                    signals[symbol]["session_gain_pct"] = day_gain
                    if day_gain is not None and day_gain >= 15:
                        signals[symbol]["setup_type"] = "continuation"
                signals[symbol]["bar_utc"] = bar_utc
                event = earnings.get(symbol)
                if event:
                    signals[symbol]["earnings"] = event
                if one:
                    with tracker_lock:
                        tracker.observe(symbol, signals[symbol], one[-1].close, bar_utc)
            except Exception as exc:
                log.warning("Market-data fetch failed for %s: %s", symbol, type(exc).__name__)
                signals[symbol] = {"state": "DATA_ERROR", "error_type": type(exc).__name__}
        with tracker_lock:
            tracker.expire()
        # Current candidates expire when no longer seen; avoid a permanently stale count.
        last_candidates = {s: (v, cycle) for s, (v, age) in last_candidates.items() if cycle - age <= 10}
        last_candidates.update({s: (v, cycle) for s, v in signals.items() if v.get("state") in ("PRE_IGNITION", "EARLY_STARTER_CANDIDATE", "CONFIRMED_STARTER")})
        if len(last_candidates) > 100:
            last_candidates = dict(list(last_candidates.items())[-100:])
        with tracker_lock:
            lifecycle_snapshot, history_snapshot = tracker.summary(), tracker.recent(30)
        update(earnings_calendar=earnings.status(), discovery_mode="multi_batch_quote_discovery", discovery_batches=discovery_batches, screener_candidates=[], screener_candidate_count=0, screener_last_utc=None, screener_error=None, signal_lifecycle=lifecycle_snapshot, signal_history=history_snapshot, signal_storage="ephemeral_sqlite", signals=signals, last_poll_utc=datetime.now(timezone.utc).isoformat(), scanned_batch=batch, universe_size=len(symbols), candidate_count=len(last_candidates), recent_candidates={s: v for s, (v, age) in last_candidates.items()}, quote_candidates=[{"symbol": s, "score": round(score,2), **details} for score,s,details in ranked], candle_targets=targets, quote_history_size=len(quote_history), discovered_day_movers=discovered, hot_watch=hot_watch, quote_batch_size=len(quote_batch), sweep_progress_pct=round(100*cursor/len(symbols),1) if symbols else 0, cycle=cycle)
        log.info("SCANNER HEARTBEAT cycle=%s targets=%s universe=%s progress=%s",
                 cycle, len(targets), len(symbols), round(100*cursor/len(symbols), 1) if symbols else 0)
        for symbol, result in signals.items():
            signature = (result.get("state"), result.get("bar_utc"))
            if result.get("state") in ("PRE_IGNITION", "EARLY_STARTER_CANDIDATE", "CONFIRMED_STARTER") and logged.get(symbol) != signature:
                log.warning("PROVISIONAL IGNITION %s %s", symbol, result)
            logged[symbol] = signature
        time.sleep(max(60, int(os.getenv("POLL_SECONDS", "60"))))

def hot_worker():
    """Independent, bounded 15-second hot-watch loop; no trading or alerts."""
    if not all(os.getenv(k) for k in ("LONGPORT_APP_KEY", "LONGPORT_APP_SECRET", "LONGPORT_ACCESS_TOKEN")):
        return
    try:
        from longport.openapi import Config, QuoteContext
        ctx = QuoteContext(Config.from_env())
    except Exception as exc:
        log.warning("Hot loop connection failed: %s", type(exc).__name__)
        update(hot_loop_error=type(exc).__name__)
        return
    fast_tracker = FastTracker(os.getenv("SIGNAL_DB_PATH", "/tmp/ignition_signals.sqlite3"))
    app.state.fast_tracker = fast_tracker
    history = {}
    streaks = {}
    fast_candidates = {}
    buildup_candidates = {}
    interval = max(10, min(60, int(os.getenv("HOT_POLL_SECONDS", "15"))))
    while True:
        started = time.monotonic()
        with lock:
            symbols = list(state.get("hot_watch", []))[:30]
        if symbols:
            try:
                snapshots = ctx.quote(symbols)
                now = time.monotonic()
                results = {}
                for snap in snapshots:
                    symbol = str(snap.symbol)
                    price, volume = float(snap.last_done), float(snap.volume)
                    fast_tracker.observe(symbol, price)
                    quote_time = snap.timestamp
                    if quote_time.tzinfo is None:
                        quote_time = quote_time.replace(tzinfo=timezone.utc)
                    if abs((datetime.now(timezone.utc) - quote_time).total_seconds()) > 60:
                        history.pop(symbol, None)
                        streaks.pop(symbol, None)
                        continue
                    trail = history.setdefault(symbol, deque(maxlen=40))
                    while trail and now - trail[0][0] > 180:
                        trail.popleft()
                    previous = next((x for x in reversed(trail) if now - x[0] >= 10), None)
                    trail.append((now, price, volume))
                    if previous and previous[1] > 0:
                        seconds = now - previous[0]
                        change = 100 * (price / previous[1] - 1)
                        vol_delta = max(0, volume - previous[2])
                        if volume < previous[2]:
                            trail.clear()
                            streaks[symbol] = 0
                            continue
                        prior_window = next((x for x in reversed(trail) if previous[0] - x[0] >= 10), None)
                        prior_rate = ((previous[2] - prior_window[2]) / (previous[0] - prior_window[0])) if prior_window and previous[2] >= prior_window[2] else 0
                        rate = vol_delta / max(seconds, 1)
                        if prior_rate > 0 and rate >= prior_rate * 1.5 and -0.1 <= change <= 0.25 and vol_delta * price >= 10000:
                            buildup_candidates[symbol] = {"state": "FAST_BUILDUP_WATCH", "detected_utc": datetime.now(timezone.utc).isoformat(), "price": price, "volume_rate_ratio": round(rate/prior_rate, 2), "provisional": True, "executable": False}
                            calendar = getattr(app.state, "earnings_calendar", None)
                            event = calendar.get(symbol) if calendar else None
                            if event:
                                buildup_candidates[symbol]["earnings"] = event
                        momentum_up = change >= 0.25 and vol_delta >= 1000
                        streaks[symbol] = streaks.get(symbol, 0) + 1 if momentum_up else 0
                        if streaks[symbol] == 2:
                            fast_tracker.detect(symbol, price)
                        if streaks[symbol] >= 2:
                            fast_candidates[symbol] = {"state": "FAST_MOMENTUM_CANDIDATE", "detected_utc": datetime.now(timezone.utc).isoformat(), "price": price, "price_change_pct": round(change, 3), "volume_delta": vol_delta, "provisional": True, "executable": False}
                            calendar = getattr(app.state, "earnings_calendar", None)
                            event = calendar.get(symbol) if calendar else None
                            if event:
                                fast_candidates[symbol]["earnings"] = event
                        results[symbol] = {"price_change_pct": round(change, 3),
                                           "volume_delta": vol_delta,
                                           "window_seconds": round(seconds, 1),
                                           "momentum_up": momentum_up,
                                           "consecutive_windows": streaks[symbol],
                                           "provisional": True, "executable": False}
                history = {s: h for s, h in history.items() if s in symbols}
                streaks = {s: n for s, n in streaks.items() if s in symbols}
                fast_candidates = {s: v for s, v in fast_candidates.items() if s in symbols and (datetime.now(timezone.utc) - datetime.fromisoformat(v["detected_utc"])).total_seconds() < 120 and streaks.get(s, 0) >= 2}
                buildup_candidates = {s: v for s, v in buildup_candidates.items() if s in symbols and (datetime.now(timezone.utc)-datetime.fromisoformat(v["detected_utc"])).total_seconds() < 60}
                update(buildup_candidates=buildup_candidates.copy(), hot_loop_last_utc=datetime.now(timezone.utc).isoformat(),
                       hot_loop_symbols=len(symbols), hot_loop_metrics=results, fast_candidates=fast_candidates.copy(),
                       fast_candidate_count=len(fast_candidates), fast_signal_summary=fast_tracker.summary(), fast_signal_history=fast_tracker.recent(30), hot_loop_error=None, hot_poll_seconds=interval)
            except Exception as exc:
                log.warning("Hot loop quote failed: %s", type(exc).__name__)
                update(hot_loop_error=type(exc).__name__, hot_poll_seconds=interval)
        time.sleep(max(1, interval - (time.monotonic() - started)))

@app.get("/")
def root():
    return {"name": "Longbridge Ignition Scanner", "status_endpoint": "/status", "orders": "disabled"}

@app.get("/health")
def health():
    with lock:
        stamp = state.get("last_poll_utc")
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds() if stamp else None
        return {"service": "up", "scanner_fresh": age is not None and age <= 180,
                "poll_age_seconds": age, "connected": state.get("connected"),
                "error": state.get("error")}

@app.get("/status")
def status():
    with lock:
        return dict(state)

@app.get("/earnings")
def earnings_context():
    """Read-only earnings intelligence for the active hot-watch subset."""
    calendar = getattr(app.state, "earnings_calendar", None)
    if calendar is None:
        return {"status": {"status": "initializing"}, "watchlist": {}}
    with lock:
        symbols = list(dict.fromkeys(
            list(state.get("hot_watch", [])) + list(state.get("fast_candidates", {}))
        ))[:30]
    watchlist = {}
    for symbol in symbols:
        event = calendar.get(symbol)
        if event:
            watchlist[symbol] = event
    return {"status": calendar.status(), "watchlist": watchlist}


@app.get("/signals.csv")
def signal_export():
    tracker = getattr(app.state, "signal_tracker", None)
    if tracker is None:
        return Response("tracker not initialized", status_code=503)
    rows = tracker.recent(100000)
    output = io.StringIO()
    fields = ["id","symbol","detected_utc","last_seen_utc","detection_price","last_price","peak_price","trough_price","peak_gain_pct","max_drawdown_pct","lifecycle","reason","initial_state","last_state","last_bar_utc","observation_count"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=ignition_signals.csv"})

@app.get("/fast-signals.csv")
def fast_signal_export():
    tracker = getattr(app.state, "fast_tracker", None)
    if tracker is None:
        return Response("fast tracker not initialized", status_code=503)
    rows = tracker.recent(100000)
    output = io.StringIO()
    fields = ["id","symbol","detected_utc","detection_price","latest_price","peak_price","trough_price","peak_gain_pct","max_drawdown_pct","return_1m_pct","return_5m_pct","return_15m_pct","last_observed_utc"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=fast_signals.csv"})


@app.get("/observations")
def observations():
    tracker = getattr(app.state, "signal_tracker", None)
    if tracker is None:
        return JSONResponse({"error": "tracker not initialized"}, status_code=503)
    with tracker_lock:
        return {"storage": "ephemeral_sqlite", "observations": tracker.observations(1000)}
