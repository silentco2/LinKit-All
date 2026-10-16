"""Generic form agent: fill an application form no ATS handler covers (CLAUDE.md §5.5).

The model only decides: it maps the page's controls to questions and names the Next and
Submit buttons (a JSON field map). Our code validates every id, answers through the same
engine as the ATS handlers (sensitive rules included) and fills. One `step()` handles one
page; it never clicks Submit, the runner's guarded `click_submit` path does.

Controls are tagged on the page: singles carry `data-lk-agent~="<id>"` themselves, groups
(radios, checkbox lists, yes/no toggles) tag their common wrapper, and the first control also
gets `data-lk-input="<id>"`, so `form.fill_in` and `form.lost_values` work unchanged.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from playwright.async_api import Page
from pydantic import BaseModel

from linkit_all.apply.answers import Context, Kind, Missing, Question
from linkit_all.apply.assist import AnswerBank, answer_questions
from linkit_all.apply.form import FillError, fill_in, lost_values
from linkit_all.apply.handlers.base import CAPTCHA, ERRORS
from linkit_all.providers.base import LLMProvider, render

_SNAPSHOT = (Path(__file__).parent / "snapshot.js").read_text("utf-8")

_PAGE_TEXT = (
    "() => (document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').slice(0, 800)"
)

_SUBMIT = re.compile(r"\b(submit|apply|send)\b", re.I)
_NEXT = re.compile(r"\b(next|continue|proceed|review|forward|save and)\b", re.I)
_TEXTUAL = {"text", "textarea", "email", "tel", "number", "url", "date"}
_STRUCTURAL = {"select", "radio", "multi", "checkbox", "yesno", "file", "combobox"}


class AgentError(RuntimeError):
    pass


@dataclass
class Control:
    id: str
    kind: str  # a Question kind, or button | password
    name: str  # accessible name, or the question text found above a group
    required: bool = False
    options: list[str] = field(default_factory=list)
    value: str = ""
    empty: bool = True
    html_name: str = ""  # html name/id, used to spot standard fields
    type: str = ""  # html type; for buttons: submit | button

    @property
    def submit_like(self) -> bool:
        """Looks like the final Submit: says so, or is a submit button not saying Next."""
        if self.kind != "button":
            return False
        return bool(_SUBMIT.search(self.name)) or (
            self.type == "submit" and not _NEXT.search(self.name)
        )


async def snapshot(page: Page) -> list[Control]:
    """Visible, enabled form controls in page order (open shadow roots included; iframes
    are not entered). Tags them on the page and keeps ids stable across calls."""
    raw: list[dict[str, Any]] = await page.evaluate(_SNAPSHOT)
    return [Control(**r) for r in raw]


# --- the model's field map ---------------------------------------------------------------


class FieldSpec(BaseModel):
    id: str
    question: str
    kind: Kind
    required: bool = False


class FieldMap(BaseModel):
    page_kind: Literal["form", "review", "confirmation", "login", "signup", "other"] = "form"
    fields: list[FieldSpec] = []
    next_button: str | None = None
    submit_button: str | None = None


def clean_map(fmap: FieldMap, controls: list[Control]) -> FieldMap:
    """Trust nothing from the model: unknown ids and buttons-as-fields are dropped, Next and
    Submit must be buttons that exist, and one button is never both (it counts as Submit)."""
    by_id = {c.id: c for c in controls}
    fields, seen = [], set[str]()
    for f in fmap.fields:
        c = by_id.get(f.id)
        if c is not None and c.kind != "button" and f.id not in seen:
            seen.add(f.id)
            fields.append(f)

    def button(i: str | None) -> str | None:
        return i if i is not None and i in by_id and by_id[i].kind == "button" else None

    nxt, sub = button(fmap.next_button), button(fmap.submit_button)
    if nxt == sub:
        nxt = None
    return FieldMap(page_kind=fmap.page_kind, fields=fields, next_button=nxt, submit_button=sub)


async def field_map(
    provider: LLMProvider, controls: list[Control], page_title: str, page_text: str = ""
) -> FieldMap:
    prompt = render("form_map.j2", controls=controls, title=page_title, page_text=page_text)
    return clean_map(await provider.complete(prompt, FieldMap), controls)


def to_questions(controls: list[Control], fmap: FieldMap) -> list[Question]:
    """Questions for the answer engine. The model's label is used, but the page's own text is
    kept as the description, so a renamed sensitive question is still caught by its rules.
    Controls the model left out are asked only when the page requires them."""
    specs = {f.id: f for f in fmap.fields}
    out = []
    for c in controls:
        if c.kind in ("button", "password"):
            continue
        spec = specs.get(c.id)
        if spec is None and not c.required:
            continue
        label = (spec.question.strip() if spec else "") or c.name or c.html_name
        if not label:
            continue
        kind: Kind = c.kind  # type: ignore[assignment]  # structural kinds come from the page
        if c.kind in _TEXTUAL and spec is not None and spec.kind in _TEXTUAL:
            kind = spec.kind
        out.append(
            Question(
                key=c.id,
                label=label,
                kind=kind,
                required=c.required or bool(spec and spec.required),
                options=c.options,
                name=c.html_name,
                description="" if _norm(c.name) == _norm(label) else c.name,
            )
        )
    return out


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


# --- acting on the page ------------------------------------------------------------------


async def _fill(page: Page, q: Question, value: Any) -> None:
    box = page.locator(f'[data-lk-agent~="{q.key}"]').first
    await fill_in(page, box, page.locator(f'[data-lk-input="{q.key}"]'), q, value)


async def fill_page(
    page: Page, questions: list[Question], answers: dict[str, Any]
) -> dict[str, str]:
    """Fill every answered question through `form.fill_in`. Returns {key: why} for failures."""
    failed = {}
    for q in questions:
        if q.key in answers:
            try:
                await _fill(page, q, answers[q.key])
            except FillError as e:
                failed[q.key] = str(e)
    for q in await lost_values(page, questions, answers):  # React forms can reset fields
        try:
            await _fill(page, q, answers[q.key])
            failed.pop(q.key, None)
        except FillError as e:
            failed[q.key] = str(e)
    return failed


async def page_errors(page: Page) -> list[str]:
    """Visible validation messages (same selector the ATS handlers use)."""
    found = page.locator(ERRORS).locator("visible=true")
    texts = [
        " ".join((await found.nth(i).inner_text()).split())
        for i in range(min(await found.count(), 30))
    ]
    return sorted({t for t in texts if t})[:10]


@dataclass
class StepResult:
    page_kind: str
    action: Literal["next", "submit", "stop"]
    button: Control | None = None
    reason: str = ""  # why we stopped
    questions: list[Question] = field(default_factory=list)
    answers: dict[str, Any] = field(default_factory=dict)  # question key -> value filled
    sources: dict[str, str] = field(default_factory=dict)
    missing: list[Missing] = field(default_factory=list)  # required, only the user can answer
    failed: dict[str, str] = field(default_factory=dict)  # required fields the page refused
    unfilled: list[str] = field(default_factory=list)  # required, still empty after filling
    errors: list[str] = field(default_factory=list)  # validation messages on the page
    dry_run: bool = True

    @property
    def ready(self) -> bool:
        """Safe to press the button: nothing required is open and the page shows no error."""
        return self.action != "stop" and not (
            self.missing or self.failed or self.unfilled or self.errors
        )


def pick_button(
    controls: list[Control], fmap: FieldMap
) -> tuple[Literal["next", "submit", "stop"], Control | None]:
    """("next" | "submit", button). A Next that looks like the final Submit counts as Submit.
    Without the model's choice, a lone submit-looking button is the Submit."""
    by_id = {c.id: c for c in controls if c.kind == "button"}
    nxt = by_id.get(fmap.next_button or "")
    sub = by_id.get(fmap.submit_button or "")
    if nxt is not None and nxt.submit_like:
        nxt, sub = None, sub or nxt
    if sub is not None:
        return "submit", sub
    if nxt is not None:
        return "next", nxt
    lone = [c for c in by_id.values() if c.submit_like]
    return ("submit", lone[0]) if len(lone) == 1 else ("stop", None)


