import httpx

from linkit_all.sources.ats.selfrecruit import SelfRecruit, job_id
from linkit_all.sources.ats_detector import detect

UID = "a7cdcc00-1c9c-464c-8960-945af0c0e0a4"


def _handler(load_fixture, calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if calls is not None:
            calls.append(path)
        if path == "/vacancies/0":
            return httpx.Response(200, text=load_fixture("selfrecruit/listing.html"))
        if path == f"/{UID}":
            return httpx.Response(200, text=load_fixture("selfrecruit/detail.html"))
        return httpx.Response(200, text=load_fixture("selfrecruit/empty.html"))

    return handler


def test_job_id():
    assert job_id(f"https://dressup.selfrecruit.ge/{UID}") == UID
    assert job_id(f"/{UID}?tmpl=modal") == UID
    assert (
        job_id("https://dressup.selfrecruit.ge/articles/09f57c76-bd0c-465c-982b-1dc644d0c3e4") == ""
    )
    for url in ("/cv", "/vacancies/10", "/", "https://dressup.selfrecruit.ge"):
        assert job_id(url) == ""


def test_search_walks_offsets_until_no_new_posting(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(SelfRecruit(), _handler(load_fixture, calls), board="dressup")
    assert [p for p in calls if p.startswith("/vacancies")] == ["/vacancies/0", "/vacancies/10"]
    (job,) = pages[0]
    assert pages[1:] == [] and job.title == "Digital Marketing Lead"
    assert (job.company, job.url, job.ats) == (
        "Dressup",
        f"https://dressup.selfrecruit.ge/{UID}",
        "selfrecruit",
    )
    assert "Build campaigns" in job.description and "alert" not in job.description
    assert job.extra == {"board": "dressup", "id": UID}


def test_a_repeated_link_ends_the_board(search_pages, load_fixture):
    # a page past the end redirects to the tenant root, whose links were already seen
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.startswith("/vacancies"):
            return httpx.Response(200, text=load_fixture("selfrecruit/listing.html"))
        return _handler(load_fixture)(req)

    pages = search_pages(SelfRecruit(), handler, board="dressup")
    assert [[s.title for s in p] for p in pages] == [["Digital Marketing Lead"]]


def test_resume_uses_the_page_offset(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(
        SelfRecruit(), _handler(load_fixture, calls), board="dressup", start_page=1
    )
    assert pages == [] and [c for c in calls if c != "/robots.txt"] == ["/vacancies/10"]


def test_a_page_without_posting_markup_is_skipped(search_pages, load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/vacancies/0":
            return httpx.Response(200, text=load_fixture("selfrecruit/listing.html"))
        return httpx.Response(200, text="<html><body>maintenance</body></html>")

    assert search_pages(SelfRecruit(), handler, board="dressup") == [[]]


def test_url_patterns():
    assert detect(f"https://dressup.selfrecruit.ge/{UID}") == ("selfrecruit", "dressup")
    assert detect("selfrecruit:dressup") == ("selfrecruit", "dressup")
