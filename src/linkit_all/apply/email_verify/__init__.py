"""Read the user's mailbox (IMAP, read-only) for the code or link a job site sends after sign-up.

Regex first, local. Only when it finds nothing is the email text (at most ~4,000 chars) sent to
the chosen model provider (CLAUDE.md §2, §5.5). Email bodies, codes, links and the password are
never logged; only counts.
"""

import asyncio
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import unescape
from urllib.parse import urlparse

from imap_tools import AND, MailBox, MailboxLoginError
from imap_tools.errors import ImapToolsError
from loguru import logger
from pydantic import BaseModel
from selectolax.lexbor import LexborHTMLParser

from linkit_all.apply.vault import Vault
from linkit_all.core.search import EmailSection
from linkit_all.providers.base import LLMProvider, ProviderError, UsageLimitError, render

AI_MAX_CHARS = 4000
SLACK = timedelta(minutes=2)  # clock skew between us and the mail server
INBOX = "INBOX"
SPAM_FALLBACK = "[Gmail]/Spam"  # verification mails sometimes land in spam
MAX_PER_POLL = 50

# English first; add words here (other languages) to widen matching.
_LINK_WORDS = r"verif|confirm|activat|validat|token"
_CODE_WORDS = r"code|one[- ]time|otp|passcode|pin"
_SUBJECT_WORDS = re.compile(rf"(?i){_LINK_WORDS}|code|one[- ]time|otp|passcode")

_URL = re.compile(r"https?://[^\s<>\"'\])]+", re.I)
_CODE_RE = r"(?:\d{4,8}|\d{3}[- ]\d{3}|(?=[A-Z0-9]*\d)[A-Z0-9]{4,8})"
# "verification code is 123456" / "code: AB12CD"; then "123456 is your verification code".
_CODE_AFTER = re.compile(
    rf"(?i:\b(?:{_CODE_WORDS})\b)[^\d]{{0,40}}?(?<![\w-])({_CODE_RE})(?![\w-])"
)
_CODE_BEFORE = re.compile(
    rf"(?<![\w-])({_CODE_RE})(?![\w-])\s+(?i:is|=)\s+(?i:your|the)\b[^\n]{{0,30}}?(?i:\b(?:{_CODE_WORDS})\b)"
)


class EmailLoginError(Exception):
    """Plain-language reason the mailbox could not be opened."""


class Verification(BaseModel):
    code: str | None = None
    link: str | None = None


def _html_text(html: str) -> str:
    tree = LexborHTMLParser(html)
    tree.strip_tags(["script", "style"])
    return tree.text(separator="\n")


