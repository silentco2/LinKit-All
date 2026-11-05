"""Outlook/Hotmail: Microsoft OAuth sign-in, token refresh into the vault, XOAUTH2 for IMAP and SMTP.
All with fakes; nothing reaches Microsoft."""

import base64
import imaplib
import smtplib
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from test_api import SAME_ORIGIN, client, mem_keyring  # noqa: F401  (fixtures)
from test_vault import CHEAP, PASS

import linkit_all.apply.email_verify as ev
from linkit_all.apply.email_send import OutgoingEmail, SmtpAuthError, build_message, send
from linkit_all.apply.email_verify import EmailLoginError, check_login, credentials, microsoft
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


class FakeBox:
    def __init__(self, host: str) -> None:
        self.host = host
        self.how: tuple[str, str, str] | None = None

    def login(self, user: str, password: str) -> "FakeBox":
        self.how = ("login", user, password)
        return self

    def xoauth2(self, user: str, token: str) -> "FakeBox":
        self.how = ("xoauth2", user, token)
        if token == "bad":  # noqa: S105
            raise imaplib.IMAP4.error("AUTHENTICATE failed")
        if token == "imap-off":  # noqa: S105
            raise imaplib.IMAP4.error("User is authenticated but not connected.")
        return self

    def __enter__(self) -> "FakeBox":
        return self

    def __exit__(self, *a: object) -> None:
        return None


def test_imap_uses_xoauth2_for_microsoft_only(monkeypatch: pytest.MonkeyPatch) -> None:
    boxes: list[FakeBox] = []
    monkeypatch.setattr(ev, "MailBox", lambda host: boxes.append(FakeBox(host)) or boxes[-1])
    check_login(microsoft.IMAP_HOST, USER, "AT")
    check_login("imap.gmail.com", "me@gmail.com", "pw")
    assert [b.how for b in boxes] == [("xoauth2", USER, "AT"), ("login", "me@gmail.com", "pw")]
    with pytest.raises(EmailLoginError, match="Microsoft rejected the sign-in"):
        check_login(microsoft.IMAP_HOST, USER, "bad")
    with pytest.raises(EmailLoginError, match="Let devices and apps use IMAP"):
        check_login(microsoft.IMAP_HOST, USER, "imap-off")


class FakeSMTP:
    instances: ClassVar[list["FakeSMTP"]] = []
    reject = False

    def __init__(self, host: str, port: int, timeout: float = 0) -> None:
        self.host, self.port = host, port
        self.tls = self.hello = False
        self.auth_line = ""
        self.sent: list[EmailMessage] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def starttls(self, context: Any = None) -> None:
        self.tls, self.hello = True, False  # like the real server: EHLO again after STARTTLS

    def ehlo(self) -> None:
        self.hello = True

    def auth(self, mechanism: str, authobject: Any) -> None:
        assert mechanism == "XOAUTH2" and self.tls and self.hello
        self.auth_line = base64.b64encode(authobject().encode()).decode()
        if FakeSMTP.reject:
            raise smtplib.SMTPAuthenticationError(535, b"no")

    def send_message(self, msg: EmailMessage) -> None:
        self.sent.append(msg)


def test_smtp_sends_with_starttls_and_xoauth2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeSMTP.instances, FakeSMTP.reject = [], False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    v = _vault(tmp_path)
    msg = build_message("Me", USER, OutgoingEmail("hr@acme.com", "S", "B"))
    assert send(MS, v, USER, msg) == msg["Message-ID"]
    (smtp,) = FakeSMTP.instances
    assert (smtp.host, smtp.port, smtp.sent) == ("smtp-mail.outlook.com", 587, [msg])
    assert (
        base64.b64decode(smtp.auth_line) == f"user={USER}\x01auth=Bearer AT-fresh\x01\x01".encode()
    )
    FakeSMTP.reject = True
    with pytest.raises(SmtpAuthError, match="sign in with Microsoft again"):
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
