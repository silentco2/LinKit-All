"""Required-field sweep (apply/agent step, A2): fields a fill reveals are surveyed, answered and
filled before the page counts as ready, and a select still on its "Select..." placeholder counts
as empty. Every request is intercepted; nothing is submitted. Needs Google Chrome installed."""

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from playwright.async_api import Page, Route, async_playwright

sys.path.insert(0, str(Path(__file__).parents[1] / "e2e"))
from test_agent_form import FakeAI, ctx, run, run_step

from linkit_all.apply.agent import snapshot
from linkit_all.core.tools import chrome_path

pytestmark = pytest.mark.skipif(chrome_path() is None, reason="Google Chrome not installed")

URL = "https://forms.test/apply"
HTML = (Path(__file__).parents[1] / "fixtures/agent/reveal_on_answer.html").read_text("utf-8")


@asynccontextmanager
async def open_form() -> AsyncIterator[Page]:
    async def handle(route: Route) -> None:
        if route.request.url == URL and route.request.method == "GET":
            await route.fulfill(body=HTML, content_type="text/html")
        else:
            await route.abort()

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page()
        await page.route("**/*", handle)
        await page.goto(URL)
        try:
            yield page
        finally:
            await browser.close()


def test_fields_revealed_by_an_answer_are_filled_not_missed(tmp_path: Path) -> None:
    async def go() -> None:
        async with open_form() as page:
            r = await run_step(page, FakeAI(), ctx(tmp_path), tmp_path, dry_run=True)
            assert await page.is_checked("input[name=licence][value=yes]")
            assert await page.input_value("#years_held") != ""  # revealed, then answered
            assert await page.eval_on_selector("#category", "e => e.selectedIndex") > 0
            labels = [q.label for q in r.questions]
            assert "How many years have you held it?" in labels
            assert "Licence category" in labels
            assert r.ready, (r.missing, r.unfilled, r.failed, r.errors)
            assert await page.evaluate("window.submitted") == 0

    run(go())


def test_a_select_on_its_placeholder_counts_as_empty() -> None:
    async def go() -> None:
        async with open_form() as page:
            await page.check("input[name=licence][value=yes]")
            await page.locator("#category").wait_for()
            category = next(c for c in await snapshot(page) if c.html_name == "category")
            assert category.empty and category.value == ""
            assert "Select..." not in category.options
            await page.select_option("#category", label="B (car)")
            category = next(c for c in await snapshot(page) if c.html_name == "category")
            assert not category.empty and category.value == "B (car)"

    run(go())