async def step(
    page: Page,
    provider: LLMProvider,
    ctx: Context,
    bank: AnswerBank,
    cv: str,
    profile: str,
    job: dict[str, str],
    out_dir: Path,
    *,
    dry_run: bool = True,
) -> StepResult:
    """One page: snapshot -> map -> answer -> fill -> re-check. Never clicks anything;
    `result.button` is what the caller may press (`press_next`, or `click_submit`)."""
    if await _captcha_shown(page):
        return StepResult("other", "stop", reason="a CAPTCHA is shown: only you can solve it")
    controls = await snapshot(page)
    if not controls:
        return StepResult("other", "stop", reason="no form controls on the page")
    if any(c.kind == "password" for c in controls):
        return StepResult("login", "stop", reason="sign-in or sign-up page: needs the account flow")
    page_text: str = await page.evaluate(_PAGE_TEXT)
    fmap = await field_map(provider, controls, await page.title(), page_text)
    if fmap.page_kind not in ("form", "review"):
        return StepResult(fmap.page_kind, "stop", reason=f"page looks like: {fmap.page_kind}")

    questions = to_questions(controls, fmap)
    r = await answer_questions(questions, ctx, bank, provider, cv, profile, job, out_dir)
    failed = await fill_page(page, questions, r.answers)
    required = {q.key: q for q in questions if q.required}
    after = {c.id: c for c in await snapshot(page)}
    parked = {m.question.key for m in r.missing}
    action, button = pick_button(controls, fmap)
    result = StepResult(
        fmap.page_kind,
        action,
        button,
        "" if button else "no Next or Submit button found",
        questions,
        r.answers,
        r.sources,
        r.missing,
        {k: why for k, why in failed.items() if k in required},
        [
            required[k].label
            for k, c in after.items()
            if k in required and c.empty and k not in parked and k not in failed
        ],
        await page_errors(page),
        dry_run,
    )
    logger.info(
        "agent step: {} questions, {} missing, {} failed, next action {}",
        len(questions), len(result.missing), len(result.failed), result.action,
    )  # fmt: skip
    return result


async def press_next(page: Page, result: StepResult) -> None:
    """Navigation inside the form. Refuses Submit, and anything not ready."""
    if result.action != "next" or result.button is None:
        raise AgentError("only a Next button may be pressed here; Submit goes through click_submit")
    if not result.ready:
        raise AgentError("required answers are still open on this page")
    await page.locator(f'[data-lk-agent~="{result.button.id}"]').first.click()


async def _captcha_shown(page: Page) -> bool:
    frames = page.locator(CAPTCHA)
    return any([await frames.nth(i).is_visible() for i in range(await frames.count())])
