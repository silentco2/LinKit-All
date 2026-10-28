"""LinkedIn profile key, search URL, sign-in/session API (fake browser) and capture command."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from linkit_all import cli
from linkit_all.api.app import create_app
from linkit_all.apply.browser import profile_dir
from linkit_all.core.config import Settings
from linkit_all.sources.linkedin_posts import session as sess

BASE = "http://127.0.0.1:8000"


def test_profile_dir_linkedin_is_separate(tmp_path: Path) -> None:
    s = Settings(data_dir=tmp_path)
    assert profile_dir(s, "linkedin") == tmp_path / "browser" / "linkedin"
    assert profile_dir(s, "workday") == tmp_path / "browser" / "generic"
    assert profile_dir(s, None) == tmp_path / "browser" / "generic"


def test_search_url_is_encoded() -> None:
    url = sess.search_url("hiring python & data/ml dev")
    parts = urlsplit(url)
    assert parts.path == "/search/results/content/"
    q = parse_qs(parts.query)
    assert q == {"keywords": ["hiring python & data/ml dev"]}  # no filters (see search_url)
    assert " " not in url and '"' not in url


@pytest.mark.parametrize(
    ("url", "state"),
    [
        ("https://www.linkedin.com/login?session_redirect=%2Ffeed", "logged_out"),
        ("https://www.linkedin.com/authwall?trk=x", "logged_out"),
        ("https://www.linkedin.com/uas/login", "logged_out"),
        ("https://www.linkedin.com/signup/cold-join", "logged_out"),
        ("https://www.linkedin.com/checkpoint/challenge/abc", "challenge"),
        ("https://www.linkedin.com/feed/", None),
    ],
)
def test_classify_url(url: str, state: str | None) -> None:
    assert sess.classify_url(url) == state


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(data_dir=tmp_path / "data"))
    with TestClient(app, base_url=BASE) as c:
        yield c


def test_signin_opens_app_browser_on_linkedin_profile(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[tuple[Path, str]] = []

    async def fake_open(self: object, profile: Path, url: str, item_id: int) -> None:
        opened.append((profile, url))
        client.app.state.user_browser._opening = True  # type: ignore[attr-defined]

    monkeypatch.setattr("linkit_all.apply.browser.UserBrowser.open", fake_open)
    r = client.post("/api/linkedin/signin")
    assert r.status_code == 201
    assert opened[0][0].name == "linkedin"
    assert opened[0][1] == "https://www.linkedin.com/login"
    assert client.post("/api/linkedin/signin").status_code == 409  # one app browser at a time
    assert client.get("/api/linkedin/session").status_code == 409  # window holds the profile
    client.app.state.user_browser._opening = False  # type: ignore[attr-defined]


def test_signin_failure_is_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(self: object, profile: Path, url: str, item_id: int) -> None:
        raise RuntimeError("no chrome\ndetails")

    monkeypatch.setattr("linkit_all.apply.browser.UserBrowser.open", boom)
    r = client.post("/api/linkedin/signin")
    assert r.status_code == 503 and "no chrome" in r.json()["detail"]


def test_session_state_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    async def fake_check(settings: Settings, headless: bool, browser: object = None) -> str:
        seen.append(headless)
        return "logged_out"

    monkeypatch.setattr(sess, "check_session", fake_check)
    r = client.get("/api/linkedin/session")
    assert r.json() == {"state": "logged_out"} and seen == [True]  # the setting's default
    body = {"sources": {"linkedin_headless": False}}
    assert client.put("/api/search", json=body, headers={"origin": BASE}).status_code == 200
    client.get("/api/linkedin/session")
    assert seen == [True, False]


def test_capture_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(data_dir=tmp_path))
    calls: list[tuple[str, Path, bool]] = []
    result_state = ["ok"]

    async def fake_capture(
        settings: Settings, keywords: str, out: Path, headed: bool = False
    ) -> str:
        calls.append((keywords, out, headed))
        return result_state[0]

    monkeypatch.setattr(sess, "capture_search", fake_capture)
    out = tmp_path / "x.html"
    args = ["linkedin", "capture", "--keywords", "hiring dev", "--out", str(out)]
    r = CliRunner().invoke(cli.app, args)
    assert r.exit_code == 0 and "Review it before sharing" in r.output
    assert calls == [("hiring dev", out, False)]
    result_state[0] = "logged_out"
    r = CliRunner().invoke(cli.app, ["linkedin", "capture", "--keywords", "a", "--headed"])
    assert r.exit_code == 1 and "Not signed in" in r.output and calls[-1][2] is True


def test_linkedin_context_uses_real_chrome_and_closes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []

    class FakeCtx:
        pass

    class FakeChrome:
        async def close(self) -> None:
            calls.append("closed")

    class FakePW:
        async def __aenter__(self) -> "FakePW":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    async def fake_open(pw: object, profile: Path, *, headless: bool) -> tuple[FakeChrome, FakeCtx]:
        calls.append(("open", profile, headless))
        return FakeChrome(), FakeCtx()

    monkeypatch.setattr(sess, "async_playwright", lambda: FakePW())
    monkeypatch.setattr(sess, "open_context", fake_open)
    settings = Settings(data_dir=tmp_path)

    async def run(fail: bool) -> None:
        async with sess.linkedin_context(settings, headless=True) as ctx:
            assert isinstance(ctx, FakeCtx)
            if fail:
                raise ValueError("boom")

    asyncio.run(run(False))
    with pytest.raises(ValueError):
        asyncio.run(run(True))
    expected = ("open", profile_dir(settings, "linkedin"), True)
    assert calls == [expected, "closed", expected, "closed"]


class FakeButton:
    def __init__(self, page: "FakePage") -> None:
        self.page = page
        self.first = self

    async def count(self) -> int:  # like the live list: rendered only once read to its end
        return int(self.page.pages_left > 0 and self.page.top() == self.page.end())

    async def scroll_into_view_if_needed(self) -> None:
        return None

    async def click(self) -> None:
        self.page.clicks += 1
        self.page.pages_left -= 1


class FakeMouse:
    def __init__(self) -> None:
        self.moves: list[tuple[float, float]] = []
        self.wheels = 0

    async def move(self, x: float, y: float) -> None:
        self.moves.append((x, y))

    async def wheel(self, dx: float, dy: float) -> None:
        self.wheels += 1


class FakeMain:
    async def bounding_box(self) -> dict[str, float]:
        return {"x": 0, "y": 80, "width": 760, "height": 380}


class FakePage:
    def __init__(self, pages_left: int) -> None:
        self.pages_left, self.clicks, self.mouse = pages_left, 0, FakeMouse()

    def locator(self, selector: str) -> FakeMain:
        assert selector == "main"
        return FakeMain()

    def get_by_role(self, role: str, name: object) -> FakeButton:
        assert role == "button" and name is sess.LOAD_MORE
        return FakeButton(self)

    def end(self) -> int:
        return 1500 * (self.clicks + 1)  # each page makes the list longer

    def top(self) -> int:
        return min(self.mouse.wheels * 250, self.end())

    async def evaluate(self, js: str) -> int:
        assert "scrollTop" in js
        return self.top()


@pytest.mark.parametrize(("pages_left", "cap", "clicks"), [(5, 3, 3), (1, 3, 1), (0, 3, 0)])
def test_load_more_is_capped_and_stops_on_last_page(
    monkeypatch: pytest.MonkeyPatch, pages_left: int, cap: int, clicks: int
) -> None:
    async def no_sleep(s: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    page = FakePage(pages_left)
    assert asyncio.run(sess.load_more(page, cap)) == clicks  # type: ignore[arg-type]
    assert page.clicks == clicks
    assert page.mouse.moves == [(380, 270)]  # over the results, not the nav at (0, 0)


def test_load_more_label_matches_english_only_whole() -> None:
    assert sess.LOAD_MORE.match(" Load more ") and sess.LOAD_MORE.match("LOAD MORE")
    assert not sess.LOAD_MORE.match("Load more comments")
