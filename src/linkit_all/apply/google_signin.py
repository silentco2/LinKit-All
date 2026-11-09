""" "Sign in with Google" on job sites (CLAUDE.md §5.5).

The user signs in to Google once, by hand, in the Chrome profile the form agent uses. On a site's
login or sign-up page we press its Google button, pick the user's account and press Continue on
Google's consent screen. Google's password is never typed or stored and its checks are never
solved: a password box, a two-step prompt or a challenge goes to the user.
"""

import asyncio
import re
from typing import Literal
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page

GoogleResult = Literal["signed_in", "no_button", "needs_user"]

GOOGLE_HOST = "accounts.google.com"
WAIT_S = 45  # for the whole trip through Google
_GOOGLE = r"(?:google|جوجل|غوغل)"
BUTTON = re.compile(
    rf"^\s*{_GOOGLE}\s*$"  # an icon button named just "Google"
    rf"|(?:sign|log|continue|register|join|connect|apply|create)[^.,]{{0,24}}\b{_GOOGLE}"
    rf"|(?:الدخول|المتابعة|التسجيل|متابعة)[^.,]{{0,24}}{_GOOGLE}",
    re.IGNORECASE,
)
GSI_FRAME = 'iframe[src*="accounts.google.com/gsi/button"]'  # Google's own hosted button
CONSENT = re.compile(r"^\s*(?:continue|allow|confirm|متابعة|السماح|تأكيد)\s*$", re.IGNORECASE)
SIGN_IN_BOX = 'input[type="password"]:visible, input[type="email"]:visible'


async def find_button(page: Page) -> Locator | None:
    for role in ("button", "link"):
        found = page.get_by_role(role, name=BUTTON).locator("visible=true")
        if await found.count():
            return found.first
    if await page.locator(GSI_FRAME).count():
        return page.frame_locator(GSI_FRAME).first.get_by_role("button").first
    return None


async def _on_google(g: Page, email: str) -> bool:
    """One look at a Google page: press what we may press. False = this page needs the user."""
    if "/challenge" in urlsplit(g.url).path or await g.locator(SIGN_IN_BOX).count():
        return False
    rows = g.locator("[data-identifier]")
    names = [await rows.nth(i).get_attribute("data-identifier") for i in range(await rows.count())]
    if names:
        wanted = email.strip().lower()
        await rows.nth(names.index(wanted) if wanted in names else 0).click()
        return True
    consent = g.get_by_role("button", name=CONSENT).locator("visible=true")
    if await consent.count():
        await consent.first.click()
    return True


async def sign_in_with_google(page: Page, email: str, wait_s: float = WAIT_S) -> GoogleResult:
    """Press the page's Google button and see the sign-in through, in a popup or in this tab.
    `email` picks the account when Google lists several."""
    button = await find_button(page)
    if button is None:
        return "no_button"
    popups: list[Page] = []

    def opened(popup: Page) -> None:
        popups.append(popup)

    page.context.on("page", opened)
    seen_google = False
    try:
        await button.click()
        for _ in range(int(wait_s)):
            await asyncio.sleep(1)
            g = next((p for p in popups if not p.is_closed()), page)
            try:
                if urlsplit(g.url).hostname == GOOGLE_HOST:
                    seen_google = True
                    if not await _on_google(g, email):
                        return "needs_user"
                elif g is page and (seen_google or popups):  # back on the site, or popup gone
                    return "signed_in"
            except PlaywrightError:  # the page moved on while we looked: look again
                continue
    except PlaywrightError:
        pass
    finally:
        page.context.remove_listener("page", opened)
    return "needs_user"
