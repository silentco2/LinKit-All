"""Careers pages that draw their jobs with JavaScript, read in real Chrome. Every browser request
is answered by a route handler and the plain-HTTP side by httpx's MockTransport: nothing leaves
the machine. Needs Google Chrome installed."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from playwright.async_api import Request, Route

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_careers import site as fake_site

from linkit_all.core.tools import chrome_path
from linkit_all.providers.base import LLMProvider
from linkit_all.sources.base import JobStub, Task
from linkit_all.sources.browser_extract import BrowserError, PageBrowser
from linkit_all.sources.careers import Careers, Unsupported
from linkit_all.sources.http import Http

pytestmark = pytest.mark.skipif(chrome_path() is None, reason="Google Chrome not installed")

URL = "https://acme.test/careers"
SHELL = "<html><head><title>Careers</title></head><body><div id='root'></div></body></html>"

JOBS_JSON = {
    "data": {
        "jobs": [
            {"id": 1, "title": "Backend Engineer", "path": "/jobs/1", "city": "Cairo"}
            | {"summary": "<p>Build the APIs</p>"},
            {"id": 2, "title": "Data Analyst", "path": "/jobs/2", "city": "Giza"},
            {"id": 3, "title": "Designer", "path": "/jobs/3", "city": "Alexandria"},
        ]
    }
}
API_PAGE = """<html><head><title>Careers</title></head><body><div id="root"></div><script>
fetch('/api/jobs').then(r => r.json()).then(d => {
  document.getElementById('root').innerHTML = '<ul class="jobs">' +
    d.data.jobs.map(j => '<li>' + j.title + '</li>').join('') + '</ul>';
});
</script></body></html>"""
DOM_PAGE = """<html><head><title>Careers</title></head><body><ul id="jobs"></ul><script>
const jobs = [['Backend Engineer', '/jobs/1', 'Cairo'], ['Data Analyst', '/jobs/2', 'Giza'],
              ['Designer', '/jobs/3', 'Alexandria']];
