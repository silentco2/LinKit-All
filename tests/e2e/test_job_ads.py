"""What the agent makes of job ads and upload widgets, on small pages. Nothing is submitted."""

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from playwright.async_api import Page, async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from test_agent_form import FakeAI, ctx, run_step

from linkit_all.apply.agent import FieldMap, open_signup, page_errors, signup_link_needed
from linkit_all.core.tools import chrome_path

pytestmark = pytest.mark.skipif(chrome_path() is None, reason="Google Chrome not installed")


class ModelSeesNoButton(FakeAI):
    """The model's real mistake: it calls the page a job ad and names no Apply button."""

    async def complete(self, prompt: str, schema: Any, *a: Any, **k: Any) -> Any:
        return FieldMap(page_kind="listing")


@asynccontextmanager
async def _page(html: str) -> AsyncIterator[Page]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        yield page
        await browser.close()


def _ad(html: str, tmp_path: Path) -> Any:
    async def go() -> Any:
        async with _page(html) as page:
            return await run_step(page, ModelSeesNoButton(), ctx(tmp_path), tmp_path)

    return asyncio.run(go())


@pytest.mark.parametrize(
    "html",
    [
        '<button>Share</button><a href="https://x.test/feedback/1">Откликнуться</a>',
        '<button>Share</button><a href="https://x.test/unete">ME INTERESA</a>',
        '<button>Share</button><a class="cta">SIGN IN TO APPLY</a>',  # no address: a script button
        '<div aria-hidden="true"><a href="https://x.test/a">Ansök nu</a></div>'  # behind a popup
        '<div role="dialog"><button>Acceptera alla</button></div>',
    ],
)
def test_an_apply_button_the_model_missed_is_still_pressed(html: str, tmp_path: Path) -> None:
    assert _ad(html, tmp_path).action == "open"


def test_a_link_with_an_address_beats_an_in_page_one(tmp_path: Path) -> None:
    r = _ad('<a href="#form">Apply now</a><a href="https://x.test/go">Apply now</a>', tmp_path)
    assert r.button.href == "https://x.test/go"


@pytest.mark.parametrize(
    ("html", "code"),
    [
        ("<button>Save</button><button>NOT ELIGIBLE</button>", "not_eligible"),
        ("<title>404 error</title><button>Login</button>", "posting_gone"),
        ("<p>This job has expired.</p><button>Login</button>", "posting_gone"),
        ("<p>A nice job.</p><button>Share</button>", "no_apply_button"),
    ],
)
def test_a_job_ad_without_apply_says_why(html: str, code: str, tmp_path: Path) -> None:
    r = _ad(html, tmp_path)
    assert (r.action, r.code) == ("stop", code)


def test_a_site_menus_apply_link_is_not_the_jobs(tmp_path: Path) -> None:
    html = """<header><a href="https://x.test/accelerator">Apply</a></header>
    <button>Share</button><a href="https://x.test/role">Apply to this role</a>"""
    assert _ad(html, tmp_path).button.href == "https://x.test/role"


def test_a_page_of_only_sign_in_and_sign_up_buttons_needs_the_link() -> None:
    html = """<input placeholder="Search jobs"><button>Sign in</button><button>Sign up</button>"""

    async def go() -> bool:
        async with _page(html) as page:
            return await signup_link_needed(page)

    assert asyncio.run(go()) is True


def test_a_real_sign_up_form_needs_no_link() -> None:
    html = """<label for="m">Email</label><input id="m" type="email"><button>Create</button>"""

    async def go() -> bool:
        async with _page(html) as page:
            return await signup_link_needed(page)

    assert asyncio.run(go()) is False


def test_a_sign_up_button_behind_a_popup_is_passed_over() -> None:
    html = """<button id="b" onclick="document.title='clicked'">SIGN UP NOW</button>
    <div style="position:fixed;inset:0;background:#fff"></div>"""

    async def go() -> tuple[bool, str]:
        async with _page(html) as page:
            return await open_signup(page), await page.title()

    assert asyncio.run(go()) == (False, "")


def test_only_real_messages_count_as_errors() -> None:
    html = """<form class="ng-invalid"><label>Email</label><input></form>
    <p class="file-error">File "cv.docx" is attached</p>
    <div class="has-error">%s</div>
    <p class="error">Enter a valid email</p>""" % ("word " * 100)

    async def go() -> list[str]:
        async with _page(html) as page:
            return await page_errors(page)

    assert asyncio.run(go()) == ["Enter a valid email"]


def test_an_upload_widget_that_empties_its_input_is_not_reported_empty(tmp_path: Path) -> None:
    html = """<form><label for="cv">Resume *</label>
    <input id="cv" type="file" required onchange="this.value=''">
    <button type="submit">Submit application</button></form>"""

    async def go() -> Any:
        async with _page(html) as page:
            return await run_step(page, FakeAI(), ctx(tmp_path), tmp_path)

    r = asyncio.run(go())
    assert r.unfilled == [] and r.failed == {}
