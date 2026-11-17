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

from linkit_all.apply.agent import (
    FieldMap,
    decline_cookies,
    fill_page,
    open_signup,
    page_errors,
    page_questions,
    signup_link_needed,
    snapshot,
)
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


def test_a_signup_dialog_inside_a_hidden_body_is_seen() -> None:
    """Wuzzuf (2026-11-11): Apply opens a sign-up dialog but sets aria-hidden on <body> around
    it. Its fields were dropped, so the runner said "pressing Apply opened nothing"."""
    html = """<body aria-hidden="true"><input name="q" placeholder="Search jobs">
    <div role="dialog" aria-modal="true"><label>First name <input name="firstname"></label>
    <label>Password <input type="password" name="password"></label></div></body>"""

    async def go() -> list[str]:
        async with _page(html) as page:
            return [c.html_name for c in await snapshot(page)]

    assert asyncio.run(go()) == ["firstname", "password"]


def test_an_upload_hidden_behind_its_label_button_is_read() -> None:
    # Henkel's careers site (Cornerstone), 2026-11-13: the input is aria-hidden, its label shows
    html = """<label for="cv"><input id="cv" name="resumeFileUpload" type="file" class="hidden"
    aria-hidden="true" tabindex="-1" style="display:none"><span role="button">Upload Resume/CV</span>
    </label><div style="display:none"><label>Hidden <input type="file" name="ghost"></label></div>"""

    async def go() -> list[tuple[str, str]]:
        async with _page(html) as page:
            return [(c.kind, c.html_name) for c in await snapshot(page) if c.kind == "file"]

    assert asyncio.run(go()) == [("file", "resumeFileUpload")]


def test_a_link_with_an_address_beats_an_in_page_one(tmp_path: Path) -> None:
    r = _ad('<a href="#form">Apply now</a><a href="https://x.test/go">Apply now</a>', tmp_path)
    assert r.button.href == "https://x.test/go"


@pytest.mark.parametrize(
    ("html", "code"),
    [
        ("<button>Save</button><button>NOT ELIGIBLE</button>", "not_eligible"),
        ("<title>404 error</title><button>Login</button>", "posting_gone"),
        ("<p>This job has expired.</p><button>Login</button>", "posting_gone"),
        # real closed ads, 2026-11-11: Rasan (Teamtailor), Capgemini behind a long site menu, Wuzzuf
        (
            "<h1>Dev</h1><p>This position is no longer active</p><button>Login</button>",
            "posting_gone",
        ),
        (
            "<nav>" + "<p>Egypt | EN</p>" * 80 + "</nav><h1>This job is no longer available</h1>"
            "<button>Search</button>",
            "posting_gone",
        ),
        (
            "<span>Closed</span><h1>Dev</h1><p>Full Time</p><button>Browse Similar Jobs</button>",
            "posting_gone",
        ),
        ("<p>Closed-loop control for Dev teams.</p><button>Share</button>", "no_apply_button"),
        # Merck's careers site, 2026-11-13: try again later, not a dead end
        (
            "<nav>Jobs</nav><p>Site is under maintenance. Please try again after some time.</p>"
            "<button>Cookie Settings</button>",
            "site_down",
        ),
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
    <p class="error">Enter a valid email</p>
    <span class="required-error">*</span>
    <div class="[&>.field-with-errors]:w-auto"><label>I agree to the Privacy Policy</label></div>
    """ % ("word " * 100)  # Henkel (CSOD) marks with "*"; Teamtailor styles fields with Tailwind

    async def go() -> list[str]:
        async with _page(html) as page:
            return await page_errors(page)

    assert asyncio.run(go()) == ["Enter a valid email"]


def test_a_cookie_banner_is_declined_and_nothing_else_is() -> None:
    html = """<fieldset><legend>Gender</legend><button onclick="window.eeo=1">Decline</button>
    </fieldset><div id="cb"><p>We and our partners use cookies.</p>
    <button onclick="window.pick='accept'">Accept all</button>
    <button onclick="window.pick='decline'">Disagree and close</button></div>"""

    async def go() -> tuple[str | None, Any, Any]:
        async with _page(html) as page:
            pressed = await decline_cookies(page)
            return pressed, await page.evaluate("window.pick"), await page.evaluate("window.eeo")

    assert asyncio.run(go()) == ("Disagree and close", "decline", None)


def test_a_progress_note_is_waited_out_and_never_an_error() -> None:
    # Henkel parses the uploaded CV and says so in an alert box; the real error shows after it
    html = """<div role="alert" id="n">Processing Resume/CV. This could take several seconds.</div>
    <script>setTimeout(() => { n.textContent = 'Phone is invalid'; }, 1500)</script>"""

    async def go() -> list[str]:
        async with _page(html) as page:
            return await page_errors(page, busy_wait_s=10)

    assert asyncio.run(go()) == ["Phone is invalid"]


def test_a_field_the_site_resets_after_reading_the_cv_is_filled_again(tmp_path: Path) -> None:
    # Henkel scans the uploaded CV and then empties Country; filling waits for it and refills
    html = """<label for="city">City</label><input id="city">
    <label for="country">Country</label><select id="country"><option value="">Please Select</option>
    <option value="EGY">Egypt</option></select>
    <label for="cv">Resume</label><input id="cv" type="file" onchange="busy()">
    <div role="alert" id="n"></div>
    <script>function busy() {
      n.textContent = 'Processing Resume/CV. This could take several seconds.';
      setTimeout(() => { city.value = ''; country.value = ''; n.textContent = ''; }, 1500);
    }</script>"""
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")

    async def go() -> tuple[str, str]:
        async with _page(html) as page:
            qs = page_questions(await snapshot(page))
            by = {q.label: q.key for q in qs}
            answers = {by["City"]: "Cairo", by["Country"]: "Egypt", by["Resume"]: str(cv)}
            await fill_page(page, qs, answers)
            return await page.input_value("#city"), await page.input_value("#country")

    assert asyncio.run(go()) == ("Cairo", "EGY")


def test_an_upload_widget_that_empties_its_input_is_not_reported_empty(tmp_path: Path) -> None:
    html = """<form><label for="cv">Resume *</label>
    <input id="cv" type="file" required onchange="this.value=''">
    <button type="submit">Submit application</button></form>"""

    async def go() -> Any:
        async with _page(html) as page:
            return await run_step(page, FakeAI(), ctx(tmp_path), tmp_path)

    r = asyncio.run(go())
    assert r.unfilled == [] and r.failed == {}
