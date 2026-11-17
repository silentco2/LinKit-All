"""Per-ATS quirks (apply/quirks.py, A4) and how the filler honours them. The Workday case uses a
field that, like Workday's React inputs, drops a value set by script and keeps only typed keys.
Every request is intercepted. Needs Google Chrome installed."""

import asyncio

import pytest
from playwright.async_api import Route, async_playwright

from linkit_all.apply.answers import Question
from linkit_all.apply.form import fill_in
from linkit_all.apply.quirks import NONE, Quirks, host_of, quirks_for
from linkit_all.core.tools import chrome_path


@pytest.mark.parametrize(
    ("url", "quirks"),
    [
        ("https://acme.wd5.myworkdayjobs.com/en-US/External/job/X/apply", Quirks(type_keys=True)),
        ("https://wd3.myworkdaysite.com/recruiting/acme/External", Quirks(type_keys=True)),
        ("https://jobs.lever.co/acme/123/apply", Quirks(trusted_ticks_only=True)),
        ("https://jobs.ashbyhq.com/acme/123/application", Quirks(email_merge=True)),
        ("https://career5.successfactors.eu/career?company=acme", Quirks(stored_profile=True)),
        ("https://boards.greenhouse.io/acme/jobs/1", NONE),
        ("https://notmyworkdayjobs.com/x", NONE),  # a suffix, not the domain
        ("not a url", NONE),
    ],
)
def test_quirks_follow_the_form_host(url: str, quirks: Quirks) -> None:
    assert quirks_for(url) == quirks


def test_host_of() -> None:
    assert host_of("https://WWW.Example.com/a") == "example.com"
    assert host_of("") == ""


# Like Workday's React inputs: a value set without key presses is wiped on the next tick.
REACTISH = """<html><body><label for=n>Role description *</label><input id=n required>
<script>
  const n = document.getElementById('n'); let keyed = false;
  n.addEventListener('keydown', () => { keyed = true; });
  n.addEventListener('input', () => { if (!keyed) setTimeout(() => { n.value = ''; }, 0); });
</script></body></html>"""


async def _fill_on(url: str) -> str:
    async def handle(route: Route) -> None:
        if route.request.url == url:
            await route.fulfill(body=REACTISH, content_type="text/html")
        else:
            await route.abort()

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page()
        await page.route("**/*", handle)
        await page.goto(url)
        field = page.locator("#n")
        q = Question("n", "Role description", "text", True)
        try:
            await fill_in(page, field, field, q, "Built payment APIs")
        except Exception as e:
            return f"error: {e}"
        await page.wait_for_timeout(100)
        value = await field.input_value()
        await browser.close()
        return value


@pytest.mark.skipif(chrome_path() is None, reason="Google Chrome not installed")
def test_workday_fields_are_typed_so_the_value_sticks() -> None:
    assert asyncio.run(_fill_on("https://acme.wd5.myworkdayjobs.com/apply")) == "Built payment APIs"
    # elsewhere the fast fill() is kept; this field rejects it, which is what Workday does
    assert asyncio.run(_fill_on("https://careers.acme.test/apply")) == ""
