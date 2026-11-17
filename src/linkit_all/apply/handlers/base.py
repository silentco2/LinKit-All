"""ATS handler interface: where the form is, how to read it, what success looks like."""

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from linkit_all.apply.accounts import Account, PasswordRules
from linkit_all.apply.answers import Question
from linkit_all.apply.form import extract
from linkit_all.core import timing
from linkit_all.sources.liveness import closed_text

CAPTCHA = (
    'iframe[src*="recaptcha/api2/bframe"], iframe[src*="hcaptcha.com"][src*="challenge"], '
    'iframe[title*="challenge" i]'
)

# .ng-invalid is Angular's state class on whole forms, not a message
ERRORS = "[role=alert], [class*=error i], [class*=invalid i]:not(.ng-invalid), .application-error"


class PostingGone(Exception):
    """The form never showed and the page says the posting is gone."""


# Confirmation wording of sites without a handler (the generic form agent).
GENERIC_CONFIRMATION = re.compile(
    r"thank you for (applying|your application)|thanks? for applying|"
    r"application (has been |was )?(successfully )?(submitted|received|sent)|"
    r"we.ve received your application|we have received your application"
)


async def wait_for_text(page: Page, pattern: re.Pattern[str], timeout_ms: int = 25000) -> bool:
    """True once the page text matches `pattern` (case-insensitive)."""
    try:
        await page.wait_for_function(
            "re => new RegExp(re, 'i').test(document.body.innerText)",
            arg=pattern.pattern,
            timeout=timeout_ms,
        )
    except Exception:
        return False
    return True


def posting_form(job: "JobInfo", host: str, suffix: str) -> str:
    """The form page of an ATS posting: the apply link, else the posting link, on the ATS's own
    host, without tracking parameters (`?utm_source=...` from the board that linked it)."""
    for link in (job.apply_url, job.url):
        base = (link or "").split("#")[0].split("?")[0].rstrip("/")
        if host in base:
            return base if base.endswith(suffix) else base + suffix
    return f"{job.url.rstrip('/')}{suffix}"


@dataclass
class JobInfo:
    id: int
    title: str
    company: str
    location: str
    description: str
    url: str
    apply_url: str
    source: str
    extra: dict[str, Any]


# A connection the site dropped or reset mid-load (seen on Ashby): worth one more try. Anything
# else (a 404, a DNS failure, a timeout) is the site's answer and is not retried.
_DROPPED = re.compile(
    r"ERR_(CONNECTION_(CLOSED|RESET|ABORTED)|EMPTY_RESPONSE|NETWORK_CHANGED|HTTP2_)"
)


async def goto(page: Page, url: str, timeout_ms: int = 60000) -> None:
    """Open `url` in `page`, once more after a short wait if the site dropped the connection."""
    with timing.step("load page"):
        timing.note(urlparse(url).netloc)
        for attempt in (1, 2):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                return
            except PlaywrightError as e:
                if attempt == 2 or not _DROPPED.search(str(e)):
                    raise
                timing.note("the site dropped the connection; tried again")
                await page.wait_for_timeout(3000)


class Handler:
    ats: str
    container: str
    label: str
    description: str = ""
    ignore: str = ""
    submit_button: str
    confirmation: re.Pattern[str]
    password_rules: PasswordRules = PasswordRules()

    def form_url(self, job: JobInfo) -> str:
        return job.apply_url or job.url

    async def open(self, page: Page, job: JobInfo) -> None:
        await goto(page, self.form_url(job))
        with timing.step("wait for page"):
            try:
                await page.locator(self.container).first.wait_for(timeout=30000)
            except PlaywrightError:
                text = await page.evaluate("() => document.body ? document.body.innerText : ''")
                if closed_text(f"{await page.title()} {text[:5000]}"):
                    raise PostingGone("the posting is gone") from None
                raise
            # Let React finish hydrating, or it resets fields filled too early. Pages that
            # long-poll never go idle; the refill check after filling covers those.
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightError:
                timing.note("the form never went quiet; stopped waiting after 15 s")

    async def questions(self, page: Page, job: JobInfo) -> list[Question]:
        return await extract(page, self.container, self.label, self.description, self.ignore)

    async def confirmed(self, page: Page, timeout_ms: int = 25000) -> bool:
        return await wait_for_text(page, self.confirmation, timeout_ms)

    async def captcha_shown(self, page: Page) -> bool:
        frames = page.locator(CAPTCHA)
        return any([await frames.nth(i).is_visible() for i in range(await frames.count())])

    async def errors(self, page: Page) -> list[str]:
        """Visible validation messages (alerts and error-styled elements, not question text)."""
        found = page.locator(ERRORS).locator("visible=true")
        texts = [
            " ".join((await found.nth(i).inner_text()).split())
            for i in range(min(await found.count(), 30))
        ]
        return sorted({t for t in texts if t})[:10]

    # -- account gate: ATS sites that need a login override these (CLAUDE.md §5.5) --

    def account_tenant(self, job: JobInfo) -> str | None:
        """Which account this job needs (e.g. the employer's Workday tenant); None = no account."""
        return None

    def site_domains(self, job: JobInfo) -> list[str]:
        """Domains the verification email and its links come from."""
        host = urlparse(job.apply_url or job.url).hostname
        return [host] if host else []

    async def signed_in(self, page: Page) -> bool:
        return True

    async def two_factor_shown(self, page: Page) -> bool:
        return False

    async def login(self, page: Page, job: JobInfo, account: Account) -> None:
        """Fill and submit the login form; return once the page has settled."""
        raise NotImplementedError

    async def signup(self, page: Page, job: JobInfo, account: Account) -> None:
        """Fill and submit the sign-up form. Only the runner's `run_signup` calls this, and
        never in dry-run mode."""
        raise NotImplementedError

    async def enter_code(self, page: Page, code: str) -> None:
        raise NotImplementedError

    async def follow_link(self, page: Page, link: str) -> None:
        await goto(page, link)
