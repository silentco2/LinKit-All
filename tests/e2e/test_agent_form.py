"""Generic form agent on saved forms. Every request is intercepted: nothing leaves the machine
and nothing is ever submitted. Needs Google Chrome installed."""

import asyncio
import json
import re
import sys
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TypeVar

import pymupdf
import pytest
from playwright.async_api import Page, Route, async_playwright

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_matching import fake_embed

from linkit_all.apply.agent import (
    AgentError,
    Control,
    page_errors,
    press_next,
    snapshot,
    step,
)
from linkit_all.apply.answers import ApplicationAnswers, Context
from linkit_all.apply.assist import AnswerBank
from linkit_all.core.db import init_db
from linkit_all.core.tools import chrome_path
from linkit_all.providers.base import LLMProvider

pytestmark = pytest.mark.skipif(chrome_path() is None, reason="Google Chrome not installed")

FIXTURES = Path(__file__).parents[1] / "fixtures"
PAGES = {
    "lever": FIXTURES / "lever/apply_form.html",
    "greenhouse": FIXTURES / "agent/greenhouse.html",
    "ashby": FIXTURES / "agent/ashby.html",
    "synthetic": FIXTURES / "agent/synthetic_two_page.html",
}
URL = "https://forms.test/apply"
T = TypeVar("T")

_CONTROL = re.compile(r'^- id: (\w+) \| (\w+)((?: \| \w+)*)\n  name: (".*")$', re.M)
_QUESTION = re.compile(r"^- key: (\w+) \| (\w+).*\n  question: (.*)$", re.M)


class FakeAI(LLMProvider):
    """Maps every control the way a careful model would; answers every question it is asked."""

    name = "fake"

    def __init__(
        self, *, rename: dict[str, str] | None = None, bogus: bool = False, kind: str = "form"
    ) -> None:
        super().__init__("fake")
        self.rename, self.bogus, self.page_kind = rename or {}, bogus, kind
        self.asked: list[str] = []  # question labels that reached the answer prompt

    async def _call(self, prompt: str) -> str:
        if "You help fill in a job application form" in prompt:
            return json.dumps(self._map(prompt))
        out = []
        for key, kind, label in _QUESTION.findall(prompt):
            self.asked.append(label)
            opts = re.search(rf"- key: {key} .*\n  question: .*\n  options: (.*)", prompt)
            answer: Any = "Because I build backend systems."
            if opts and "long list" not in opts.group(1):
                first = opts.group(1).split(" || ")[0]
                answer = [first] if kind == "multi" else first
            elif kind == "checkbox":
                answer = True
            out.append({"key": key, "known": True, "answer": answer})
        return json.dumps({"answers": out})

    def _map(self, prompt: str) -> dict[str, Any]:
        fields, nxt, sub = [], None, None
        for cid, kind, extra, quoted in _CONTROL.findall(prompt):
            name = json.loads(quoted)
            if kind == "button":
                if re.search(r"next", name, re.I):
                    nxt = cid
                elif re.search(r"submit", name, re.I):
                    sub = cid
                continue
            for needle, new in self.rename.items():
                if needle in name:
                    name = new
            fields.append(
                {"id": cid, "question": name, "kind": kind, "required": "required" in extra}
            )
        if self.bogus:
            fields.append({"id": "zz9", "question": "Mystery", "kind": "text", "required": True})
            sub = sub or "zz8"
        return {
            "page_kind": self.page_kind,
            "fields": fields,
            "next_button": nxt,
            "submit_button": sub,
        }


def run(coro: Awaitable[T]) -> T:
    async def go() -> T:
        return await coro

    return asyncio.run(go())


@asynccontextmanager
async def open_page(name: str, posts: list[str] | None = None) -> AsyncIterator[Page]:
    html = PAGES[name].read_text("utf-8")

    async def handle(route: Route) -> None:
        req = route.request
        if req.method == "POST":
            (posts if posts is not None else []).append(req.url)
            await route.abort()
        elif req.url == URL:
            await route.fulfill(body=html, content_type="text/html")
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


def ctx(tmp_path: Path, **answers: Any) -> Context:
    pdf = tmp_path / "resume.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Jane Doe")
    doc.save(str(pdf))
    base = {"authorized_countries": ["United States", "United Kingdom"], "needs_sponsorship": False,
            "years_experience": 3}  # fmt: skip
    return Context(
        full_name="Jane Doe",
        email="jane@example.com",
        phone="+44 20 0000 0000",
        location="London",
        answers=ApplicationAnswers(**{**base, **answers}),
        job_location="London",
        resume_path=str(pdf),
    )


