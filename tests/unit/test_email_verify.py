"""Email verification: regex extraction, AI fallback guard rails, polling, login, credentials."""

import asyncio
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import keyring
import pytest
from imap_tools import MailboxLoginError
from keyring.backend import KeyringBackend

from linkit_all.apply import email_verify as ev
from linkit_all.apply.email_verify import (
    EmailLoginError,
    Verification,
    ai_extract,
    check_login,
    credentials,
    extract,
    wait_for_verification,
)
from linkit_all.apply.vault import Vault
from linkit_all.core.db import init_db
from linkit_all.core.search import EmailSection, SearchConfig
from linkit_all.providers.base import LLMProvider, ProviderError, UsageLimitError

DOMAINS = ["myworkdayjobs.com", "greenhouse.io"]

WORKDAY_HTML = """<html><body><p>Hi Jane,</p><p>Thanks for creating an account.</p>
<a href="https://acme.wd5.myworkdayjobs.com/en-US/Careers/activate/abc123token?x=1&amp;y=2">
Verify Email</a>
<a href="https://track.evil.example/verify?u=1">Verify now</a>
<p><a href="https://acme.wd5.myworkdayjobs.com/unsubscribe">Unsubscribe</a></p></body></html>"""
WORKDAY_LINK = "https://acme.wd5.myworkdayjobs.com/en-US/Careers/activate/abc123token?x=1&y=2"
GREENHOUSE_TEXT = """Hi Jane,

Copy and paste this code into the security code field on your application:

Your verification code is 8K2P9QX1

It expires in 10 minutes. If you did not apply, ignore this email.
"""
ICIMS_TEXT = "Your one-time passcode: 482913\nDo not share it."
PHISH_HTML = '<a href="https://acme-careers.example.net/verify?token=zzz">Confirm your email</a>'
NEWSLETTER = "Ten new roles this week at Acme. Visit https://acme.myworkdayjobs.com/jobs to browse."


class FakeAI(LLMProvider):
    name = "fake"

    def __init__(self, answer: dict[str, Any] | Exception) -> None:
        super().__init__("fake")
        self.answer = answer
        self.prompts: list[str] = []

    async def _call(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return json.dumps(self.answer)


# --- extract ---


def test_code_extraction() -> None:
    assert extract("Verify", GREENHOUSE_TEXT, "", DOMAINS) == Verification(code="8K2P9QX1")
    assert extract("Your code", ICIMS_TEXT, "", DOMAINS) == Verification(code="482913")
    v = extract("Welcome", "482 913 is your verification code.", "", DOMAINS)
    assert v == Verification(code="482913")
    v = extract("Verify your account", "", "<p>Your OTP is <b>7391</b></p>", DOMAINS)
    assert v == Verification(code="7391")


def test_link_extraction_html_and_text_restricted_to_site_domains() -> None:
    assert extract("Confirm", "", WORKDAY_HTML, DOMAINS) == Verification(link=WORKDAY_LINK)
    text = "Confirm here: https://boards.greenhouse.io/confirm/xyz789."
    assert extract("Confirm", text, "", DOMAINS) == Verification(
        link="https://boards.greenhouse.io/confirm/xyz789"
    )
    # lookalike host is not a subdomain of a site domain
    assert extract("x", "https://evilmyworkdayjobs.com/verify/1", "", DOMAINS) is None


def test_foreign_domain_link_is_ignored() -> None:
    assert extract("Confirm your email", "", PHISH_HTML, DOMAINS) is None


def test_link_preferred_over_code() -> None:
    html = WORKDAY_HTML.replace("<p>Hi Jane,</p>", "<p>Your verification code is 654321</p>")
    assert extract("Verify", "", html, DOMAINS) == Verification(link=WORKDAY_LINK)


def test_nothing_found() -> None:
    assert extract("Weekly jobs", NEWSLETTER, "", DOMAINS) is None
    assert extract("", "", "", DOMAINS) is None


# --- ai_extract ---


def test_ai_extract_accepts_only_verbatim_in_domain() -> None:
    text = "Use 5521 to finish. Or open https://acme.myworkdayjobs.com/go/9f3 and sign in."
    good = FakeAI({"code": "5521", "link": "https://acme.myworkdayjobs.com/go/9f3"})
    got = asyncio.run(ai_extract(good, "Welcome", text, DOMAINS))
    assert got == Verification(code="5521", link="https://acme.myworkdayjobs.com/go/9f3")
    assert "Use 5521" in good.prompts[0] and "myworkdayjobs.com" in good.prompts[0]

    bad = FakeAI({"code": "9999", "link": "https://evil.example/go/9f3"})
    assert asyncio.run(ai_extract(bad, "Welcome", text, DOMAINS)) is None
    # in the text, but a foreign domain: link dropped, verbatim code kept
    phish = f"Code 4455. {PHISH_HTML} https://evil.example/v/1"
    mixed = FakeAI({"code": "4455", "link": "https://evil.example/v/1"})
    assert asyncio.run(ai_extract(mixed, "x", phish, DOMAINS)) == Verification(code="4455")


def test_ai_extract_truncates_and_handles_errors() -> None:
    long_text = "a" * 3990 + " TAILMARKER " + "b" * 500
    ai = FakeAI({"code": None, "link": None})
    assert asyncio.run(ai_extract(ai, "s", long_text, DOMAINS)) is None
    assert "TAILMARKER" not in ai.prompts[0]
    assert asyncio.run(ai_extract(FakeAI(ProviderError("boom")), "s", "t", DOMAINS)) is None
    with pytest.raises(UsageLimitError):
        asyncio.run(ai_extract(FakeAI(UsageLimitError("usage limit")), "s", "t", DOMAINS))


# --- wait_for_verification with a fake MailBox ---

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def msg(
    uid: str, subject: str, text: str = "", html: str = "", sender: str = "no-reply@x.example",
    when: datetime = NOW, folder: str = "INBOX",
) -> SimpleNamespace:  # fmt: skip
    return SimpleNamespace(
        uid=uid, subject=subject, text=text, html=html, date=when, folder=folder,
        from_values=SimpleNamespace(email=sender),
    )  # fmt: skip


@dataclass
class FakeBox:
    """Stands in for imap_tools.MailBox; `script[i]` is what poll i sees (last one repeats)."""

    script: list[list[SimpleNamespace]]
    polls: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)
    current: str = "INBOX"
    password_ok: bool = True
    spam: bool = True

    def __call__(self, host: str) -> "FakeBox":
        self.host = host
        return self

    def login(self, user: str, password: str) -> "FakeBox":
        if not self.password_ok:
            raise MailboxLoginError(("NO", "bad"), "NO")  # type: ignore[arg-type]
        self.polls += 1
        return self

    def __enter__(self) -> "FakeBox":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    @property
    def folder(self) -> "FakeBox":
        return self

    def exists(self, name: str) -> bool:
        return self.spam

    def set(self, name: str) -> None:
        self.current = name

    def fetch(self, criteria: object, **kw: Any) -> Iterator[SimpleNamespace]:
        self.calls.append(kw)
        batch = self.script[min(self.polls, len(self.script)) - 1]
        return iter([m for m in batch if m.folder == self.current])


