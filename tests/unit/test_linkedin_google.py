"""LinkedIn posts through Google: result parsing, check detection, redirect resolving, post pages,
the source (fake browser and HTTP) and the Settings endpoints. Nothing leaves the machine."""

import asyncio
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from linkit_all.api.app import create_app
from linkit_all.core.config import Settings
from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.linkedin_posts import google as g
from linkit_all.sources.linkedin_posts.post import read_post
from linkit_all.sources.linkedin_posts.source import LinkedInPosts, check_flag

FIX = Path(__file__).parent.parent / "fixtures" / "linkedin_posts"
RESULTS = (FIX / "google_results.html").read_text("utf-8")
SORRY = (FIX / "google_sorry.html").read_text("utf-8")
POST_HTML = (FIX / "post.html").read_text("utf-8")
POST = "https://www.linkedin.com/posts/acme-hr_hiring-python-activity-7521569560525946880-qLMu"
BASE = "http://127.0.0.1:8000"


def test_search_url() -> None:
    parts = urlsplit(g.search_url(" python developer hiring ", "day", 20))
    q = parse_qs(parts.query)
    assert q == {
        "q": ["site:linkedin.com/posts python developer hiring"],
        "tbs": ["qdr:d"],
        "start": ["20"],
    }
    assert "start" not in g.search_url("x", "week")


@pytest.mark.parametrize(
    ("url", "html", "kind"),
    [
        ("https://www.google.com/sorry/index?continue=x", "", "check"),
        ("https://www.google.com/search?q=x", SORRY, "check"),
        ("https://consent.google.com/ml?continue=x", "", "consent"),
        ("https://www.google.com/search?q=x", RESULTS, None),
        ("https://www.google.com/search?q=x", "<p>unusual traffic, not a robot</p>", None),
    ],
)
def test_blocked(url: str, html: str, kind: str | None) -> None:
    assert g.blocked(url, html) == kind


def test_result_links_and_direct_targets() -> None:
    links, more = g.result_links(RESULTS)
    assert more and len(links) == 5  # "Related searches" has no <h3>: not a result
    assert all(link.startswith("https://www.google.com/") for link in links[:3])
    assert [g.direct_target(link) for link in links[:3]] == [None, None, None]  # opaque
    assert g.direct_target(links[3]) == POST + "?utm_source=share"
    assert g.direct_target(links[4]) == (
        "https://eg.linkedin.com/posts/nour_hiring-activity-7520000000000000000-abCD"
    )
    assert g.result_links("<div id=search></div>") == ([], False)


def test_post_id_canonical_and_date() -> None:
    assert g.post_id(POST + "?trk=x") == ("activity", "7521569560525946880")
    assert g.post_id("https://www.linkedin.com/posts/x-ugcPost-7521569560525946880-ab") == (
        "ugcpost",
        "7521569560525946880",
    )
    assert g.post_id("https://www.linkedin.com/in/sara") is None
    assert g.post_id("https://evil-linkedin.com/posts/x-activity-7521569560525946880") is None
    assert g.canonical("https://eg.linkedin.com/posts/a-activity-1234567890123456789-x?u=1#c") == (
        "https://www.linkedin.com/posts/a-activity-1234567890123456789-x"
    )
    at = g.posted_from_id("activity", "7521569560525946880")
    assert at is not None and at.replace(microsecond=0) == datetime(2026, 10, 29, 13, 52, 7)
    assert g.posted_from_id("ugcpost", "7521569560525946880") is None


def test_read_post_reads_only_the_post() -> None:
    now = datetime(2026, 10, 31)
    post = read_post(POST_HTML, POST, "urn:li:activity:7521569560525946880", now)
    assert post is not None
    assert post.author == "Acme HR" and post.author_url == "https://www.linkedin.com/company/acme"
    assert post.posted_at == datetime(2026, 10, 29, 13, 52, 7, 232000)
    assert post.emails == ("jobs@acme.example",)  # the commenter's address is never read
    assert post.links == ("https://boards.greenhouse.io/acme/jobs/123",)
    assert read_post("<html></html>", POST, "u", now) is None
    assert read_post(RESULTS, POST, "u", now) is None


