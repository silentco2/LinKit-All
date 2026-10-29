# ruff: noqa: F811
"""Connecting Gmail end to end through the API, against a fake Gmail (IMAP reader + SMTP sender).

CI never reaches Gmail: `imap_tools.MailBox` and `smtplib.SMTP_SSL` are replaced by in-memory fakes
that share one inbox, so a test-send lands where the verification reader looks. The one real-Gmail
test is opt-in (`pytest -m live`, needs LINKIT_LIVE_GMAIL_USER and LINKIT_LIVE_GMAIL_APP_PASSWORD).
"""

import asyncio
import os
import smtplib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from loguru import logger
from test_actions_batch import park
from test_api import SAME_ORIGIN, client, mem_keyring  # noqa: F401  (fixtures)
from test_email_verify import FakeBox, cfg, msg
from test_vault import PASS

from linkit_all.apply import email_verify as ev
from linkit_all.apply.email_verify import Verification, credentials, wait_for_verification
from linkit_all.apply.vault import Vault
from linkit_all.core.models import ActionItem, ActionKind, ActionStatus, Job, JobState

USER = "me@gmail.com"
APP_PASSWORD = "abcdefghijklmnop"  # noqa: S105  (fake)
SPACED = "abcd efgh ijkl mnop"  # how Google shows it


@dataclass
class GmailBox(FakeBox):
    """A MailBox that only accepts the right address + app password."""

    user: str = USER
    good: str = APP_PASSWORD

    def login(self, user: str, password: str) -> "GmailBox":
        self.password_ok = (user, password) == (self.user, self.good)
        return super().login(user, password)  # type: ignore[return-value]


class FakeSMTP:
    """Gmail's SMTP: checks the login, then delivers into the shared inbox."""

    box: GmailBox
    inbox: list[SimpleNamespace]
    connections: list[tuple[str, int]]

    def __init__(self, host: str, port: int, **kw: Any) -> None:
        type(self).connections.append((host, port))
        self.authed = False

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        if (user, password) != (self.box.user, self.box.good):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.authed = True

    def send_message(self, m: EmailMessage) -> None:
        assert self.authed
        body = m.get_body(("plain",))
        text = body.get_content() if body is not None else ""
        self.inbox.append(
            msg(
                str(len(self.inbox) + 1), str(m["Subject"]), text,
                sender=USER, when=datetime.now(UTC),
            )
        )  # fmt: skip
        self.inbox[-1].raw_to = str(m["To"])
        self.inbox[-1].raw_from = str(m["From"])


@pytest.fixture
def gmail(monkeypatch: pytest.MonkeyPatch) -> GmailBox:
    box = GmailBox([[]])
    monkeypatch.setattr(ev, "MailBox", box)
    smtp = type("SMTP", (FakeSMTP,), {"box": box, "inbox": box.script[0], "connections": []})
    monkeypatch.setattr(smtplib, "SMTP_SSL", smtp)
    box.smtp = smtp  # type: ignore[attr-defined]
    return box


@pytest.fixture
def logs() -> Iterator[list[str]]:
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")
    yield lines
    logger.remove(sink)


def post(client: TestClient, path: str, body: object = None) -> Any:
    return client.post(path, json=body or {}, headers=SAME_ORIGIN)


def unlock_with_profile(client: TestClient) -> Vault:
    post(client, "/api/vault/create", {"passphrase": PASS})
    post(client, "/api/vault/unlock", {"passphrase": PASS, "remember": False})
    client.put("/api/profile", json={"full_name": "Me", "email": USER}, headers=SAME_ORIGIN)
    return client.app.state.vault  # type: ignore[no-any-return, attr-defined]


def test_connect_send_and_disconnect(client: TestClient, gmail: GmailBox, logs: list[str]) -> None:
    vault = unlock_with_profile(client)

    # a wrong password: clear message, nothing saved, the secret is never echoed
    bad = post(client, "/api/email", {"app_password": "wrong wrong wrong wrg"})
    assert bad.status_code == 400 and bad.json()["detail"] == "Gmail rejected the app password"
    assert "wrongwrong" not in bad.text
    assert vault.entries() == [] and client.get("/api/email").json()["connected"] is False

    # the right one (as Google prints it, with spaces): saved in the vault, never returned
    ok = post(client, "/api/email", {"app_password": SPACED})
    assert ok.status_code == 200 and ok.json()["connected"] is True
    assert APP_PASSWORD not in ok.text and SPACED not in ok.text
    (entry,) = vault.entries()
    assert (entry.kind, entry.site, entry.username) == ("imap", "imap.gmail.com", USER)
    assert vault.get(entry.id) == APP_PASSWORD
    for url in ("/api/email", "/api/search", "/api/profile", "/api/status"):
        assert APP_PASSWORD not in client.get(url).text, url
    assert post(client, "/api/email/test").json() == {"ok": True}

    # test-send goes through smtp.gmail.com:465 to the user's own address
    sent = post(client, "/api/email/test-send")
    assert sent.status_code == 200 and sent.json()["ok"] is True and sent.json()["message_id"]
    assert APP_PASSWORD not in sent.text
    assert gmail.smtp.connections == [("smtp.gmail.com", 465)]  # type: ignore[attr-defined]
    (delivered,) = gmail.script[0]
    assert delivered.raw_to == USER and USER in delivered.raw_from
    assert delivered.subject == "LinKit All test" and APP_PASSWORD not in delivered.text

    # the saved password stopped working (user revoked it): a clear failure, no crash
    gmail.good = "somethingelseentirely"
    revoked = post(client, "/api/email/test-send").json()
    assert revoked["ok"] is False and "app password" in revoked["error"]
    gmail.good = APP_PASSWORD

    # disconnect removes the secret and everything that needed it
    assert client.delete("/api/email", headers=SAME_ORIGIN).status_code == 204
    assert vault.entries() == [] and client.get("/api/email").json()["connected"] is False
    assert post(client, "/api/email/test").status_code == 404
    assert post(client, "/api/email/test-send").status_code == 409

    assert not [line for line in logs if APP_PASSWORD in line or "wrongwrong" in line]