def bank(tmp_path: Path) -> AnswerBank:
    return AnswerBank(init_db(tmp_path / "t.db"), fake_embed)


async def run_step(page: Page, ai: FakeAI, c: Context, tmp_path: Path, **kw: Any) -> Any:
    return await step(
        page,
        ai,
        c,
        bank(tmp_path),
        "CV text",
        "profile",
        {"title": "Dev", "company": "Acme", "description": "Python APIs"},
        tmp_path,
        **kw,
    )


# --- snapshot -----------------------------------------------------------------------------


def by_name(controls: list[Control], start: str) -> Control:
    return next(c for c in controls if c.name.startswith(start))


def test_snapshot_lever_finds_controls_and_required_flags() -> None:
    async def go() -> list[Control]:
        async with open_page("lever") as page:
            return await snapshot(page)

    controls = run(go())
    assert len({c.id for c in controls}) == len(controls)
    assert not any(c.html_name in ("selectedLocation", "h-captcha-response") for c in controls)
    assert by_name(controls, "Full name").required and by_name(controls, "Email").required
    assert not by_name(controls, "Phone").required
    assert by_name(controls, "Current location").required
    langs = by_name(controls, "Language Skill")
    assert (langs.kind, langs.required, len(langs.options)) == ("multi", True, 33)
    auth = by_name(controls, "Are you legally authorized")
    assert (auth.kind, auth.options, auth.required) == ("radio", ["Yes", "No"], True)
    assert by_name(controls, "Which university").kind == "select"
    assert by_name(controls, "Resume/CV").kind == "file"
    consent = by_name(controls, "Palantir Technologies has my consent")
    assert (consent.kind, consent.required) == ("checkbox", False)
    submits = [c for c in controls if c.submit_like]  # the empty hidden helper button is dropped
    assert [c.name for c in submits] == ["Submit application"]


def test_snapshot_other_real_forms() -> None:
    async def go() -> tuple[list[Control], list[Control]]:
        async with open_page("ashby") as page:
            ashby = await snapshot(page)
        async with open_page("greenhouse") as page:
            return ashby, await snapshot(page)

    ashby, greenhouse = run(go())
    # Ashby: a Yes/No toggle pair is one control (its hidden mirror checkbox is dropped)
    toggles = [c for c in ashby if c.kind == "yesno"]
    assert [(c.options, c.required) for c in toggles] == [(["Yes", "No"], True)]
    assert not any(c.html_name == "question_10174619004" for c in ashby)
    assert [c.name for c in ashby if c.kind == "radio" and c.name in ("Gender", "Race")] == [
        "Gender",
        "Race",
    ]
    assert by_name(ashby, "How did you hear").kind == "multi"
    # Greenhouse: react-select dropdowns are comboboxes, the privacy notice is a required checkbox
    assert (
        by_name(greenhouse, "Country").kind == "combobox"
        and by_name(greenhouse, "Country").required
    )
    ack = by_name(greenhouse, "I acknowledge receipt")
    assert (ack.kind, ack.required) == ("checkbox", True)
    assert [c.name for c in greenhouse if c.submit_like] == ["Submit application"]


def test_snapshot_skips_honeypot_and_keeps_ids_stable() -> None:
    async def go() -> tuple[list[Control], list[Control]]:
        async with open_page("synthetic") as page:
            first = await snapshot(page)
            return first, await snapshot(page)

    first, second = run(go())
    assert [c.name for c in first] == ["Full name", "Email", "Phone", "Country", "Next"]
    assert first == second


# --- steps --------------------------------------------------------------------------------


