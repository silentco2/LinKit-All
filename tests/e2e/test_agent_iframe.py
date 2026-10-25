"""Generic form agent on forms embedded in iframes, same-origin and cross-origin. Every request is
intercepted: nothing leaves the machine and nothing is ever submitted. Uses Google Chrome when
installed, else the Chromium Playwright ships."""

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from playwright.async_api import Browser, Page, Route, async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from test_agent_form import FakeAI, by_name, ctx, run, run_step

from linkit_all.apply.agent import captcha_shown, locate, press_next, snapshot
from linkit_all.apply.runner import DryRunViolation, click_submit
from linkit_all.core.tools import chrome_path

FIXTURES = Path(__file__).parents[1] / "fixtures/agent"
PARENT = (FIXTURES / "iframe_parent.html").read_text("utf-8")
FORM = (FIXTURES / "iframe_form.html").read_text("utf-8")
HIDDEN = (FIXTURES / "iframe_hidden.html").read_text("utf-8")
PAGE_URL = "https://careers.acme.test/apply"
SAME = "https://careers.acme.test/embed"
CROSS = "https://boards.otherats.test/embed"
HIDDEN_URL = "https://careers.acme.test/hidden"
RECAPTCHA = "https://www.google.com/recaptcha/api2/bframe"
CHALLENGE = (
    "<body><input type=checkbox aria-label='I am not a robot'><button>Verify</button></body>"
)


@asynccontextmanager
async def open_page(pages: dict[str, str]) -> AsyncIterator[Page]:
    async def handle(route: Route) -> None:
        body = pages.get(route.request.url)
        if route.request.method == "POST" or body is None:
            await route.abort()
        else:
            await route.fulfill(body=body, content_type="text/html")

    async with async_playwright() as p:
        browser: Browser
        try:
            browser = await p.chromium.launch(channel="chrome" if chrome_path() else None)
        except Exception:
            pytest.skip("no Chrome or Chromium available")
        page = await browser.new_page()
        await page.route("**/*", handle)
        await page.goto(PAGE_URL)
        await page.wait_for_load_state("load")
        try:
            yield page
        finally:
            await browser.close()


def site(embed: str) -> dict[str, str]:
    html = PARENT.replace("__SRC__", embed).replace("__HIDDEN__", HIDDEN_URL)
    return {PAGE_URL: html, embed: FORM, HIDDEN_URL: HIDDEN}


@pytest.fixture(params=[SAME, CROSS], ids=["same-origin", "cross-origin"])
def embed(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def test_snapshot_lists_controls_of_the_page_and_the_iframe(embed: str) -> None:
    async def go() -> None:
        async with open_page(site(embed)) as page:
            controls = await snapshot(page)
            assert [c.name for c in controls] == [
                "Referral code",
                "Full name",
                "Email",
                "Country",
                "Why do you want to work here?",
                "Submit application",
            ]  # the hidden and off-screen helper frames are not read
            assert len({c.id for c in controls}) == len(controls)
            assert not by_name(controls, "Referral code").id.startswith("f")  # main frame: plain id
            assert by_name(controls, "Full name").id.startswith("f")
            assert by_name(controls, "Full name").required
            assert by_name(controls, "Country").options == [
                "Egypt",
                "United Kingdom",
                "United States",
            ]
            assert controls == await snapshot(page)  # ids stay stable

    run(go())


def test_step_fills_inside_the_iframe_and_dry_run_never_clicks_submit(
    embed: str, tmp_path: Path
) -> None:
    async def go() -> None:
        async with open_page(site(embed)) as page:
            r = await run_step(page, FakeAI(), ctx(tmp_path), tmp_path, dry_run=True)
            assert (r.action, r.button.name if r.button else None) == (
                "submit",
                "Submit application",
            )
            assert r.ready, (r.missing, r.unfilled, r.failed, r.errors)
            frame = next(f for f in page.frames if f.url == embed)
            assert await frame.input_value("#full_name") == "Jane Doe"
            assert await frame.input_value("#email") == "jane@example.com"
            assert await frame.input_value("#country") == "United Kingdom"
            assert await frame.input_value("#why") == "Because I build backend systems."
            assert await page.input_value("#referral") != ""  # the page's own control too
            assert r.button is not None
            with pytest.raises(DryRunViolation):
                await click_submit(page, await locate(page, r.button.id), dry_run=True)
            assert await frame.evaluate("window.submitted || 0") == 0
            # the guard is what stops it: with it off, the same locator clicks inside the frame
            await click_submit(page, await locate(page, r.button.id), dry_run=False)
            assert await frame.evaluate("window.submitted") == 1

    run(go())


def test_press_next_refuses_submit_inside_an_iframe(embed: str, tmp_path: Path) -> None:
    async def go() -> None:
        async with open_page(site(embed)) as page:
            r = await run_step(page, FakeAI(), ctx(tmp_path), tmp_path)
            with pytest.raises(Exception, match="Submit goes through click_submit"):
                await press_next(page, r)

    run(go())


def test_captcha_frame_is_never_read_and_still_parks(tmp_path: Path) -> None:
    async def go() -> None:
        pages = site(SAME)
        pages[PAGE_URL] = pages[PAGE_URL].replace(
            "</body>", f'<iframe src="{RECAPTCHA}" width=300 height=300></iframe></body>'
        )
        pages[RECAPTCHA] = CHALLENGE
        async with open_page(pages) as page:
            assert await captcha_shown(page)
            names = [c.name for c in await snapshot(page)]
            assert "I am not a robot" not in names and "Verify" not in names
            assert "Full name" in names  # the form beside it is still read
            r = await run_step(page, FakeAI(), ctx(tmp_path), tmp_path)
            assert (r.action, r.answers) == ("stop", {})
            assert "CAPTCHA" in r.reason
            frame = next(f for f in page.frames if f.url == SAME)
            assert await frame.input_value("#full_name") == ""  # nothing touched

    run(go())


def test_captcha_inside_the_form_iframe_still_parks(tmp_path: Path) -> None:
    async def go() -> None:
        pages = site(SAME)
        pages[SAME] = FORM.replace(
            "</body>", f'<iframe src="{RECAPTCHA}" width=300 height=300></iframe></body>'
        )
        pages[RECAPTCHA] = CHALLENGE
        async with open_page(pages) as page:
            assert await captcha_shown(page)
            assert "Verify" not in [c.name for c in await snapshot(page)]
            r = await run_step(page, FakeAI(), ctx(tmp_path), tmp_path)
            assert (r.action, r.answers) == ("stop", {})

    run(go())


def test_no_captcha_means_none_shown(embed: str) -> None:
    async def go() -> None:
        async with open_page(site(embed)) as page:
            assert not await captcha_shown(page)

    run(go())
