"""session_state against fake LinkedIn pages served through Playwright routes: nothing leaves the
machine. Uses installed Chrome, else Playwright's Chromium."""

import asyncio
import glob
from typing import Any

import pytest
from playwright.async_api import Route, async_playwright

from linkit_all.core.tools import chrome_path
from linkit_all.sources.linkedin_posts.session import session_state

PW_CHROMIUM = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))
pytestmark = pytest.mark.skipif(
    chrome_path() is None and not PW_CHROMIUM, reason="no Chrome or Chromium available"
)


async def state_for(redirect_to: str | None, body: str) -> str:
    async def handle(route: Route) -> None:
        if redirect_to and "/feed" in route.request.url:
            # a script redirect: Playwright cannot serve the redirect target of a fulfilled 302
            js = f"<script>location.replace({redirect_to!r})</script>"
            await route.fulfill(status=200, content_type="text/html", body=js)
        else:
            await route.fulfill(
                status=200, content_type="text/html", body=f"<html><body>{body}</body></html>"
            )

    async with async_playwright() as pw:
        kw: dict[str, Any] = (
            {"channel": "chrome"} if chrome_path() else {"executable_path": PW_CHROMIUM[-1]}
        )
        browser = await pw.chromium.launch(
            headless=True, args=["--no-sandbox", "--no-proxy-server"], **kw
        )
        try:
            page = await browser.new_page()
            await page.route("https://www.linkedin.com/**", handle)
            return await session_state(page)
        finally:
            await browser.close()


def test_logged_out_redirect() -> None:
    url = "https://www.linkedin.com/login?session_redirect=feed"
    assert asyncio.run(state_for(url, "<form></form>")) == "logged_out"


def test_authwall() -> None:
    assert asyncio.run(state_for("https://www.linkedin.com/authwall?x=1", "join")) == "logged_out"


def test_checkpoint() -> None:
    url = "https://www.linkedin.com/checkpoint/challenge/1"
    assert asyncio.run(state_for(url, "check")) == "challenge"


def test_challenge_text_on_feed_url() -> None:
    body = "<h1>Let's do a quick security check</h1>"
    assert asyncio.run(state_for(None, body)) == "challenge"


def test_feed_ok() -> None:
    body = '<nav class="global-nav">home</nav><main>feed</main>'
    assert asyncio.run(state_for(None, body)) == "ok"
