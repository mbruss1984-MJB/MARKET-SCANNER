"""Fast-signal detection and forward-price validation. Read-only."""
import sqlite3
from datetime import datetime, timezone

class FastTracker:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS fast_signals (
            id INTEGER PRIMARY KEY, symbol TEXT NOT NULL,
            detected_utc TEXT NOT NULL, detection_price REAL NOT NULL,
            latest_price REAL NOT NULL, peak_price REAL NOT NULL,
            trough_price REAL NOT NULL, peak_gain_pct REAL NOT NULL DEFAULT 0,
            max_drawdown_pct REAL NOT NULL DEFAULT 0,
            return_1m_pct REAL, return_5m_pct REAL, return_15m_pct REAL,
            last_observed_utc TEXT NOT NULL)""")
        self.db.commit()

    def detect(self, symbol, price, now=None):
        if price <= 0: return
        now = now or datetime.now(timezone.utc)
        # One event per symbol per 15 minutes; prevent repeated signal spam.
        row = self.db.execute("SELECT detected_utc FROM fast_signals WHERE symbol=? ORDER BY id DESC LIMIT 1", (symbol,)).fetchone()
        if row and (now - datetime.fromisoformat(row["detected_utc"])).total_seconds() < 900:
            return
        stamp = now.isoformat()
        self.db.execute("""INSERT INTO fast_signals
            (symbol,detected_utc,detection_price,latest_price,peak_price,trough_price,last_observed_utc)
            VALUES (?,?,?,?,?,?,?)""", (symbol,stamp,price,price,price,price,stamp))
        self.db.commit()

    def observe(self, symbol, price, now=None):
        if price <= 0: return
        now = now or datetime.now(timezone.utc)
        rows = self.db.execute("SELECT * FROM fast_signals WHERE symbol=? AND detected_utc>=?",
            (symbol, datetime.fromtimestamp(now.timestamp()-1800, timezone.utc).isoformat())).fetchall()
        for row in rows:
            elapsed = (now - datetime.fromisoformat(row["detected_utc"])).total_seconds()
            if elapsed < 0: continue
            base = row["detection_price"]
            gain = 100*(price/base-1)
            peak = max(row["peak_price"],price)
            trough = min(row["trough_price"],price)
            fields = {"latest_price":price,"peak_price":peak,"trough_price":trough,
                "peak_gain_pct":100*(peak/base-1),"max_drawdown_pct":100*(trough/base-1),
                "last_observed_utc":now.isoformat()}
            for seconds,key in ((60,"return_1m_pct"),(300,"return_5m_pct"),(900,"return_15m_pct")):
                if elapsed >= seconds and row[key] is None:
                    fields[key]=gain
            self.db.execute("UPDATE fast_signals SET "+", ".join(k+"=?" for k in fields)+" WHERE id=?",
                (*fields.values(),row["id"]))
        self.db.commit()

    def recent(self, limit=100):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM fast_signals ORDER BY id DESC LIMIT ?",(limit,)).fetchall()]

    def summary(self):
        row=self.db.execute("""SELECT COUNT(*) AS n,
            SUM(CASE WHEN return_1m_pct IS NOT NULL THEN 1 ELSE 0 END) AS measured_1m,
            SUM(CASE WHEN return_5m_pct IS NOT NULL THEN 1 ELSE 0 END) AS measured_5m,
            SUM(CASE WHEN return_15m_pct IS NOT NULL THEN 1 ELSE 0 END) AS measured_15m
            FROM fast_signals""").fetchone()
        return dict(row)
