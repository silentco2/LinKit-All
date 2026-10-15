"""ATS handler interface: where the form is, how to read it, what success looks like."""

import contextlib
import re
from dataclasses import dataclass
from typing import Any

from playwright.async_api import Page

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