def cfg(**kw: Any) -> EmailSection:
    # model_copy skips validation so tests can use sub-second timings
    return EmailSection().model_copy(update={"timeout_s": 1, "poll_s": 0.02, **kw})


def run_wait(box: FakeBox, monkeypatch: pytest.MonkeyPatch, **kw: Any) -> Verification | None:
    monkeypatch.setattr(ev, "MailBox", box)
    return asyncio.run(wait_for_verification(cfg(**kw), "me@gmail.com", "pw", DOMAINS, NOW))


def test_wait_finds_code_newest_first_and_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    old = msg(
        "1", "Your verification code", "verification code: 111111", when=NOW - timedelta(minutes=1)
    )
    new = msg("2", "Your verification code", "verification code: 222222", when=NOW + timedelta(minutes=1))  # fmt: skip
    box = FakeBox([[old, new]])
    assert run_wait(box, monkeypatch) == Verification(code="222222")
    assert box.calls and all(c["mark_seen"] is False for c in box.calls)


def test_wait_ignores_old_and_unrelated_mail_then_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = msg("1", "Your verification code", "code: 111111", when=NOW - timedelta(minutes=10))
    other = msg("2", "Lunch?", "code: 333333", sender="friend@gmail.example")
    box = FakeBox([[stale, other]])
    assert run_wait(box, monkeypatch, timeout_s=0.1) is None
    assert box.polls >= 2  # kept polling until the timeout


def test_wait_accepts_site_sender_and_slack_window(monkeypatch: pytest.MonkeyPatch) -> None:
    # subject has no keyword but the sender is on a site domain; 90s before `since` is inside the 2 min slack
    m = msg("3", "Welcome to Acme", ICIMS_TEXT, sender="jobs@mail.greenhouse.io", when=NOW - timedelta(seconds=90))  # fmt: skip
    assert run_wait(FakeBox([[m]]), monkeypatch) == Verification(code="482913")


