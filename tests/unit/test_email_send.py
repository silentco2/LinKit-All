"""SMTP sending: message building, header safety, fake SMTP, error mapping."""

import smtplib
from email import message_from_bytes
from email.message import EmailMessage
from pathlib import Path
from typing import Any, ClassVar

import pytest
from test_vault import CHEAP, PASS

from linkit_all.apply.email_send import (
    NoCredentials,
    OutgoingEmail,
    SmtpAuthError,
    SmtpError,
    build_message,
    save_eml,
    send,
)
from linkit_all.apply.vault import Vault
from linkit_all.core.db import init_db
from linkit_all.core.search import EmailSection


class FakeSMTP:
    instances: ClassVar[list["FakeSMTP"]] = []
    fail_login: Exception | None = None
    fail_send: Exception | None = None

    def __init__(self, host: str, port: int, timeout: float = 0, context: Any = None) -> None:
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.logged_in: tuple[str, str] | None = None
        self.sent: list[EmailMessage] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        if FakeSMTP.fail_login:
            raise FakeSMTP.fail_login
        self.logged_in = (user, password)

    def send_message(self, msg: EmailMessage) -> None:
        if FakeSMTP.fail_send:
            raise FakeSMTP.fail_send
        self.sent.append(msg)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    FakeSMTP.fail_login = FakeSMTP.fail_send = None
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def _vault(tmp_path: Path, host: str = "imap.gmail.com") -> Vault:
    v = Vault(init_db(tmp_path / "v.db"), "t", CHEAP)
    v.create(PASS)
    v.unlock(PASS)
    v.put("imap", host, "me@x.com", "app-secret-pw")
    return v


def test_build_message_headers_and_attachment(tmp_path: Path) -> None:
    pdf = tmp_path / "Jane CV.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    mail = OutgoingEmail("hr@acme.com", "Application", "Hello", [pdf], reply_to="me@x.com")
    msg = build_message("Jane Doe", "me@x.com", mail)
    assert msg["From"] == "Jane Doe <me@x.com>" and msg["To"] == "hr@acme.com"
    assert msg["Reply-To"] == "me@x.com" and msg["Subject"] == "Application"
    assert msg["Message-ID"].endswith("@x.com>") and msg["Date"]
    parsed = message_from_bytes(bytes(msg))
    parts = list(parsed.walk())
    att = next(p for p in parts if p.get_filename())
    assert att.get_content_type() == "application/pdf" and att.get_filename() == "Jane CV.pdf"
    assert att.get_payload(decode=True) == b"%PDF-1.4 fake"
    assert any(p.get_content_type() == "text/plain" for p in parts)


@pytest.mark.parametrize(
    "mail",
    [
        OutgoingEmail("a@b.com\r\nBcc: evil@x.com", "s", "b"),
        OutgoingEmail("a@b.com", "hi\nBcc: evil@x.com", "b"),
        OutgoingEmail("a@b.com, c@d.com", "s", "b"),
        OutgoingEmail("not-an-address", "s", "b"),
        OutgoingEmail("a@b.com", "s", "b", reply_to="x@y.com\r\nX: 1"),
    ],
)
def test_header_injection_rejected(mail: OutgoingEmail) -> None:
    with pytest.raises(ValueError):
        build_message("Jane", "me@x.com", mail)


def test_sender_name_injection_rejected() -> None:
    with pytest.raises(ValueError):
        build_message("Jane\r\nBcc: e@x.com", "me@x.com", OutgoingEmail("a@b.com", "s", "b"))


def test_save_eml(tmp_path: Path) -> None:
    msg = build_message("Jane", "me@x.com", OutgoingEmail("a@b.com", "Subj", "Body"))
    out = save_eml(msg, tmp_path / "sub" / "p.eml")
    assert b"Subject: Subj" in out.read_bytes()


def test_send_uses_vault_credentials(tmp_path: Path, fake_smtp: type[FakeSMTP]) -> None:
    msg = build_message("Jane", "me@x.com", OutgoingEmail("a@b.com", "S", "B"))
    mid = send(EmailSection(), _vault(tmp_path), "me@x.com", msg)
    (smtp,) = fake_smtp.instances
    assert mid == msg["Message-ID"]
    assert (smtp.host, smtp.port) == ("smtp.gmail.com", 465)
    assert smtp.logged_in == ("me@x.com", "app-secret-pw") and smtp.sent == [msg]
    assert smtp.context is not None and smtp.timeout > 0


def test_no_credentials(tmp_path: Path) -> None:
    v = Vault(init_db(tmp_path / "v.db"), "t", CHEAP)
    v.create(PASS)
    v.unlock(PASS)
    msg = build_message("J", "me@x.com", OutgoingEmail("a@b.com", "S", "B"))
    with pytest.raises(NoCredentials):
        send(EmailSection(), v, "me@x.com", msg)


def test_yahoo_default_host(tmp_path: Path, fake_smtp: type[FakeSMTP]) -> None:
    cfg = EmailSection(imap_host="imap.mail.yahoo.com")
    msg = build_message("J", "me@x.com", OutgoingEmail("a@b.com", "S", "B"))
    send(cfg, _vault(tmp_path, "imap.mail.yahoo.com"), "me@x.com", msg)
    assert fake_smtp.instances[0].host == "smtp.mail.yahoo.com"
    custom = EmailSection(imap_host="imap.mail.yahoo.com", smtp_host="smtp.example.org")
    assert custom.effective_smtp_host() == "smtp.example.org"
    old = EmailSection.model_validate({"imap_host": "imap.gmail.com"})  # config without smtp keys
    assert old.smtp_port == 465 and old.effective_smtp_host() == "smtp.gmail.com"


def test_error_mapping(tmp_path: Path, fake_smtp: type[FakeSMTP]) -> None:
    v = _vault(tmp_path)
    msg = build_message("J", "me@x.com", OutgoingEmail("a@b.com", "S", "B"))
    fake_smtp.fail_login = smtplib.SMTPAuthenticationError(535, b"bad")
    with pytest.raises(SmtpAuthError, match="app password"):
        send(EmailSection(), v, "me@x.com", msg)
    fake_smtp.fail_login = None
    fake_smtp.fail_send = smtplib.SMTPRecipientsRefused({})
    with pytest.raises(SmtpError) as e:
        send(EmailSection(), v, "me@x.com", msg)
    assert not isinstance(e.value, SmtpAuthError)
    fake_smtp.fail_send = TimeoutError()
    with pytest.raises(SmtpError):
        send(EmailSection(), v, "me@x.com", msg)
