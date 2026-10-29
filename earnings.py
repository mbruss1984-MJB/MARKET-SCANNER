"""Rate-limited, read-only earnings calendar enrichment (not an execution signal).

Uses a single Alpha Vantage EARNINGS_CALENDAR CSV request per 12 hours when
ALPHA_VANTAGE_API_KEY is configured. The feed supplies expected report dates
and estimates, NOT actual reported EPS, confirmed release status, or sentiment.
A missing/failed/stale feed must never block the momentum scanner.
"""
import csv
import io
import os
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
SOURCE = "alpha_vantage_earnings_calendar"


def _utc(now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(timezone.utc)


def _parse_estimate(value):
    value = str(value or "").strip().replace("$", "").replace(",", "")
    try:
        return float(value)
    except ValueError:
        return None


def parse_calendar_csv(raw, today=None):
    """Return one nearest non-past event per normalized U.S. ticker."""
    today = today or datetime.now(EASTERN).date()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or not {"symbol", "reportDate"}.issubset(reader.fieldnames):
        raise ValueError("Unexpected earnings calendar response")
    events = {}
    for row in reader:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        try:
            report_date = date.fromisoformat(str(row.get("reportDate") or "").strip())
        except ValueError:
            continue
        # Keep the next report in preference to very old events.
        if report_date < today - timedelta(days=1):
            continue
        event = {
            "symbol": symbol,
            "earnings_date": report_date.isoformat(),
            "fiscal_period_ending": row.get("fiscalDateEnding") or None,
            "eps_estimate": _parse_estimate(row.get("estimate")),
            "currency": row.get("currency") or None,
            "release_timing": row.get("timeOfTheDay") or None,
            "source": SOURCE,
            "verification": "scheduled_unverified",
        }
        if symbol not in events or report_date < date.fromisoformat(events[symbol]["earnings_date"]):
            events[symbol] = event
    if not events:
        raise ValueError("Earnings calendar returned no usable events")
    return events


class EarningsCalendar:
    def __init__(self, api_key=None):
        self.api_key = (os.getenv("ALPHA_VANTAGE_API_KEY", "") if api_key is None else api_key).strip()
        self.events = {}
        self.updated_at = None
        self.next_refresh_at = None
        self.last_error = None

    def _fetch(self):
        url = "https://www.alphavantage.co/query?" + urlencode({
            "function": "EARNINGS_CALENDAR", "horizon": "3month", "apikey": self.api_key
        })
        request = Request(url, headers={"User-Agent": "MarketScanner-Earnings/1.0"})
        with urlopen(request, timeout=8) as response:
            return response.read(10_000_000)

    def refresh_if_due(self, now=None, fetcher=None):
        """Fail open; never leak credentials, make per-ticker calls or rapid retries."""
        now = _utc(now)
        if not self.api_key:
            return False
        if self.next_refresh_at is not None and now < self.next_refresh_at:
            return False
        self.next_refresh_at = now + timedelta(hours=12)
        try:
            records = parse_calendar_csv((fetcher or self._fetch)(), today=now.astimezone(EASTERN).date())
            self.events = records
            self.updated_at = now
            self.last_error = None
            return True
        except Exception as exc:
            # Deliberately log error type only, not provider URL (which contains key).
            self.last_error = type(exc).__name__
            return False

    def get(self, symbol, now=None):
        now = _utc(now)
        if not self.updated_at or now - self.updated_at > timedelta(hours=36):
            return None
        lookup = str(symbol).upper().strip()
        if lookup.endswith(".US"):
            lookup = lookup[:-3]
        event = self.events.get(lookup)
        if not event:
            return None
        days = (date.fromisoformat(event["earnings_date"]) - now.astimezone(EASTERN).date()).days
        if days < -1 or days > 30:
            return None
        return {**event, "days_to_earnings": days}

    def bonus(self, symbol, now=None):
        """Priority only, never a stand-alone ignition or trade recommendation."""
        event = self.get(symbol, now)
        return 6.0 if event and -1 <= event["days_to_earnings"] <= 2 else 0.0

    def status(self, now=None):
        now = _utc(now)
        if not self.api_key:
            mode = "disabled_missing_api_key"
        elif not self.updated_at:
            mode = "unavailable"
        elif now - self.updated_at > timedelta(hours=36):
            mode = "stale"
        else:
            mode = "ready"
        return {
            "status": mode, "source": SOURCE, "event_count": len(self.events),
            "last_success_utc": self.updated_at.isoformat() if self.updated_at else None,
            "next_refresh_utc": self.next_refresh_at.isoformat() if self.next_refresh_at else None,
            "error_type": self.last_error,
            "estimates_only": True,
        }