def test_wait_polls_until_mail_arrives_and_checks_spam(monkeypatch: pytest.MonkeyPatch) -> None:
    spam = msg("9", "Confirm your email", html=WORKDAY_HTML, folder="[Gmail]/Spam")
    box = FakeBox([[], [], [spam]])
    assert run_wait(box, monkeypatch) == Verification(link=WORKDAY_LINK)
    assert box.polls == 3
    box2 = FakeBox([[spam]], spam=False)  # no spam folder: skipped, nothing found
    assert run_wait(box2, monkeypatch, timeout_s=0.05) is None


def test_wait_ai_fallback_only_when_regex_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    m = msg("5", "Please confirm", "Enter ab-77 within ten minutes. Token K9X2 here.", sender="a@greenhouse.io")  # fmt: skip
    ai = FakeAI({"code": "K9X2", "link": None})
    monkeypatch.setattr(ev, "MailBox", FakeBox([[m]]))
    got = asyncio.run(wait_for_verification(cfg(), "u", "p", DOMAINS, NOW, provider=ai))
    assert got == Verification(code="K9X2")
    assert len(ai.prompts) == 1  # the same email is not re-sent on later polls
    hit = msg("6", "Your code", "code: 123456")
    ai2 = FakeAI({"code": "000000", "link": None})
    monkeypatch.setattr(ev, "MailBox", FakeBox([[hit]]))
    asyncio.run(wait_for_verification(cfg(), "u", "p", DOMAINS, NOW, provider=ai2))
    assert ai2.prompts == []


def test_wait_bad_password_raises_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    box = FakeBox([[]], password_ok=False)
    with pytest.raises(EmailLoginError, match="Gmail rejected the app password"):
        run_wait(box, monkeypatch)


def test_wait_survives_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class Flaky(FakeBox):
        def login(self, user: str, password: str) -> "Flaky":
            if self.polls == 0:
                self.polls += 1
                raise ConnectionResetError("reset")
            return super().login(user, password)  # type: ignore[return-value]

    m = msg("1", "Your code", "code: 123456")
    assert run_wait(Flaky([[m]]), monkeypatch) == Verification(code="123456")


# --- check_login ---


def test_check_login_error_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ev, "MailBox", FakeBox([[]]))
    check_login("imap.gmail.com", "me@gmail.com", "pw")  # no error
    monkeypatch.setattr(ev, "MailBox", FakeBox([[]], password_ok=False))
    with pytest.raises(EmailLoginError, match="Gmail rejected the app password"):
        check_login("imap.gmail.com", "me@gmail.com", "pw")
    with pytest.raises(EmailLoginError, match=r"mail.example.org rejected"):
        check_login("mail.example.org", "me@example.org", "pw")

    def offline(host: str) -> object:
        raise TimeoutError("timed out")

    monkeypatch.setattr(ev, "MailBox", offline)
    with pytest.raises(EmailLoginError, match=r"Could not connect to imap.gmail.com"):
        check_login("imap.gmail.com", "me@gmail.com", "pw")


# --- credentials / config ---


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.store.pop((service, username), None)


def test_credentials_from_vault(tmp_path: Path) -> None:
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    try:
        v = Vault(
            init_db(tmp_path / "t.db"),
            "k",
            kdf={"time_cost": 1, "memory_cost": 8, "parallelism": 1},
        )
        v.create("correct horse battery")
        v.unlock("correct horse battery")
        assert credentials(EmailSection(), v, "me@gmail.com") is None
        v.put("imap", "imap.gmail.com", "other@gmail.com", "other-app-pw")
        v.put("imap", "imap.gmail.com", "me@gmail.com", "abcd efgh ijkl mnop")
        v.put("imap", "imap.yahoo.com", "me@yahoo.com", "yahoo-pw")
        assert credentials(EmailSection(), v, "Me@Gmail.com") == (
            "me@gmail.com",
            "abcd efgh ijkl mnop",
        )
        # imap_user overrides the profile email
        c = EmailSection(imap_user="other@gmail.com")
        assert credentials(c, v, "me@gmail.com") == ("other@gmail.com", "other-app-pw")
        assert credentials(EmailSection(imap_user="nobody@gmail.com"), v, "") is None
        assert credentials(EmailSection(imap_host="imap.yahoo.com"), v, "") == (
            "me@yahoo.com",
            "yahoo-pw",
        )
    finally:
        keyring.set_keyring(previous)


def test_search_config_backward_compatible() -> None:
    cfg_ = SearchConfig.model_validate({"search": {"queries": ["dev"]}})
    assert cfg_.email == EmailSection()
    assert (cfg_.email.imap_host, cfg_.email.timeout_s, cfg_.email.poll_s) == (
        "imap.gmail.com",
        300,
        10,
    )
    with pytest.raises(ValueError):
        EmailSection(timeout_s=5)