def _host_ok(url: str, domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(
        host == d or host.endswith("." + d) for d in (x.lower().lstrip(".") for x in domains)
    )


def _links(text: str, html: str) -> Iterator[tuple[str, str]]:
    """(url, anchor text) from HTML hrefs, then bare URLs in the text."""
    if html:
        for a in LexborHTMLParser(html).css("a[href]"):
            yield unescape((a.attributes.get("href") or "").strip()), a.text(strip=True)
    for m in _URL.finditer(text):
        yield m.group(0).rstrip(".,;:!?"), ""


def extract(subject: str, text: str, html: str, site_domains: list[str]) -> Verification | None:
    """Pure regex pass. A link is preferred over a code when both are present."""
    for url, anchor in _links(text, html):
        if (
            url.startswith(("http://", "https://"))
            and _host_ok(url, site_domains)
            and re.search(_LINK_WORDS, f"{url} {anchor}", re.I)
        ):
            return Verification(link=url)
    body = f"{subject}\n{text or _html_text(html)}"
    for rx in (_CODE_AFTER, _CODE_BEFORE):
        if m := rx.search(body):
            return Verification(code=re.sub(r"[- ]", "", m.group(1)))
    return None


async def ai_extract(
    provider: LLMProvider, subject: str, text: str, site_domains: list[str]
) -> Verification | None:
    """Ask the model, then keep only what appears verbatim in the email (and, for a link, on a
    site domain). Usage-limit errors propagate so the run can pause."""
    body = text[:AI_MAX_CHARS]
    prompt = render("verify_email.j2", subject=subject[:200], text=body, domains=site_domains)
    try:
        got = await provider.complete(prompt, Verification)
    except UsageLimitError:
        raise
    except ProviderError as e:
        logger.warning("email verification AI fallback failed ({})", type(e).__name__)
        return None
    code = (got.code or "").strip()
    link = (got.link or "").strip()
    out = Verification(
        code=code if 3 < len(code) <= 12 and " " not in code and code in body else None,
        link=link if link in body and _host_ok(link, site_domains) else None,
    )
    return out if out.code or out.link else None


@dataclass(frozen=True)
class _Mail:
    key: str
    subject: str
    text: str
    html: str


def _spam_folder(mb: MailBox) -> str | None:
    """The spam folder: the one flagged \\Junk (RFC 6154, any language), else `[Gmail]/Spam`."""
    try:
        for info in mb.folder.list():
            if any(f.lower() == "\\junk" for f in info.flags):
                return str(info.name)
    except ImapToolsError as e:  # no LIST support: use the fallback
        logger.warning("IMAP folder list failed ({})", type(e).__name__)
    return SPAM_FALLBACK if mb.folder.exists(SPAM_FALLBACK) else None


def _fetch(
    host: str, user: str, password: str, site_domains: list[str], since: datetime
) -> list[_Mail]:
    """Blocking: relevant recent messages, newest first. Nothing is marked read or deleted."""
    floor = since - SLACK
    if floor.tzinfo is None:
        floor = floor.replace(tzinfo=UTC)
    domains = [d.lower().lstrip(".") for d in site_domains]
    found: list[tuple[datetime, _Mail]] = []
    with MailBox(host).login(user, password) as mb:
        spam = _spam_folder(mb)
        for folder in (INBOX, spam) if spam else (INBOX,):
            mb.folder.set(folder)
            # IMAP SINCE is date-only and server-timezone: widen by a day, filter exactly below.
            crit = AND(date_gte=(floor - timedelta(days=1)).date())
            for msg in mb.fetch(crit, mark_seen=False, reverse=True, limit=MAX_PER_POLL):
                when = msg.date if msg.date.tzinfo else msg.date.replace(tzinfo=UTC)
                if when < floor:
                    continue
                sender = (msg.from_values.email if msg.from_values else "").lower()
                sender_host = sender.rpartition("@")[2]
                from_site = any(sender_host == d or sender_host.endswith("." + d) for d in domains)
                if from_site or _SUBJECT_WORDS.search(msg.subject or ""):
                    key = f"{folder}:{msg.uid or when.isoformat()}"
                    found.append(
                        (when, _Mail(key, msg.subject or "", msg.text or "", msg.html or ""))
                    )
    found.sort(key=lambda t: t[0], reverse=True)
    return [m for _, m in found]


async def wait_for_verification(
    cfg: EmailSection,
    user: str,
    password: str,
    site_domains: list[str],
    since: datetime,
    provider: LLMProvider | None = None,
) -> Verification | None:
    """Poll until a verification code/link arrives or `cfg.timeout_s` passes (then None)."""
    deadline = time.monotonic() + cfg.timeout_s
    seen: set[str] = set()
    while True:
        try:
            mails = await asyncio.to_thread(
                _fetch, cfg.imap_host, user, password, site_domains, since
            )
        except MailboxLoginError:
            raise EmailLoginError(_login_message(cfg.imap_host)) from None
        except (OSError, ImapToolsError) as e:  # network blip: try again next poll
            logger.warning("IMAP poll failed ({})", type(e).__name__)
            mails = []
        fresh = [m for m in mails if m.key not in seen]
        logger.debug("IMAP poll: {} candidate emails, {} new", len(mails), len(fresh))
        for m in fresh:
            seen.add(m.key)
            text = m.text or _html_text(m.html)
            found = extract(m.subject, m.text, m.html, site_domains)
            if found is None and provider is not None:
                found = await ai_extract(provider, m.subject, text, site_domains)
            if found is not None:
                return found
        if time.monotonic() + cfg.poll_s >= deadline:
            return None
        await asyncio.sleep(cfg.poll_s)


def _login_message(host: str) -> str:
    if "gmail" in host.lower():
        return "Gmail rejected the app password"
    return f"{host} rejected the email address or app password"


def check_login(host: str, user: str, password: str) -> None:
    """Connect and log in; raise EmailLoginError with a plain message on failure."""
    try:
        with MailBox(host).login(user, password):
            pass
    except MailboxLoginError:
        raise EmailLoginError(_login_message(host)) from None
    except (OSError, ImapToolsError) as e:
        logger.warning("IMAP check failed ({})", type(e).__name__)
        raise EmailLoginError(f"Could not connect to {host}") from None


def credentials(cfg: EmailSection, vault: Vault, profile_email: str) -> tuple[str, str] | None:
    """(user, app password) from the vault entry kind="imap", site=<imap host>; None if absent."""
    user = (cfg.imap_user or profile_email).strip().lower()
    for e in vault.find("imap", cfg.imap_host):
        if not user or e.username.lower() == user:
            return e.username, vault.get(e.id)
    return None
