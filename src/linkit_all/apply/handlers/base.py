"""ATS handler interface: where the form is, how to read it, what success looks like."""

import contextlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page

from linkit_all.apply.accounts import Account, PasswordRules
from linkit_all.apply.answers import Question
from linkit_all.apply.form import extract

CAPTCHA = (
    'iframe[src*="recaptcha/api2/bframe"], iframe[src*="hcaptcha.com"][src*="challenge"], '
    'iframe[title*="challenge" i]'
)

ERRORS = "[role=alert], [class*=error i], [class*=invalid i], .application-error"


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
        await page.goto(self.form_url(job), wait_until="domcontentloaded", timeout=60000)
        await page.locator(self.container).first.wait_for(timeout=30000)
        # Let React finish hydrating, or it resets fields filled too early. Pages that
        # long-poll never go idle; the refill check after filling covers those.
        with contextlib.suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=15000)

    async def questions(self, page: Page, job: JobInfo) -> list[Question]:
        return await extract(page, self.container, self.label, self.description, self.ignore)

    async def confirmed(self, page: Page, timeout_ms: int = 25000) -> bool:
        try:
            await page.wait_for_function(
                "re => new RegExp(re, 'i').test(document.body.innerText)",
                arg=self.confirmation.pattern,
                timeout=timeout_ms,
            )
        except Exception:
            return False
        return True

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
        await page.goto(link, wait_until="domcontentloaded", timeout=60000)
