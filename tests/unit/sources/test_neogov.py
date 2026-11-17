import httpx

from linkit_all.sources.ats.neogov import Neogov
from linkit_all.sources.ats_detector import detect


def test_search_asks_the_list_endpoint_like_the_page(search_pages, load_fixture):
    html = load_fixture("neogov/list.html")
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, text=html)

    ((a, b),) = search_pages(Neogov(), handler, board="governmentjobs/lakeside")
    (req,) = seen  # a short page ends the walk
    assert req.url.host == "www.governmentjobs.com" and req.url.path == "/careers/home/index"
    assert req.url.params["agency"] == "lakeside" and req.url.params["page"] == "1"
    assert req.headers["x-requested-with"] == "XMLHttpRequest"
    assert (a.title, a.company, a.location) == (
        "Water Systems Operator",
        "Lakeside",
        "Lakeside, CA",
    )
    assert a.url.startswith(
        "https://www.governmentjobs.com/careers/lakeside/jobs/5550001/water-systems-operator"
    )
    assert a.extra == {"board": "governmentjobs/lakeside", "id": "5550001"}
    assert (b.title, b.remote) == ("Librarian", "remote")


def test_url_patterns():
    assert detect("https://www.governmentjobs.com/careers/lakeside") == (
        "neogov",
        "governmentjobs/lakeside",
    )
    assert detect("https://schooljobs.com/careers/lakesideusd/x") == (
        "neogov",
        "schooljobs/lakesideusd",
    )
    assert detect("https://www.schooljobs.com/careers/home") is None
