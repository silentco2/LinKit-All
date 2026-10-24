import httpx

from linkit_all.sources.ats.quickin import Quickin
from linkit_all.sources.ats_detector import detect


def _handler(load_fixture, calls):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        path = req.url.path
        if path.startswith("/public/accounts/"):
            return httpx.Response(200, json=load_fixture("quickin/account.json"))
        if path == "/public/acc123/jobs":
            return httpx.Response(
                200, json=load_fixture(f"quickin/page{req.url.params['page']}.json")
            )
        return httpx.Response(404)

    return handler


def test_search_resolves_the_account_and_pages(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(Quickin(), _handler(load_fixture, calls), board="botcity")
    assert len(pages) == 2
    (py,), (be,) = pages  # the draft posting is left out
    assert (py.title, py.company, py.location) == ("Python Developer", "BotCity", "Global, SP, BR")
    assert py.url == "https://jobs.quickin.io/botcity/jobs/job1"
    assert py.remote == "remote" and py.ats == "quickin"
    assert "Build bots" in py.description and "Python, 3y" in py.description
    assert "evil" not in py.description
    assert py.posted_at is not None and py.posted_at.year == 2026
    # empty career_url falls back to the constructed URL; a blank city is skipped
    assert be.url == "https://jobs.quickin.io/botcity/jobs/job3"
    assert be.location == "Sao Paulo, BR" and be.remote == "hybrid"
    assert be.extra == {"board": "botcity", "id": "job3"}
    assert [c for c in calls if "page=" in c] == [
        "https://api.quickin.io/public/acc123/jobs?page=1&limit=100",
        "https://api.quickin.io/public/acc123/jobs?page=2&limit=100",
    ]


def test_resume_starts_at_the_checkpointed_page(search_pages, load_fixture):
    pages = search_pages(Quickin(), _handler(load_fixture, []), board="botcity", start_page=1)
    assert [[s.title for s in p] for p in pages] == [["Backend Engineer"]]


def test_a_missing_pages_field_ends_on_a_short_page(search_pages):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.startswith("/public/accounts/"):
            return httpx.Response(200, json={"_id": "a1"})
        doc = {"_id": "j", "publicate": "published", "title": "Role"}
        return httpx.Response(200, json={"docs": [doc]})

    pages = search_pages(Quickin(), handler, board="acme-co")
    assert len(pages) == 1 and pages[0][0].company == "Acme Co"


def test_url_patterns():
    assert detect("https://jobs.quickin.io/botcity/jobs/job1") == ("quickin", "botcity")
    assert detect("quickin:botcity") == ("quickin", "botcity")
