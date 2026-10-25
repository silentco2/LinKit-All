"""LinkedIn profile key, search URL, sign-in/session API (fake browser) and capture command."""

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
    assert q["keywords"] == ["hiring python & data/ml dev"]
    assert q["datePosted"] == ['"past-week"']
    assert q["sortBy"] == ['"date_posted"']
    assert " " not in url and '"' not in url
    assert parse_qs(urlsplit(sess.search_url("x", "day")).query)["datePosted"] == ['"past-24h"']
    with pytest.raises(ValueError):
        sess.search_url("x", "year")


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
    assert r.json() == {"state": "logged_out"} and seen == [True]


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
