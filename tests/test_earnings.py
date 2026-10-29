from datetime import datetime, timedelta, timezone
from earnings import EarningsCalendar, parse_calendar_csv

NOW = datetime(2026, 10, 28, 18, tzinfo=timezone.utc)
CSV = ("symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\n"
       "TEST,Test Corp,2026-10-29,2026-09-30,0.25,USD,After Market Close\n"
       "FAR,Far Corp,2026-11-19,2026-09-30,1.25,USD,\n")


def test_parses_and_normalizes_longbridge_us_symbols():
    calendar = EarningsCalendar(api_key="test")
    assert calendar.refresh_if_due(now=NOW, fetcher=lambda: CSV)
    event = calendar.get("TEST.US", now=NOW)
    assert event["eps_estimate"] == 0.25
    assert event["days_to_earnings"] == 1
    assert event["verification"] == "scheduled_unverified"
    assert calendar.bonus("TEST.US", now=NOW) == 6.0
    assert calendar.bonus("FAR.US", now=NOW) == 0.0


def test_missing_key_means_no_external_calls():
    calendar = EarningsCalendar(api_key="")
    assert not calendar.refresh_if_due(now=NOW, fetcher=lambda: (_ for _ in ()).throw(AssertionError()))
    assert calendar.status(now=NOW)["status"] == "disabled_missing_api_key"


def test_cached_refresh_and_stale_guard():
    calendar = EarningsCalendar(api_key="test")
    calls = []
    def fetch():
        calls.append(1)
        return CSV
    assert calendar.refresh_if_due(now=NOW, fetcher=fetch)
    assert not calendar.refresh_if_due(now=NOW + timedelta(hours=1), fetcher=fetch)
    assert len(calls) == 1
    assert calendar.get("TEST.US", now=NOW + timedelta(hours=37)) is None
    assert calendar.bonus("TEST.US", now=NOW + timedelta(hours=37)) == 0


def test_provider_failure_does_not_crash_or_invent_earnings():
    calendar = EarningsCalendar(api_key="test")
    assert not calendar.refresh_if_due(now=NOW, fetcher=lambda: '{"Note": "rate limit"}')
    assert calendar.get("TEST.US", now=NOW) is None
    assert calendar.status(now=NOW)["error_type"] == "ValueError"


def test_bad_rows_are_rejected_and_never_describe_reported_results():
    rows = parse_calendar_csv("symbol,reportDate,estimate\nTEST,2026-10-29,\n", today=NOW.date())
    assert rows["TEST"]["eps_estimate"] is None
    assert "actual_eps" not in rows["TEST"]
    assert "beat" not in rows["TEST"]
