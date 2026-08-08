from odds_intel.sources.bwin.access_id import _from_text


def test_extract_from_query_style() -> None:
    html = 'fetch("/cds-api/x?x-bwin-accessid=969e2881-a869-4397-b1f2-caf6e4c57aa1&lang=en")'
    assert _from_text(html) == "969e2881-a869-4397-b1f2-caf6e4c57aa1"


def test_missing() -> None:
    assert _from_text("<html>no secrets here</html>") is None
