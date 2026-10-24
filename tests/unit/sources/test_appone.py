import httpx

from linkit_all.sources.ats.appone import AppOne, salary
from linkit_all.sources.ats_detector import detect


def test_search_maps_a_portal(search_pages, load_fixture):
    data = load_fixture("appone/list_crwa.json")
    pages = search_pages(AppOne(), lambda req: httpx.Response(200, json=data), board="crwa")
    a, b = pages[0]
    assert a.title == "Climate Resilience Manager"
    assert a.company == "Charles River Watershed Association"
    assert a.location == "Boston, MA"
    assert a.url == "https://apply.appone.com/job/6ab41fa965690128921b7d13"
    assert a.remote == "hybrid"
    assert (a.salary_min, a.salary_max, a.salary_currency, a.salary_interval) == (
        65000,
        70000,
        "USD",
        "year",
    )
    assert (b.salary_min, b.salary_max) == (62000, 62000)  # EXACT_AMOUNT
    assert a.posted_at is not None and a.posted_at.year == 2026
    assert a.extra["id"] == "6ab41fa965690128921b7d13" and a.ats == "appone"


def test_salary_options():
    assert salary({"minimum": 5, "salaryOption": "STARTING_AMOUNT", "periodType": "HOUR"}) == {
        "salary_min": 5,
        "salary_max": None,
        "salary_currency": "USD",
        "salary_interval": "hour",
    }
    assert (
        salary({"maximum": 9, "salaryOption": "MAXIMUM_AMOUNT", "periodType": "YEAR"})["salary_max"]
        == 9
    )
    assert salary({"minimum": 5, "salaryOption": "WEIRD", "periodType": "YEAR"}) == {}
    assert salary({"minimum": 5, "salaryOption": "RANGE"}) == {}  # no period
    assert salary(None) == {}


def test_fetch_details_reads_the_plain_text_body(search_pages, fetch_details, load_fixture):
    data = load_fixture("appone/list_streamlineworkcomp.json")
    stub = search_pages(
        AppOne(), lambda req: httpx.Response(200, json=data), board="streamlineworkcomp"
    )[0][0]
    detail = load_fixture("appone/detail_6ac795efd03e41f35800e54b.json")
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json=detail)

    url = "https://apply.appone.com/job/6ac795efd03e41f35800e54b"
    out = fetch_details(AppOne(), handler, stub.model_copy(update={"url": url}))
    assert out.description.startswith("Mid-Level QA Analyst (Remote)")
    assert seen == ["/api/apply/v2/jobposting/6ac795efd03e41f35800e54b"]


def test_a_gone_posting_keeps_the_stub(search_pages, fetch_details, load_fixture):
    data = load_fixture("appone/list_crwa.json")
    stub = search_pages(AppOne(), lambda req: httpx.Response(200, json=data), board="crwa")[0][0]
    assert fetch_details(AppOne(), lambda req: httpx.Response(404), stub) == stub


def test_a_stray_403_is_retried(search_pages, load_fixture, monkeypatch):
    import linkit_all.sources.ats.appone as mod
    from linkit_all.sources.common import retry_while

    async def no_sleep(_: float) -> None: ...

    async def fast(call, **kw):  # the real helper, minus the 2 s wait
        return await retry_while(call, sleep=no_sleep, **kw)

    monkeypatch.setattr(mod, "retry_while", fast)
    data = load_fixture("appone/list_crwa.json")
    answers = [httpx.Response(403), httpx.Response(200, json=data)]
    pages = search_pages(AppOne(), lambda req: answers.pop(0), board="crwa")
    assert len(pages[0]) == 2 and not answers


def test_url_patterns():
    sources = [AppOne()]
    assert detect("https://jobs.appone.com/streamlineworkcomp", sources) == (
        "appone",
        "streamlineworkcomp",
    )
    api = "https://jobs.appone.com/api/portal/v1/companyjobposts/crwa"
    assert detect(api, sources) == ("appone", "crwa")
