"""Outlook/Hotmail: Microsoft sign-in, token refresh into the vault, reading and sending mail
through Microsoft Graph. All with fakes; nothing reaches Microsoft."""

import asyncio
import base64
from datetime import UTC, datetime
from email import message_from_bytes
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import httpx
import pytest
from fastapi.testclient import TestClient
from test_api import SAME_ORIGIN, client, mem_keyring  # noqa: F401  (fixtures)
from test_vault import CHEAP, PASS

from linkit_all.apply.email_send import OutgoingEmail, SmtpAuthError, SmtpError, build_message, send
from linkit_all.apply.email_verify import (
    EmailLoginError,
    Verification,
    check_login,
    credentials,
    microsoft,
    wait_for_verification,
)
from linkit_all.apply.vault import Vault
from linkit_all.core.db import init_db
from linkit_all.core.search import EmailSection

USER = "me@outlook.com"


class FakeCache:
    def __init__(self) -> None:
        self.state = ""
        self.has_state_changed = False

    def serialize(self) -> str:
        return self.state

    def deserialize(self, s: str) -> None:
        self.state = s


class FakeApp:
    """Stands in for msal.PublicClientApplication."""

    calls: ClassVar[list[tuple[str, dict[str, Any]]]] = []
    result: ClassVar[dict[str, Any]] = {}
    expired = False

    def __init__(self, client_id: str, authority: str, token_cache: FakeCache) -> None:
        assert client_id == "cid" and authority.endswith("/consumers")
        self.cache = token_cache

    def acquire_token_interactive(self, scopes: list[str], **kw: Any) -> dict[str, Any]:
        FakeApp.calls.append(("interactive", kw))
        if "access_token" in FakeApp.result:
            self.cache.state = "cache-v1"
        return FakeApp.result

    def get_accounts(self, username: str | None = None) -> list[dict[str, str]]:
        return [{"username": USER}] if self.cache.state else []

    def acquire_token_silent(self, scopes: list[str], **kw: Any) -> dict[str, Any] | None:
        FakeApp.calls.append(("silent", kw))
        if FakeApp.expired:
            return None
        self.cache.state, self.cache.has_state_changed = "cache-v2", True  # rotated refresh token
        return {"access_token": "AT-fresh"}