class FakeResponse:
    def __init__(self, location: str) -> None:
        self.headers = {"location": location}


class FakeRequest:
    def __init__(self, targets: dict[str, str]) -> None:
        self.targets = targets
        self.calls: list[str] = []

    async def get(self, url: str, **kw: Any) -> FakeResponse:
        assert kw["max_redirects"] == 0  # never follows: LinkedIn is not loaded
        self.calls.append(url)
        return FakeResponse(self.targets.get(url, "https://example.com/elsewhere"))


class FakePage:
    def __init__(self, pages: list[tuple[str, str]]) -> None:
        self.pages, self.url, self.html = pages, "", ""
        self.visited: list[str] = []

    async def goto(self, url: str, **kw: Any) -> None:
        self.visited.append(url)
        self.url, self.html = self.pages.pop(0)

    async def content(self) -> str:
        return self.html


class FakeCtx:
    def __init__(self, page: FakePage, request: FakeRequest) -> None:
        self.pages, self.request = [page], request


def fake_search(pages: list[tuple[str, str]], targets: dict[str, str]) -> g.GoogleSearch:
    search = g.GoogleSearch(Path("unused"), headless=True, pause=lambda a, b: 0)
    search._ctx = FakeCtx(FakePage(pages), FakeRequest(targets))  # type: ignore[assignment]
    return search


def test_post_urls_resolves_opaque_links_and_pages_on() -> None:
    first = g.result_links(RESULTS)[0][0]
    serp = ("https://www.google.com/search?q=x", RESULTS)
    search = fake_search([serp] * 3, {first: POST.replace("acme-hr", "sara")})
    urls = asyncio.run(search.post_urls("python", "week", 30))
    assert urls == [
        POST.replace("acme-hr", "sara"),
        POST,
        "https://www.linkedin.com/posts/nour_hiring-activity-7520000000000000000-abCD",
    ]
    page: Any = search._ctx.pages[0]  # type: ignore[union-attr]
    assert len(page.visited) == 3 and "start=20" in page.visited[2]  # 30 posts = 3 pages max


def test_post_urls_stops_at_max_posts_and_on_a_check() -> None:
    serp = ("https://www.google.com/search?q=x", RESULTS)
    assert len(asyncio.run(fake_search([serp], {}).post_urls("python", "week", 1))) == 1
    sorry = ("https://www.google.com/sorry/index", SORRY)
    with pytest.raises(g.GoogleBlocked) as e:
        asyncio.run(fake_search([sorry], {}).post_urls("python", "week", 10))
    assert e.value.kind == "check"
    first = g.result_links(RESULTS)[0][0]
    with pytest.raises(g.GoogleBlocked):  # the redirect itself lands on /sorry
        asyncio.run(
            fake_search([serp], {first: "https://www.google.com/sorry/index?x"}).post_urls(
                "python", "week", 10
            )
        )


class FakeGoogle:
    def __init__(self, urls: list[str] | Exception) -> None:
        self.urls = urls
        self.calls: list[str] = []
        self.closed = False

    async def post_urls(self, keywords: str, window: str, max_posts: int) -> list[str]:
        self.calls.append(f"{keywords}|{window}|{max_posts}")
        if isinstance(self.urls, Exception):
            raise self.urls
        return self.urls

    async def close(self) -> None:
        self.closed = True


class FakeHttp:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get(self, url: str) -> httpx.Response:
        self.calls.append(url)
        return httpx.Response(200, text=POST_HTML)


def cfg(**sources: Any) -> SearchConfig:
    base = {"enabled": ["linkedin_posts"], "linkedin_keywords": ["python", "data"]}
    return SearchConfig.model_validate({"sources": base | sources})