def test_connect_then_retry_requeues_needs_email_jobs(client: TestClient, gmail: GmailBox) -> None:
    vault = unlock_with_profile(client)
    job, item = park(client, ActionKind.login_issue, code="needs_email")
    old_job, old_item = park(client, ActionKind.login_issue, code="email_not_connected")
    other_job, _ = park(client, ActionKind.login_issue, code="needs_vault")
    assert credentials(_email_cfg(client), vault, USER) is None  # nothing connected yet

    assert post(client, "/api/email", {"app_password": APP_PASSWORD}).json()["connected"] is True
    retry = post(client, "/api/actions/retry-code", {"code": "needs_email"})
    assert retry.json() == {"count": 2}

    with client.app.state.db() as s:  # type: ignore[attr-defined]
        assert s.get_one(Job, job).state == JobState.queued_apply
        assert s.get_one(Job, old_job).state == JobState.queued_apply
        assert s.get_one(Job, other_job).state == JobState.needs_user  # a different problem
        assert s.get_one(ActionItem, item).status == ActionStatus.resolved
        assert s.get_one(ActionItem, old_item).status == ActionStatus.resolved


def _email_cfg(client: TestClient) -> Any:
    from linkit_all.core.search import SearchConfig

    return SearchConfig.model_validate(client.get("/api/search").json()).email


def test_verification_code_is_found_in_the_connected_inbox(
    client: TestClient, gmail: GmailBox
) -> None:
    vault = unlock_with_profile(client)
    assert post(client, "/api/email", {"app_password": APP_PASSWORD}).status_code == 200
    post(client, "/api/email/test-send")  # our own mail must not look like a code mail
    since = datetime.now(UTC) - timedelta(minutes=1)
    gmail.script[0].append(
        msg(
            "77", "Your Greenhouse verification code",
            "Copy and paste this code into the security code field:\n\n"
            "Your verification code is 8K2P9QX1\n",
            sender="no-reply@us.greenhouse-mail.io", when=datetime.now(UTC),
        )
    )  # fmt: skip
    email_cfg = _email_cfg(client)
    creds = credentials(email_cfg, vault, USER)
    assert creds == (USER, APP_PASSWORD)

    found = asyncio.run(wait_for_verification(cfg(), *creds, ["greenhouse-mail.io"], since))
    assert found == Verification(code="8K2P9QX1")
    # nothing was marked read or deleted
    assert gmail.calls and all(c["mark_seen"] is False for c in gmail.calls)


# --- the one test that talks to the real Gmail: opt-in, never in CI ---

live_user = os.environ.get("LINKIT_LIVE_GMAIL_USER", "")
live_password = os.environ.get("LINKIT_LIVE_GMAIL_APP_PASSWORD", "")


@pytest.mark.live
@pytest.mark.skipif(
    not (live_user and live_password),
    reason="set LINKIT_LIVE_GMAIL_USER and LINKIT_LIVE_GMAIL_APP_PASSWORD to run (real Gmail)",
)
def test_live_gmail_connect_and_send_to_self(client: TestClient, logs: list[str]) -> None:
    post(client, "/api/vault/create", {"passphrase": PASS})
    post(client, "/api/vault/unlock", {"passphrase": PASS, "remember": False})
    client.put(
        "/api/profile", json={"full_name": "LinKit live test", "email": live_user},
        headers=SAME_ORIGIN,
    )  # fmt: skip
    vault: Vault = client.app.state.vault  # type: ignore[attr-defined]

    wrong = post(client, "/api/email", {"app_password": "abcdabcdabcdabcd"})
    assert wrong.status_code == 400 and "rejected" in wrong.json()["detail"]

    ok = post(client, "/api/email", {"app_password": live_password})
    assert ok.status_code == 200 and ok.json()["connected"] is True, ok.text
    assert live_password not in ok.text
    assert post(client, "/api/email/test").json() == {"ok": True}
    sent = post(client, "/api/email/test-send").json()  # one real email, to the user's own address
    assert sent["ok"] is True, sent
    assert client.delete("/api/email", headers=SAME_ORIGIN).status_code == 204
    assert vault.entries() == []
    assert not [line for line in logs if live_password in line]