@pytest.fixture(autouse=True)
def fake_msal(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeApp.calls, FakeApp.expired = [], False
    FakeApp.result = {
        "access_token": "AT-1",
        "id_token_claims": {"preferred_username": "Me@Outlook.com"},
    }
    fake = SimpleNamespace(
        PublicClientApplication=FakeApp,
        SerializableTokenCache=FakeCache,
        BrowserInteractionTimeoutError=TimeoutError,
    )
    monkeypatch.setattr(microsoft, "msal", fake)
    monkeypatch.setattr(microsoft, "get_settings", lambda: SimpleNamespace(ms_client_id="cid"))


def _vault(tmp_path: Path, secret: str = "cache-v1") -> Vault:  # noqa: S107
    v = Vault(init_db(tmp_path / "v.db"), "t", CHEAP)
    v.create(PASS)
    v.unlock(PASS)
    v.put("imap", microsoft.IMAP_HOST, USER, secret)
    return v


MS = EmailSection(imap_host=microsoft.IMAP_HOST, imap_user=USER)


def test_sign_in_returns_signed_in_address_token_and_cache() -> None:
    assert microsoft.sign_in("me@hotmail.com") == (USER, "AT-1", "cache-v1")
    ((_, kw),) = FakeApp.calls
    assert kw["login_hint"] == "me@hotmail.com" and kw["timeout"] == microsoft.SIGN_IN_TIMEOUT_S
    FakeApp.result = {"error": "access_denied"}
    with pytest.raises(microsoft.MicrosoftAuthError):
        microsoft.sign_in("")


def test_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(microsoft, "get_settings", lambda: SimpleNamespace(ms_client_id=""))
    assert not microsoft.configured()
    with pytest.raises(microsoft.MicrosoftAuthError, match="LINKIT_MS_CLIENT_ID"):
        microsoft.sign_in(USER)


def test_credentials_refresh_and_save_rotated_cache(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    assert credentials(MS, v, "") == (USER, "AT-fresh")
    assert FakeApp.calls[-1] == ("silent", {"account": {"username": USER}, "force_refresh": True})
    (entry,) = v.find("imap", microsoft.IMAP_HOST)
    assert v.get(entry.id) == "cache-v2"
    FakeApp.expired = True
    with pytest.raises(EmailLoginError, match="sign in with Microsoft again"):
        credentials(MS, v, "")


class FakeGraph:
    """Stands in for httpx.request against graph.microsoft.com."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = 200
        self.inbox: list[dict[str, Any]] = []
        self.junk: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, **kw: Any) -> httpx.Response:
        self.calls.append({"method": method, "url": url, **kw})
        if self.status != 200:
            return httpx.Response(self.status, request=httpx.Request(method, url))
        if url.endswith("/sendMail"):
            return httpx.Response(202, request=httpx.Request(method, url))
        value = self.junk if "/junkemail/" in url else self.inbox
        return httpx.Response(200, json={"value": value}, request=httpx.Request(method, url))


@pytest.fixture
def graph(monkeypatch: pytest.MonkeyPatch) -> FakeGraph:
    fake = FakeGraph()
    monkeypatch.setattr(microsoft.httpx, "request", fake)
    return fake


NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def mail(subject: str, html: str, sender: str = "no-reply@acme.example") -> dict[str, Any]:
    return {
        "id": subject,
        "subject": subject,
        "receivedDateTime": "2026-11-05T12:01:00Z",
        "from": {"emailAddress": {"address": sender}},
        "body": {"contentType": "html", "content": html},
    }


def test_check_login_reads_inbox_with_token(graph: FakeGraph) -> None:
    check_login(microsoft.IMAP_HOST, USER, "AT")
    (call,) = graph.calls
    assert call["url"].endswith("/me/mailFolders/inbox")
    assert call["headers"]["Authorization"] == "Bearer AT"
    graph.status = 401
    with pytest.raises(EmailLoginError, match="sign in with Microsoft again"):
        check_login(microsoft.IMAP_HOST, USER, "AT")
    graph.status = 503
    with pytest.raises(EmailLoginError, match="Could not connect"):
        check_login(microsoft.IMAP_HOST, USER, "AT")


def test_wait_for_verification_reads_inbox_and_junk(graph: FakeGraph) -> None:
    graph.inbox = [mail("Newsletter", "<p>hello</p>")]
    graph.junk = [mail("Your verification code", "<p>Your code is 482913</p>")]
    cfg = MS.model_copy(update={"timeout_s": 1, "poll_s": 0.02})
    got = asyncio.run(wait_for_verification(cfg, USER, "AT", ["acme.example"], NOW))
    assert got == Verification(code="482913")
    folders = [c["url"].rsplit("/", 2)[-2] for c in graph.calls]
    assert folders == ["inbox", "junkemail"]
    params = graph.calls[0]["params"]
    assert params["$filter"] == "receivedDateTime ge 2026-11-05T11:58:00Z"  # 2-minute slack
    graph.status = 403
    with pytest.raises(EmailLoginError, match="sign in with Microsoft again"):
        asyncio.run(wait_for_verification(cfg, USER, "AT", ["acme.example"], NOW))


def test_send_posts_mime_to_graph(tmp_path: Path, graph: FakeGraph) -> None:
    v = _vault(tmp_path)
    msg = build_message("Me", USER, OutgoingEmail("hr@acme.com", "Application", "Hello"))
    assert send(MS, v, USER, msg) == msg["Message-ID"]
    (call,) = graph.calls
    assert call["method"] == "POST" and call["url"].endswith("/me/sendMail")
    assert call["headers"]["Authorization"] == "Bearer AT-fresh"
    sent = message_from_bytes(base64.b64decode(call["content"]))
    assert sent["Subject"] == "Application" and sent["To"] == "hr@acme.com"
    graph.status = 401
    with pytest.raises(SmtpAuthError, match="sign in with Microsoft again"):
        send(MS, v, USER, msg)
    graph.status = 500
    with pytest.raises(SmtpError, match="Microsoft"):
        send(MS, v, USER, msg)
    FakeApp.expired = True
    with pytest.raises(SmtpAuthError, match="sign in with Microsoft again"):
        send(MS, v, USER, msg)


def test_connect_route(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    logins: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "linkit_all.api.routes.check_login",
        lambda *a: logins.append(a),  # type: ignore[func-returns-value]
    )

    def post(path: str, body: object = None) -> Any:
        return client.post(path, json=body or {}, headers=SAME_ORIGIN)

    assert post("/api/email/microsoft").status_code == 423  # vault locked
    post("/api/vault/create", {"passphrase": PASS})
    post("/api/vault/unlock", {"passphrase": PASS, "remember": False})
    got = post("/api/email/microsoft", {"imap_user": "me@hotmail.com"}).json()
    assert logins == [(microsoft.IMAP_HOST, USER, "AT-1")]
    assert got["connected"] and got["microsoft"] and got["imap_user"] == USER
    assert got["imap_host"] == microsoft.IMAP_HOST
    FakeApp.result = {"error": "access_denied"}
    bad = post("/api/email/microsoft")
    assert bad.status_code == 400 and "cancelled" in bad.json()["detail"]