async def collect(src: LinkedInPosts, http: FakeHttp, task: Any) -> list[Any]:
    return [s async for page in src.search(http, task, 0) for s in page]  # type: ignore[arg-type]


def test_source_is_registered_and_opt_in(tmp_path: Path) -> None:
    src = registry(data_dir=tmp_path)["linkedin_posts"]
    assert not src.is_enabled(cfg(enabled=[])) and src.is_enabled(cfg())
    keys = ["a", "A ", "b", "c", "d", "e", "f"]
    tasks = src.tasks(cfg(linkedin_keywords=keys, linkedin_window="day"))
    assert [t.query for t in tasks] == ["a", "A", "b", "c", "d"]  # deduped, at most 5
    assert {t.posted_within_days for t in tasks} == {1}


def test_source_reads_posts_and_skips_old_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "linkit_all.sources.linkedin_posts.source.utcnow", lambda: datetime(2026, 10, 31)
    )
    src = LinkedInPosts(None, tmp_path)
    old = "https://www.linkedin.com/posts/x-activity-7000000000000000000-ab"  # 2022
    src._google = FakeGoogle([POST, old, POST])  # type: ignore[assignment]
    check_flag(tmp_path).parent.mkdir(parents=True)
    check_flag(tmp_path).touch()
    http = FakeHttp()
    task = src.tasks(cfg())[0]
    stubs = asyncio.run(collect(src, http, task))
    assert http.calls == [POST]  # the 2022 post is dropped by its id, the repeat by the set
    assert [s.ats for s in stubs] == ["greenhouse"]  # ATS link: no AI needed
    assert stubs[0].url == POST and stubs[0].extra["urn"] == "urn:li:activity:7521569560525946880"
    assert not check_flag(tmp_path).exists()  # a search got through: the check is gone


def test_source_stops_for_the_run_on_a_check(tmp_path: Path) -> None:
    src = LinkedInPosts(None, tmp_path)
    fake = FakeGoogle(g.GoogleBlocked("check"))
    src._google = fake  # type: ignore[assignment]
    tasks = src.tasks(cfg())
    with pytest.raises(Unsupported, match="Solve Google check"):
        asyncio.run(collect(src, FakeHttp(), tasks[0]))
    assert check_flag(tmp_path).exists()
    with pytest.raises(Unsupported):
        asyncio.run(collect(src, FakeHttp(), tasks[1]))
    assert len(fake.calls) == 1  # the second keyword never reached Google
    asyncio.run(src.aclose())
    assert fake.closed and src._google is None


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(data_dir=tmp_path / "data"))
    with TestClient(app, base_url=BASE) as c:
        yield c


def test_google_check_endpoints(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    data = client.app.state.settings.data_dir  # type: ignore[attr-defined]
    assert client.get("/api/linkedin/google-check").json() == {"needed": False}
    check_flag(data).parent.mkdir(parents=True, exist_ok=True)
    check_flag(data).touch()
    assert client.get("/api/linkedin/google-check").json() == {"needed": True}

    opened: list[tuple[Path, str]] = []

    async def fake_open(self: object, profile: Path, url: str, item_id: int) -> None:
        opened.append((profile, url))
        client.app.state.user_browser._opening = True  # type: ignore[attr-defined]

    monkeypatch.setattr("linkit_all.apply.browser.UserBrowser.open", fake_open)
    body = {"sources": {"linkedin_keywords": ["python hiring"]}}
    assert client.put("/api/search", json=body, headers={"origin": BASE}).status_code == 200
    assert client.post("/api/linkedin/google-check").status_code == 201
    assert opened[0][0] == data / "browser" / "google"
    assert parse_qs(urlsplit(opened[0][1]).query)["q"] == ["site:linkedin.com/posts python hiring"]
    assert client.post("/api/linkedin/google-check").status_code == 409  # one window at a time
    client.app.state.user_browser._opening = False  # type: ignore[attr-defined]
