import httpx
import pytest

from linkit_all.sources.ats.homerun import Homerun
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.careers import Unsupported


def test_search_reads_the_atom_feed(search_pages, load_fixture):
    xml = load_fixture("homerun/feed.xml")
    calls: list[str] = []
    ((a, b),) = search_pages(
        Homerun(), lambda req: httpx.Response(200, text=xml), board="Northwind", calls=calls
    )
    assert calls == ["https://feed.homerun.co/northwind"]
    assert (a.title, a.company, a.location) == ("Backend Engineer", "Northwind Coffee", "Amsterdam")
    assert a.url == "https://northwind.homerun.co/backend-engineer"
    assert " ".join(a.description.split()) == "Build the roaster API."
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-09-29T15:07:45"
    assert a.extra["id"] == "job_abc123" and a.extra["salary_text"].startswith("€60000")
    assert b.remote == "remote" and b.extra["salary_text"] == ""
    assert (
        search_pages(Homerun(), lambda r: httpx.Response(200, text=xml), board="n", start_page=1)
        == []
    )


def test_an_unknown_board_is_reported(search_pages):
    def gone(req: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://404.homerun.co/feeds/nope"})

    with pytest.raises(Unsupported, match="no board"):
        search_pages(Homerun(), gone, board="nope")


def test_url_patterns():
    assert detect("https://northwind.homerun.co/backend-engineer") == ("homerun", "northwind")
    assert detect("https://feed.homerun.co/northwind") == ("homerun", "northwind")
    assert detect("https://www.homerun.co/pricing") is None
