import httpx

from linkit_all.sources.ats.collage import Collage
from linkit_all.sources.ats_detector import detect


def test_search(search_pages, load_fixture):
    data = load_fixture("collage/positions.json")
    calls: list[str] = []
    pages = search_pages(
        Collage(), lambda req: httpx.Response(200, json=data), board="northwind", calls=calls
    )
    ((a, b),) = pages  # the row without a link is dropped
    assert calls == ["https://api.collage.co/v1/positions/northwind"]
    assert (a.title, a.company, a.location) == (
        "Office Manager",
        "Northwind",
        "Toronto, ON; Remote",
    )
    assert a.url == "https://secure.collage.co/jobs/northwind/101" and a.remote == "remote"
    assert a.description == "Run the office.\n\nDepartment: Ops\nCommitment: Full-time"
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-09-15T00:00:00"
    assert b.location == "Ottawa, ON" and b.posted_at is not None  # epoch seconds
    assert (
        search_pages(Collage(), lambda r: httpx.Response(200, json=data), board="n", start_page=1)
        == []
    )


def test_url_patterns():
    assert detect("https://secure.collage.co/jobs/northwind") == ("collage", "northwind")
    assert detect("https://api.collage.co/v1/positions/northwind") == ("collage", "northwind")
