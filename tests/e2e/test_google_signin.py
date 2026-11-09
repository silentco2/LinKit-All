"""Sign in with Google on fake pages. Every request is intercepted: nothing reaches Google and no
real account is touched. Uses Google Chrome when installed, else the Chromium Playwright ships."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from playwright.async_api import Page, Route, async_playwright

from linkit_all.apply.google_signin import sign_in_with_google
from linkit_all.core.tools import chrome_path

SITE = "https://careers.acme.test/login"
HOME = "https://careers.acme.test/in"
CHOOSER = "https://accounts.google.com/o/oauth2/v2/auth"
CONSENT = "https://accounts.google.com/signin/oauth/consent"
CHALLENGE = "https://accounts.google.com/v3/signin/challenge/pwd"
LINK = f"<a href={CHOOSER}>Sign in with Google</a>"
POPUP = f"<button onclick=\"window.open('{CHOOSER}')\">Continue with Google</button>"
ROW = "<div data-identifier={0} onclick=\"location='{1}?who={0}'\">{0}</div>"
CHOOSE = ROW.format("other@gmail.com", CONSENT) + ROW.format("jane@gmail.com", CONSENT)
APPROVE = f"<button onclick=\"location='{HOME}'\">Continue</button>"


def run(pages: dict[str, str], check: Callable[[Page], Awaitable[Any]]) -> Any:
    """`check(page)` on the site's login page, with `pages` as the whole internet."""

    async def go() -> Any:
        async def handle(route: Route) -> None:
            url = route.request.url.split("?")[0]
            await route.fulfill(body=pages.get(url, "<body>site</body>"), content_type="text/html")

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(channel="chrome" if chrome_path() else None)
            except Exception:
                pytest.skip("no Chrome or Chromium available")
            context = await browser.new_context()
            await context.route("**/*", handle)
            page = await context.new_page()
            await page.goto(SITE)
            try:
                return await check(page)
            finally:
                await browser.close()

    return asyncio.run(go())


def sign_in(page: Page) -> Awaitable[str]:
    return sign_in_with_google(page, " Jane@gmail.com ", wait_s=6)


def test_same_tab_picks_the_users_account_and_continues() -> None:
    async def check(page: Page) -> tuple[str, str]:
        seen: list[str] = []
        page.on("framenavigated", lambda f: seen.append(f.url))
        result = await sign_in(page)
        return result, " ".join(seen)

    result, seen = run({SITE: LINK, CHOOSER: CHOOSE, CONSENT: APPROVE}, check)
    assert result == "signed_in"
    assert "who=jane@gmail.com" in seen and HOME in seen


def test_popup_that_closes_itself() -> None:
    close = "<div data-identifier=jane@gmail.com onclick=window.close()>Jane</div>"
    assert run({SITE: POPUP, CHOOSER: close}, sign_in) == "signed_in"


def test_a_password_box_is_left_to_the_user_and_stays_empty() -> None:
    box = "<input type=password aria-label=Password>"

    async def check(page: Page) -> tuple[str, str]:
        result = await sign_in(page)
        return result, await page.locator("input").input_value()

    assert run({SITE: LINK, CHOOSER: box}, check) == ("needs_user", "")


def test_an_email_box_means_not_signed_in() -> None:
    assert run({SITE: LINK, CHOOSER: "<input type=email>"}, sign_in) == "needs_user"


def test_a_challenge_is_left_to_the_user() -> None:
    go = f"<script>location='{CHALLENGE}'</script>"
    assert (
        run({SITE: LINK, CHOOSER: go, CHALLENGE: "<button>Next</button>"}, sign_in) == "needs_user"
    )


def test_no_google_button() -> None:
    page = "<a href=/x>Get it on Google Play</a><button>Sign in</button>"
    assert run({SITE: page}, sign_in) == "no_button"


def test_a_button_that_goes_nowhere_times_out() -> None:
    assert run({SITE: "<button>Sign in with Google</button>"}, sign_in) == "needs_user"
