"""Provisional signal lifecycle and forward-performance tracking.

Local SQLite survives process restarts only while the host filesystem persists.
Render Free storage is ephemeral; export data for durable validation.
"""
import os
import sqlite3
from datetime import datetime, timezone

ACTIVE = ("EARLY_STARTER_CANDIDATE", "CONFIRMED_STARTER")

class SignalTracker:
    def __init__(self, path=None):
        self.path = path or os.getenv("SIGNAL_DB_PATH", "/tmp/ignition_signals.sqlite3")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY, symbol TEXT NOT NULL,
            detected_utc TEXT NOT NULL, last_seen_utc TEXT NOT NULL,
            detection_price REAL NOT NULL, last_price REAL NOT NULL,
            peak_price REAL NOT NULL, trough_price REAL NOT NULL,
            peak_gain_pct REAL NOT NULL DEFAULT 0,
            max_drawdown_pct REAL NOT NULL DEFAULT 0,
            lifecycle TEXT NOT NULL, reason TEXT NOT NULL,
            initial_state TEXT NOT NULL, last_state TEXT NOT NULL,
            last_bar_utc TEXT, observation_count INTEGER NOT NULL DEFAULT 1
        )""")
        self.db.commit()

    def observe(self, symbol, signal, price, bar_utc, now=None):
        now = now or datetime.now(timezone.utc)
        stamp = now.isoformat()
        state = signal.get("state", "NO_SIGNAL")
        if not price or price <= 0:
            return
        row = self.db.execute(
            "SELECT * FROM signals WHERE symbol=? AND lifecycle='ACTIVE' ORDER BY id DESC LIMIT 1",
            (symbol,)).fetchone()
        # Repeated completed bars are not new evidence of fresh ignition.
        fresh = bool(bar_utc) and (row is None or row["last_bar_utc"] != bar_utc)
        if row is None:
            if state not in ACTIVE or not fresh:
                return
            self.db.execute("""INSERT INTO signals
                (symbol,detected_utc,last_seen_utc,detection_price,last_price,
                 peak_price,trough_price,lifecycle,reason,initial_state,last_state,last_bar_utc)
                VALUES (?,?,?,?,?,?,?,'ACTIVE','fresh signal',?,?,?)""",
                (symbol, stamp, stamp, price, price, price, price, state, state, bar_utc))
        else:
            peak = max(row["peak_price"], price)
            trough = min(row["trough_price"], price)
            gain = 100 * (peak / row["detection_price"] - 1)
            drawdown = 100 * (trough / row["detection_price"] - 1)
            lifecycle = "ACTIVE" if state in ACTIVE and fresh else "INVALIDATED" if fresh else "ACTIVE"
            reason = "signal no longer qualifies" if lifecycle == "INVALIDATED" else "fresh signal"
            self.db.execute("""UPDATE signals SET last_seen_utc=?,last_price=?,
                peak_price=?,trough_price=?,peak_gain_pct=?,max_drawdown_pct=?,
                lifecycle=?,reason=?,last_state=?,last_bar_utc=?,observation_count=?
                WHERE id=?""", (stamp,price,peak,trough,gain,drawdown,lifecycle,reason,
                state,bar_utc if fresh else row["last_bar_utc"],
                row["observation_count"] + int(fresh),row["id"]))
        self.db.commit()

    def expire(self, now=None, minutes=10):
        now = now or datetime.now(timezone.utc)
        for row in self.db.execute("SELECT id,last_seen_utc FROM signals WHERE lifecycle='ACTIVE'").fetchall():
            seen = datetime.fromisoformat(row["last_seen_utc"])
            if (now - seen).total_seconds() > minutes * 60:
                self.db.execute("UPDATE signals SET lifecycle='EXPIRED',reason='not reobserved within window' WHERE id=?", (row["id"],))
        self.db.commit()

    def recent(self, limit=100):
        rows = self.db.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def summary(self):
        rows = self.db.execute("SELECT lifecycle,COUNT(*) AS n FROM signals GROUP BY lifecycle").fetchall()
        return {r["lifecycle"]: r["n"] for r in rows}
