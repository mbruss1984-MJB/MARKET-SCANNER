"""Read-only MCP tools for the existing market scanner."""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Market Scanner", stateless_http=True, json_response=True, streamable_http_path="/", host="0.0.0.0", transport_security=None)

@mcp.tool()
def get_scanner_status() -> dict:
    """Current scanner state, connectivity and freshness."""
    from app import state, lock
    with lock:
        return dict(state)

@mcp.tool()
def get_ignition_signals() -> dict:
    """Current scored ignitions and fast momentum candidates."""
    from app import state, lock
    with lock:
        return {key: state.get(key) for key in (
            "connected", "last_poll_utc", "hot_loop_last_utc",
            "signals", "fast_candidates", "hot_watch")}

@mcp.tool()
def get_signal_history(limit: int = 100) -> dict:
    """Recent standard and fast signal history."""
    from app import app
    n = max(1, min(int(limit), 500))
    normal = getattr(app.state, "signal_tracker", None)
    fast = getattr(app.state, "fast_tracker", None)
    return {"signals": normal.recent(n) if normal else [],
            "fast_signals": fast.recent(n) if fast else []}

@mcp.tool()
def get_earnings_watchlist() -> dict:
    """Cached earnings windows for actively monitored symbols; never an earnings beat claim."""
    from app import app, state, lock
    calendar = getattr(app.state, "earnings_calendar", None)
    if calendar is None:
        return {"status": {"status": "initializing"}, "watchlist": {}}
    with lock:
        symbols = list(dict.fromkeys(
            list(state.get("hot_watch", [])) + list(state.get("fast_candidates", {}))
        ))[:30]
    events = {}
    for symbol in symbols:
        event = calendar.get(symbol)
        if event:
            events[symbol] = event
    return {"status": calendar.status(), "watchlist": events}