document.getElementById('jobs').innerHTML = jobs.map(j =>
  `<li class="job"><h3>${j[0]}</h3><a href="${j[1]}">Apply</a><span class="loc">${j[2]}</span></li>`
).join('');
</script></body></html>"""
CHALLENGE_PAGE = "<html><head><title>Just a moment...</title></head><body>Checking</body></html>"

API_RECIPE: dict[str, Any] = {
    "method": "api_response",
    "api_url": "https://acme.test/api/jobs",
    "items_path": "data.jobs",
    "fields": {
        "title": "title",
        "url": "path",
        "location": "city",
        "description": "summary",
    },
    "reason": "the page loads its jobs from this endpoint",
}
CSS_RECIPE: dict[str, Any] = {
    "method": "css",
    "css": {"item": "li.job", "title": "h3", "link": "a", "location": ".loc"},
    "reason": "the list is built in the page",
}


class RecipeAI(LLMProvider):
    """Always answers with the recipe it was given and counts how often it was asked."""

    name = "fake"

    def __init__(self, recipe: dict[str, Any]) -> None:
        super().__init__("fake")
        self.recipe = recipe
        self.prompts: list[str] = []

    async def _call(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.recipe)


class BrowserSite:
    """What Chrome sees: path -> (content type, body). Records every request it was asked for."""

    def __init__(self, pages: dict[str, tuple[str, str]]) -> None:
        self.pages = pages
        self.seen: list[tuple[str, str]] = []  # (resource type, url)

    async def __call__(self, route: Route, request: Request) -> None:
        self.seen.append((request.resource_type, request.url))
        if (page := self.pages.get(urlsplit(request.url).path)) is None:
            await route.fulfill(status=404, body="")
        else:
            await route.fulfill(body=page[1], content_type=page[0])

    @property
    def documents(self) -> list[str]:
        return [url for kind, url in self.seen if kind == "document"]


def html(body: str) -> tuple[str, str]:
    return "text/html", body


def api_site() -> BrowserSite:
    return BrowserSite(
        {"/careers": html(API_PAGE), "/api/jobs": ("application/json", json.dumps(JOBS_JSON))}
    )


def job_page(n: int, city: str) -> str:
    return f"<html><body><h1>Role page {n}</h1><p>Location: {city}</p><p>Details.</p></body></html>"


def plain_pages() -> dict[str, str]:
    """Plain HTTP side: a JS shell for the careers page, simple job pages for 2 and 3 (job 1's
    description comes from the API, so its page must never be fetched)."""
    return {"/careers": SHELL, "/jobs/2": job_page(2, "Giza"), "/jobs/3": job_page(3, "Alexandria")}


def with_first() -> dict[str, str]:
    return {**plain_pages(), "/jobs/1": job_page(1, "Cairo")}


def crawl(
    tmp_path: Path,
    ai: RecipeAI,
    browser: BrowserSite,
    pages: dict[str, str] | None = None,
    robots: str | None = None,
) -> tuple[list[JobStub], list[str]]:
    client, calls = fake_site(pages if pages is not None else plain_pages(), robots)
    http = Http(client, default_rate=1000, attempts=1)

    async def go() -> list[JobStub]:
        careers = Careers(ai, tmp_path, browser)
        try:
            async with client:
                task = Task("careers", f"careers:{URL}", board=URL)
                return [s async for page in careers.search(http, task, 0) for s in page]
        finally:
            await careers.aclose()

    return asyncio.run(go()), calls


def recipes(tmp_path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((tmp_path / "careers" / "recipes.json").read_text("utf-8"))
    return data


def test_api_response_recipe(tmp_path: Path) -> None:
    ai, browser = RecipeAI(API_RECIPE), api_site()
    stubs, calls = crawl(tmp_path, ai, browser)
    assert [(s.title, s.url) for s in stubs] == [
        ("Backend Engineer", "https://acme.test/jobs/1"),
        ("Data Analyst", "https://acme.test/jobs/2"),
        ("Designer", "https://acme.test/jobs/3"),
    ]
    assert len(ai.prompts) == 1 and browser.documents == [URL]
    # what the model saw: the captured response's shape, not the page's scripts
    assert "https://acme.test/api/jobs" in ai.prompts[0] and "data.jobs: array[3]" in ai.prompts[0]
    assert "<script" not in ai.prompts[0] and "fetch(" not in ai.prompts[0]
    first, second, third = stubs
    assert first.description == "Build the APIs" and first.company == "Acme"
    assert "/jobs/1" not in calls  # the API already carried the description: no job page fetch
    assert second.location == "Giza" and third.location == "Alexandria"  # from their pages
    assert recipes(tmp_path)["acme.test"]["method"] == "api_response"


def test_css_recipe_on_a_dom_built_by_script(tmp_path: Path) -> None:
    ai, browser = RecipeAI(CSS_RECIPE), BrowserSite({"/careers": html(DOM_PAGE)})
    stubs, _ = crawl(tmp_path, ai, browser, with_first())
    assert [s.title for s in stubs] == ["Backend Engineer", "Data Analyst", "Designer"]
    assert {s.url for s in stubs} == {f"https://acme.test/jobs/{n}" for n in (1, 2, 3)}
    assert "li.job" in ai.prompts[0] and "Backend Engineer" in ai.prompts[0]
    assert "const jobs" not in ai.prompts[0]  # script text is not part of the summary


def test_a_cached_recipe_skips_the_ai(tmp_path: Path) -> None:
    ai = RecipeAI(CSS_RECIPE)
    first, _ = crawl(tmp_path, ai, BrowserSite({"/careers": html(DOM_PAGE)}), with_first())
    again, _ = crawl(tmp_path, ai, BrowserSite({"/careers": html(DOM_PAGE)}), with_first())
    assert len(ai.prompts) == 1 and [s.url for s in again] == [s.url for s in first]
    saved = (tmp_path / "careers" / "recipes.json").read_text("utf-8")
    assert "saved_at" in saved and "Backend Engineer" not in saved  # parameters only


def test_a_stale_cached_recipe_is_dropped_and_the_ai_asked_once_more(tmp_path: Path) -> None:
    stale = {"method": "css", "css": {"item": "li.gone", "title": "h3", "link": "a"}}
    (tmp_path / "careers").mkdir()
    (tmp_path / "careers" / "recipes.json").write_text(json.dumps({"acme.test": stale}), "utf-8")
    ai = RecipeAI(CSS_RECIPE)
    stubs, _ = crawl(tmp_path, ai, BrowserSite({"/careers": html(DOM_PAGE)}), with_first())
    assert len(stubs) == 3 and len(ai.prompts) == 1
    assert recipes(tmp_path)["acme.test"]["css"]["item"] == "li.job"


def test_a_recipe_with_no_jobs_falls_back_to_the_next_method(tmp_path: Path) -> None:
    wrong = API_RECIPE | {"items_path": "data.nothing", "css": CSS_RECIPE["css"]}
    ai, browser = (
        RecipeAI(wrong),
        BrowserSite(
            {"/careers": html(DOM_PAGE), "/api/jobs": ("application/json", json.dumps(JOBS_JSON))}
        ),
    )
    stubs, _ = crawl(tmp_path, ai, browser, with_first())
    assert [s.title for s in stubs] == ["Backend Engineer", "Data Analyst", "Designer"]
    assert len(ai.prompts) == 1  # no second call for the fallback
    assert recipes(tmp_path)["acme.test"]["method"] == "css"  # the one that worked is kept


def test_an_api_url_the_model_invented_is_rejected(tmp_path: Path) -> None:
    ai, browser = RecipeAI(API_RECIPE | {"api_url": "https://evil.test/api/jobs"}), api_site()
    with pytest.raises(Unsupported, match="needs a browser"):
        crawl(tmp_path, ai, browser)
    assert not (tmp_path / "careers" / "recipes.json").exists()
    assert all("evil.test" not in url for _, url in browser.seen)  # never requested


def test_robots_disallow_never_opens_the_browser(tmp_path: Path) -> None:
    ai, browser = RecipeAI(API_RECIPE), api_site()
    with pytest.raises(Unsupported, match=r"robots\.txt"):
        crawl(tmp_path, ai, browser, robots="User-agent: *\nDisallow: /careers\n")
    assert browser.seen == [] and ai.prompts == []

    async def direct() -> None:  # the browser checks robots itself, before it even starts Chrome
        client, _ = fake_site({}, "User-agent: *\nDisallow: /\n")
        pb = PageBrowser(browser)
        async with client:
            with pytest.raises(BrowserError, match=r"robots\.txt"):
                await pb.capture(Http(client, attempts=1), URL)
        assert pb._browser is None

    asyncio.run(direct())
    assert browser.seen == []


def test_a_challenge_page_is_unsupported_and_nothing_is_clicked(tmp_path: Path) -> None:
    ai, browser = RecipeAI(API_RECIPE), BrowserSite({"/careers": html(CHALLENGE_PAGE)})
    with pytest.raises(Unsupported, match="bot challenge"):
        crawl(tmp_path, ai, browser)
    assert browser.documents == [URL] and ai.prompts == []
    assert [kind for kind, _ in browser.seen if kind not in ("document", "other")] == []


def test_no_provider_means_no_browser(tmp_path: Path) -> None:
    client, _ = fake_site(plain_pages())
    http = Http(client, default_rate=1000, attempts=1)
    browser = api_site()

    async def go() -> None:
        async with client:
            task = Task("careers", f"careers:{URL}", board=URL)
            careers = Careers(None, tmp_path, browser)
            with pytest.raises(Unsupported, match="needs a browser"):
                _ = [s async for page in careers.search(http, task, 0) for s in page]

    asyncio.run(go())
    assert browser.seen == []
