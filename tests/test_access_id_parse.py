import base64

from odds_intel.sources.bwin.access_id import _b64_to_uuid, _extract_candidates, _variants


def test_extract_base64_access_id() -> None:
    uuid = "56b2978c-6592-4609-b61b-fe804a7d1fa3"
    b64 = base64.b64encode(uuid.encode()).decode()
    html = f'fetch("/cds-api/x?x-bwin-accessid={b64}&lang=en")'
    hits = _extract_candidates(html)
    assert b64 in hits
    assert uuid in hits


def test_extract_from_query_style_uuid() -> None:
    html = 'x-bwin-accessid=969e2881-a869-4397-b1f2-caf6e4c57aa1'
    hits = _extract_candidates(html)
    assert "969e2881-a869-4397-b1f2-caf6e4c57aa1" in hits


def test_b64_roundtrip() -> None:
    uuid = "56b2978c-6592-4609-b61b-fe804a7d1fa3"
    b64 = base64.b64encode(uuid.encode()).decode()
    assert _b64_to_uuid(b64) == uuid
    assert b64 in _variants(uuid)


def test_missing() -> None:
    assert _extract_candidates("<html>no secrets here</html>") == []