def test_two_page_form_next_then_submit_without_clicking_submit(tmp_path: Path) -> None:
    async def go() -> None:
        ai, c = FakeAI(), ctx(tmp_path)
        async with open_page("synthetic") as page:
            # validation: pressing Next on an empty page shows an error, which clears once filled
            await page.locator("#next").click()
            assert await page_errors(page) == ["Please fill in all required fields."]

            r1 = await run_step(page, ai, c, tmp_path, dry_run=True)
            assert (r1.action, r1.button.name if r1.button else None) == ("next", "Next")
            assert r1.ready and not r1.missing and not r1.unfilled and not r1.errors
            assert await page.input_value("#full_name") == "Jane Doe"
            assert await page.input_value("#email") == "jane@example.com"
            assert await page.input_value("#phone") == "+44 20 0000 0000"
            assert await page.input_value("#country") == "United Kingdom"
            assert await page.input_value("#website_url") == ""  # honeypot untouched
            await press_next(page, r1)
            await page.locator("#page2").wait_for(state="visible")

            r2 = await run_step(page, ai, c, tmp_path, dry_run=True)
            assert (r2.action, r2.button.name if r2.button else None) == (
                "submit",
                "Submit application",
            )
            assert r2.ready, (r2.missing, r2.unfilled, r2.failed, r2.errors)
            assert await page.input_value("#why") == "Because I build backend systems."
            assert await page.is_checked(
                "input[name=auth][value=yes]"
            )  # from the profile, not the AI
            assert await page.is_checked("#remote")
            with pytest.raises(AgentError):
                await press_next(page, r2)  # Submit is never pressed by the agent
            assert await page.evaluate("window.submitted") == 0

    run(go())


def test_sensitive_question_is_parked_not_answered_by_the_ai(tmp_path: Path) -> None:
    async def go() -> None:
        # The model even renames the question to hide what it is asking.
        ai = FakeAI(rename={"legally authorized": "Additional information"})
        c = ctx(tmp_path, authorized_countries=[])
        async with open_page("synthetic") as page:
            await page.evaluate(
                "document.getElementById('page1').hidden = true; document.getElementById('page2').hidden = false"
            )
            r = await run_step(page, ai, c, tmp_path)
            assert [m.sensitive for m in r.missing] == [True]
            assert r.missing[0].question.kind == "radio"
            assert not r.ready
            assert not any("authorized" in q or "Additional information" in q for q in ai.asked)
            assert not await page.is_checked("input[name=auth][value=yes]")
            assert not await page.is_checked("input[name=auth][value=no]")
            assert await page.input_value("#why") == "Because I build backend systems."

    run(go())


def test_unknown_ids_from_the_model_are_dropped(tmp_path: Path) -> None:
    async def go() -> None:
        ai = FakeAI(bogus=True)
        async with open_page("synthetic") as page:
            r = await run_step(page, ai, ctx(tmp_path), tmp_path)
            assert "zz9" not in {q.key for q in r.questions}
            assert (r.action, r.ready) == ("next", True)

    run(go())


def test_stops_on_login_and_confirmation_pages(tmp_path: Path) -> None:
    async def go() -> None:
        async with open_page("synthetic") as page:
            r = await run_step(page, FakeAI(kind="confirmation"), ctx(tmp_path), tmp_path)
            assert (r.action, r.page_kind, r.answers) == ("stop", "confirmation", {})
            assert await page.input_value("#full_name") == ""  # nothing touched
            await page.evaluate(
                "document.body.insertAdjacentHTML('beforeend', '<input type=password id=pw aria-label=Password>')"
            )
            r = await run_step(page, FakeAI(), ctx(tmp_path), tmp_path)
            assert (r.action, r.page_kind) == ("stop", "login")

    run(go())


def test_real_lever_form_fills_and_parks_the_notetaker_question(tmp_path: Path) -> None:
    async def go() -> None:
        posts: list[str] = []
        ai = FakeAI()
        async with open_page("lever", posts) as page:
            r = await run_step(page, ai, ctx(tmp_path), tmp_path)
            assert (r.action, r.button.name if r.button else None) == (
                "submit",
                "Submit application",
            )
            # AI-notetaker consent is a sensitive question: parked, never sent to the AI
            assert any("notetakers" in m.question.label for m in r.missing)
            assert not any("notetakers" in q for q in ai.asked)
            assert not r.ready and not r.failed, r.failed
            assert await page.input_value("input[name=name]") == "Jane Doe"
            assert await page.input_value("input[name=location]") == "London"
            assert await page.is_checked(
                "input[name$='[field0]'][value=Yes] >> nth=0"
            )  # authorized, from profile
            assert await page.locator("input[name=resume]").evaluate("e => e.files.length") == 1
            assert await page.is_checked(
                "input[name='cards[a69a985a-eae9-4c14-90fb-b5a4b891523e][field0]'][value='English (ENG)']"
            )
            assert not await page.is_checked("input[name='consent[marketing]'][type=checkbox]")
        assert posts == []

    run(go())
