import httpx
import pytest

from linkit_all.sources.ats.applitrack import AppliTrack, decode, us_date, written
from linkit_all.sources.ats_detector import detect


def router(load_fixture, details: dict[str, str]):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        job = req.url.params.get("AppliTrackJobId")
        text = details[job] if job else load_fixture("applitrack/all.js")
        # the pages are served as windows-1252 without a declared character set
        return httpx.Response(200, content=text.replace("NDASH", chr(0x2013)).encode("cp1252"))

    return handler


DETAILS = {
    "739": "applitrack/detail_739.js",
    "812": "applitrack/detail_812.js",
    "950": "applitrack/detail_950.js",
}


@pytest.fixture
def handler(load_fixture):
    return router(load_fixture, {k: load_fixture(v) for k, v in DETAILS.items()})


def test_written_unescapes_and_skips_unescape_calls():
    assert written("document.write('<a class=\\'x\\'>hi</a>')") == "<a class='x'>hi</a>"
    assert written('document.write(unescape("%3Cb%3E"))') == ""


def test_written_refuses_a_truncated_body():
    with pytest.raises(ValueError, match="truncated"):
        written("document.write('<b>half")


def test_decode_and_dates():
    assert decode("café".encode("cp1252")) == "café"
    assert decode("café".encode()) == "café"
    assert us_date("9/1/2026").isoformat() == "2026-09-01T00:00:00"  # type: ignore[union-attr]
    assert us_date("Open until Filled") is None


def test_search_lists_each_posting_once(search_pages, handler):
    calls: list[str] = []
    pages = search_pages(AppliTrack(), handler, board="acme", calls=calls)
    stubs = pages[0]
    assert [s.extra["id"] for s in stubs] == ["739", "812", "950"]  # 950 listed twice
    assert [s.title for s in stubs] == [
        "Network Engineer",
        "Desktop Technician",
        "Help Desk Technician",
    ]
    assert stubs[0].location == "Central Office"
    assert stubs[0].posted_at is not None and stubs[0].posted_at.month == 9
    assert (
        stubs[0].url
        == "https://www.applitrack.com/acme/onlineapp/jobpostings/view.asp?AppliTrackJobId=739"
    )
    assert "all=1" in next(c for c in calls if "robots" not in c)


def test_search_is_one_page(search_pages, handler):
    assert search_pages(AppliTrack(), handler, board="acme", start_page=1) == []


def test_fetch_details_reads_the_body_and_fields(search_pages, fetch_details, handler):
    stub = search_pages(AppliTrack(), handler, board="acme")[0][0]
    out = fetch_details(AppliTrack(), handler, stub)
    assert f"Keep the district{chr(0x2013)}wide network running." in out.description
    assert "Cisco" in out.description and "track()" not in out.description
    assert "Technology" not in out.description  # the field rows are not the body
    assert out.location == "Central Office"
    assert out.posted_at is not None and out.posted_at.day == 1


def test_details_without_a_location_or_a_posting(search_pages, fetch_details, handler):
    s812, s950 = search_pages(AppliTrack(), handler, board="acme")[0][1:]
    out = fetch_details(AppliTrack(), handler, s812)
    assert out.description == "Reimage the lab carts."
    assert out.location == "Transportation"  # the listing's value stays
    # 200 with an empty list = the board no longer carries it
    assert fetch_details(AppliTrack(), handler, s950) == s950


def test_url_patterns():
    url = "https://www.applitrack.com/saskatoon/onlineapp/jobpostings/view.asp?AppliTrackJobId=739"
    assert detect(url, [AppliTrack()]) == ("applitrack", "saskatoon")
