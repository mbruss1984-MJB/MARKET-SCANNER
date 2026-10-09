from types import SimpleNamespace
from screener import extract_symbols

def test_screener_filters_to_listed_common_universe():
    payload = SimpleNamespace(data={"items": [
        {"symbol": "AAPL.US"}, {"code": "MSFT"},
        {"symbol": "BAD-W.US"}, {"symbol": "OTCQ.US"},
        {"symbol": "AAPL.US"}, {"symbol": None}]})
    assert extract_symbols(payload, {"AAPL.US", "MSFT.US"}) == ["AAPL.US", "MSFT.US"]

def test_invalid_payload_fails_closed():
    assert extract_symbols({"items": None}, {"AAPL.US"}) == []
    assert extract_symbols({}, {"AAPL.US"}) == []
