"""Generic form agent: fill an application form no ATS handler covers (CLAUDE.md §5.5).

The model only decides: it maps the page's controls to questions and names the Next and
Submit buttons (a JSON field map). Our code validates every id, answers through the same
engine as the ATS handlers (sensitive rules included) and fills. One `step()` handles one
page; it never clicks Submit, the runner's guarded `click_submit` path does.

Controls are tagged on the page: singles carry `data-lk-agent~="<id>"` themselves, groups
(radios, checkbox lists, yes/no toggles) tag their common wrapper, and the first control also
gets `data-lk-input="<id>"`, so `form.fill_in` and `form.lost_values` work unchanged.

Forms inside iframes (same- or cross-origin) are read the same way, one frame at a time. Ids
carry a per-frame prefix so they stay unique page-wide, and `locate` finds the frame a tagged
control lives in. CAPTCHA frames are never read: they only park the job.
"""

import asyncio
import contextlib
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, cast, get_args
from weakref import WeakKeyDictionary

from loguru import logger
from playwright.async_api import Frame, Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeout
from pydantic import BaseModel

from linkit_all.apply.answers import (
    Context,
    Kind,
    Missing,
    Question,
    remember_secrets,
    scrub,
    secrets_seen,
)
from linkit_all.apply.assist import AnswerBank, answer_questions, remember_bank_secrets
from linkit_all.apply.form import FillError, fill_in, lost_values
from linkit_all.apply.handlers.base import CAPTCHA, ERRORS
from linkit_all.providers.base import LLMProvider, render

_SNAPSHOT = (Path(__file__).parent / "snapshot.js").read_text("utf-8")

_BODY_TEXT = "() => (document.body ? document.body.innerText : '')"

# ponytail: the page plus 3 levels of iframes, 12 frames in all; deeper or more embeds are not read.
_MAX_DEPTH = 3
_MAX_FRAMES = 12
_CAPTCHA_FRAME = re.compile(r"captcha|turnstile|challenges\.cloudflare\.com", re.I)
_prefixes: WeakKeyDictionary[Frame, str] = WeakKeyDictionary()

_SUBMIT = re.compile(r"\b(submit|apply|send)\b", re.I)
_NEXT = re.compile(r"\b(next|continue|proceed|review|forward|save and)\b", re.I)
_TEXTUAL = {"text", "textarea", "email", "tel", "number", "url", "date"}


class AgentError(RuntimeError):
    pass


@dataclass
class Control:
    id: str
    kind: str  # a Question kind, or button | link | password
    name: str  # accessible name, or the question text found above a group
    required: bool = False
    options: list[str] = field(default_factory=list)
    value: str = ""
    empty: bool = True
    html_name: str = ""  # html name/id, used to spot standard fields
    type: str = ""  # html type; for buttons: submit | button
    href: str = ""  # links only: where an Apply link goes
    apply: bool = False  # a button or link worded like Apply (snapshot.js)

    @property
    def submit_like(self) -> bool:
        """Looks like the final Submit: says so, or is a submit button not saying Next."""
        if self.kind != "button":
            return False
        return bool(_SUBMIT.search(self.name)) or (
            self.type == "submit" and not _NEXT.search(self.name)
        )


# --- frames ------------------------------------------------------------------------------


async def _frame_shown(frame: Frame) -> bool:
    """The iframe element is rendered and not parked far off-screen (hidden helper frames)."""
    try:
        el = await frame.frame_element()
        box = await el.bounding_box()
        return (
            await el.is_visible()
            and box is not None
            and box["x"] + box["width"] > 0
            and box["x"] < 20000
        )
    except Exception:  # detached or navigating
        return False


async def _walk(frame: Frame, depth: int, out: list[Frame]) -> None:
    out.append(frame)
    if depth >= _MAX_DEPTH:
        return
    for child in frame.child_frames:
        if len(out) >= _MAX_FRAMES:
            return
        if child.is_detached() or _CAPTCHA_FRAME.search(child.url) or not await _frame_shown(child):
            continue
        await _walk(child, depth + 1, out)


async def frames_of(page: Page) -> list[Frame]:
    """The main frame and the visible child frames worth reading, parents first. CAPTCHA
    frames are left out: their controls are never ours to touch."""
    out: list[Frame] = []
    await _walk(page.main_frame, 0, out)
    return out


def _prefix(frame: Frame) -> str:
    """Id prefix of a frame: none for the main frame, so single-frame pages are unchanged."""
    if frame.parent_frame is None:
        return ""
    return _prefixes.setdefault(frame, f"f{len(_prefixes) + 1}_")


async def snapshot(page: Page) -> list[Control]:
    """Visible, enabled form controls in page order (open shadow roots and iframes included).
    Tags them on the page and keeps ids stable across calls."""
    controls: list[Control] = []
    for frame in await frames_of(page):
        try:
            raw: list[dict[str, Any]] = await frame.evaluate(_SNAPSHOT, _prefix(frame))
        except Exception as e:  # a frame that navigates or detaches mid-read
            logger.debug("skipping frame {}: {}", frame.url, e)
            continue
        controls += [Control(**r) for r in raw]
    return controls


async def locate(page: Page, key: str) -> Locator:
    """The tagged element for a control id, in whichever frame holds it."""
    css = f'[data-lk-agent~="{key}"]'
    for frame in await frames_of(page):
        loc = frame.locator(css)
        if await loc.count():
            return loc.first
    return page.locator(css).first


async def page_text(page: Page, limit: int = 800) -> str:
    """Rendered text of the page and its frames (a form in an iframe has its words there)."""
    parts = []
    for frame in await frames_of(page):
        try:
            parts.append(await frame.evaluate(_BODY_TEXT))
        except Exception as e:  # a frame that navigates or detaches mid-read
            logger.debug("no text from frame {}: {}", frame.url, e)
    return " ".join(" ".join(parts).split())[:limit]


async def wait_for_confirmation(
    page: Page, pattern: re.Pattern[str], timeout_ms: int = 25000
) -> bool:
    """True once the text of the page or of any frame matches `pattern` (case-insensitive)."""
    rx = re.compile(pattern.pattern, re.I)
    end = time.monotonic() + timeout_ms / 1000
    while True:
        if rx.search(await page_text(page, 100_000)):
            return True
        if time.monotonic() >= end:
            return False
        await asyncio.sleep(0.5)


# --- the model's field map ---------------------------------------------------------------


class FieldSpec(BaseModel):
    id: str
    question: str
    kind: Kind
    required: bool = False


PageKind = Literal["form", "review", "confirmation", "login", "signup", "listing", "other"]


class FieldMap(BaseModel):
    page_kind: PageKind = "form"
    fields: list[FieldSpec] = []
    next_button: str | None = None
    submit_button: str | None = None
    apply_button: str | None = None  # listing only: the button or link that opens the application
    dismiss_button: str | None = None  # closes a sign-in or cookie popup covering the page


def clean_map(fmap: FieldMap, controls: list[Control]) -> FieldMap:
    """Trust nothing from the model: unknown ids and buttons-as-fields are dropped, Next and
    Submit must be buttons that exist, and one button is never both (it counts as Submit).
    Apply may be a button or an Apply link; Dismiss is a button that is none of the others."""
    by_id = {c.id: c for c in controls}
    fields, seen = [], set[str]()
    for f in fmap.fields:
        c = by_id.get(f.id)
        if c is not None and c.kind not in ("button", "link") and f.id not in seen:
            seen.add(f.id)
            fields.append(f)

    def button(i: str | None, kinds: tuple[str, ...] = ("button",)) -> str | None:
        return i if i is not None and i in by_id and by_id[i].kind in kinds else None

    nxt, sub = button(fmap.next_button), button(fmap.submit_button)
    if nxt == sub:
        nxt = None
    apply = button(fmap.apply_button, ("button", "link"))
    dismiss = button(fmap.dismiss_button)
    if dismiss in (nxt, sub, apply):
        dismiss = None
    return FieldMap(
        page_kind=fmap.page_kind,
        fields=fields,
        next_button=nxt,
        submit_button=sub,
        apply_button=apply,
        dismiss_button=dismiss,
    )


async def field_map(
    provider: LLMProvider, controls: list[Control], page_title: str, page_text: str = ""
) -> FieldMap:
    """Ask the model to map the page. The page's words are scrubbed of the user's sensitive
    answers first, then cut: callers pass a longer text so a secret is not cut in half."""
    shown = [
        replace(c, name=scrub(c.name, secrets_seen, 4)) for c in controls if c.kind != "password"
    ]  # password boxes are filled by our code, never mapped
    prompt = render(
        "form_map.j2",
        controls=shown,
        title=scrub(page_title, secrets_seen),
        page_text=scrub(page_text, secrets_seen)[:800],
    )
    return clean_map(await provider.complete(prompt, FieldMap), controls)


def to_questions(controls: list[Control], fmap: FieldMap) -> list[Question]:
    """Questions for the answer engine. The model's label is used, but the page's own text is
    kept as the description, so a renamed sensitive question is still caught by its rules.
    Controls the model left out are asked only when the page requires them."""
    specs = {f.id: f for f in fmap.fields}
    out = []
    for c in controls:
        if c.kind in ("button", "link", "password"):
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


_NOT_APPLICATION = re.compile(r"\b(search|newsletter|subscribe|coupon)\b", re.I)
_LABEL_MARKS = re.compile(r"\s*(?:[*✱]|\((?:required|optional)\))\s*", re.I)


def page_questions(controls: list[Control]) -> list[Question]:
    """Questions read straight from the page's own labels and field names, without the AI.
    Fields the form already holds a value for are left alone."""
    out = []
    for c in controls:
        label = _LABEL_MARKS.sub(" ", c.name or c.html_name).strip()
        if c.kind in get_args(Kind) and c.empty and label and not _NOT_APPLICATION.search(label):
            out.append(
                Question(
                    key=c.id,
                    label=label,
                    kind=cast(Kind, c.kind),
                    required=c.required,
                    options=c.options,
                    name=c.html_name,
                )
            )
    return out


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


# --- acting on the page ------------------------------------------------------------------


async def _frame_of(page: Page, key: str) -> Frame:
    """The frame holding control `key` (the main frame if it is not found)."""
    for frame in await frames_of(page):
        if await frame.locator(f'[data-lk-input="{key}"]').count():
            return frame
    return page.main_frame


async def _fill(frame: Frame, q: Question, value: Any) -> None:
    box = frame.locator(f'[data-lk-agent~="{q.key}"]').first
    await fill_in(frame, box, frame.locator(f'[data-lk-input="{q.key}"]'), q, value)


async def fill_page(
    page: Page, questions: list[Question], answers: dict[str, Any]
) -> dict[str, str]:
    """Fill every answered question through `form.fill_in`, inside its own frame.
    Returns {key: why} for failures."""
    failed = {}
    frames = {q.key: await _frame_of(page, q.key) for q in questions if q.key in answers}
    for q in questions:
        if q.key in answers:
            try:
                await _fill(frames[q.key], q, answers[q.key])
            except FillError as e:
                failed[q.key] = str(e)
    for frame in dict.fromkeys(frames.values()):
        mine = [q for q in questions if frames.get(q.key) is frame]
        for q in await lost_values(frame, mine, answers):  # React forms can reset fields
            try:
                await _fill(frame, q, answers[q.key])
                failed.pop(q.key, None)
            except FillError as e:
                failed[q.key] = str(e)
    return failed


_MAX_ERROR = 300  # longer is a wrapper around the form that happens to have an error class
_GOOD_NEWS = re.compile(r"\b(is attached|file selected|uploaded successfully)\b", re.I)


async def page_errors(page: Page) -> list[str]:
    """Visible validation messages of the page and its frames (same selector as the handlers)."""
    texts = []
    for frame in await frames_of(page):
        found = frame.locator(ERRORS).locator("visible=true")
        for i in range(min(await found.count(), 30)):
            with contextlib.suppress(Exception):  # e.g. an SVG error icon has no inner text
                texts.append(" ".join((await found.nth(i).inner_text(timeout=2000)).split()))
    return sorted({t for t in texts if t and len(t) <= _MAX_ERROR and not _GOOD_NEWS.search(t)})[
        :10
    ]


@dataclass
class StepResult:
    page_kind: str
    action: Literal["next", "submit", "open", "stop"]  # open: press Apply on a job ad
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
    code: str = ""  # stable id of why we stopped (no_form, no_apply_button, ...)
    dismiss: Control | None = None  # popup to close before pressing `button`

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


# The site's own words on a job ad that cannot be applied to: nothing for the user to finish.
_NOT_ELIGIBLE = re.compile(r"^not eligible$", re.I)
_GONE = re.compile(
    r"^404\b|\b(error 404|404 error|page not found)\b|\bno longer (available|accepting)\b"
    r"|\bthis (job|position|posting|vacancy) (has )?(expired|closed|been filled)\b",
    re.I,
)


def _apply_control(controls: list[Control]) -> Control | None:
    """The Apply button when the model named none; one that leads somewhere comes first."""
    found = [c for c in controls if c.apply]
    return (
        min(found, key=lambda c: not c.href.startswith("http") or "#" in c.href) if found else None
    )


async def _dead_end(page: Page, controls: list[Control]) -> StepResult | None:
    if any(c.kind == "button" and _NOT_ELIGIBLE.search(c.name) for c in controls):
        why = "the site says you are not eligible for this job"
        return StepResult("listing", "stop", reason=why, code="not_eligible")
    if _GONE.search(f"{await page.title()} {await page_text(page)}"):
        return StepResult("listing", "stop", reason="the posting is gone", code="posting_gone")
    return None


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
    password: str | None = None,
) -> StepResult:
    """One page: snapshot -> map -> answer -> fill -> re-check. Never clicks anything;
    `result.button` is what the caller may press (`press_next`, or `click_submit`).
    With `password` (a sign-up form of the account flow), password boxes are filled with it,
    straight from the vault: never shown to the model, never logged."""
    if await captcha_shown(page):
        return StepResult(
            "other", "stop", reason="a CAPTCHA is shown: only you can solve it", code="captcha"
        )
    controls = await snapshot(page)
    if not controls:
        return StepResult("other", "stop", reason="no form controls on the page", code="no_form")
    if password is None and any(c.kind == "password" for c in controls):
        return StepResult(
            "login", "stop", reason="sign-in or sign-up page: needs the account flow", code="login"
        )
    remember_secrets(ctx.answers)
    remember_bank_secrets(bank.db)
    fmap = await field_map(provider, controls, await page.title(), await page_text(page, 2000))
    by_id = {c.id: c for c in controls}
    if fmap.page_kind in ("listing", "other"):
        opener = by_id.get(fmap.apply_button or "") or _apply_control(controls)
        if opener is not None:
            return StepResult(
                "listing", "open", opener, dismiss=by_id.get(fmap.dismiss_button or "")
            )
        if (dead := await _dead_end(page, controls)) is not None:
            return dead
        if fmap.page_kind == "listing":
            return StepResult(
                "listing", "stop", reason="a job ad without an Apply button", code="no_apply_button"
            )
    accepted = ("form", "review", "signup", "login") if password else ("form", "review")
    if fmap.page_kind not in accepted:
        return StepResult(
            fmap.page_kind,
            "stop",
            reason=f"page looks like: {fmap.page_kind}",
            code=f"page_{fmap.page_kind}",
        )

    questions = to_questions(controls, fmap)
    r = await answer_questions(questions, ctx, bank, provider, cv, profile, job, out_dir)
    remember_secrets(ctx.answers, questions, r.answers)
    failed = await fill_page(page, questions, r.answers)
    for c in controls:
        if password and c.kind == "password":
            await (await locate(page, c.id)).fill(password)
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
            if k in required
            and c.empty
            and k not in parked
            and k not in failed
            and not (c.kind == "file" and k in r.answers)  # upload widgets empty their input
        ],
        await page_errors(page),
        dry_run,
        "" if button else "no_button",
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
    await (await locate(page, result.button.id)).click()


# --- the account flow on sites without a handler (CLAUDE.md §5.5) -----------------------------

_SIGNUP = re.compile(
    r"^(sign ?up|create (an |your |a free )?account|register|join( now| free| us)?|new (user|here)"
    r"|don.?t have an account)",
    re.I,
)
_LOGIN_BUTTON = re.compile(r"\b(sign ?in|log ?in|continue|next|submit|verify|confirm)\b", re.I)
_USER = re.compile(r"e-?mail|user|login", re.I)
_CODE = re.compile(r"code|otp|pin|verif", re.I)


async def login_form(page: Page) -> bool:
    """A sign-in form is shown: a password box, or an email box with a Sign in / Continue button
    and nothing else to answer (email-first logins)."""
    controls = await snapshot(page)
    if any(c.kind == "password" for c in controls):
        return True
    fields = [c for c in controls if c.kind not in ("button", "link")]
    return (
        len(fields) == 1
        and _user_box(fields) is not None
        and any(c.kind == "button" and _LOGIN_BUTTON.search(c.name) for c in controls)
    )


def _user_box(controls: list[Control]) -> Control | None:
    for c in controls:
        if c.kind == "email" or (c.kind == "text" and _USER.search(f"{c.name} {c.html_name}")):
            return c
    return None


def _button(controls: list[Control], rx: re.Pattern[str]) -> Control | None:
    named = [c for c in controls if c.kind == "button" and rx.search(c.name)]
    lone = [c for c in controls if c.submit_like]
    return named[0] if named else (lone[0] if len(lone) == 1 else None)


async def sign_in(page: Page, username: str, password: str) -> None:
    """Fill a sign-in form and press its button, over up to 3 screens (email first, then the
    password). The password is typed from the vault and never logged."""
    for _ in range(3):
        controls = await snapshot(page)
        user = _user_box(controls)
        pw = [c for c in controls if c.kind == "password"]
        if user is None and not pw:
            return
        if user is not None and user.empty:
            await (await locate(page, user.id)).fill(username)
        for c in pw:
            await (await locate(page, c.id)).fill(password)
        button = _button(controls, _LOGIN_BUTTON)
        if button is None:
            return
        await (await locate(page, button.id)).click()
        with contextlib.suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=10000)


async def open_signup(page: Page) -> bool:
    """On a sign-in form, follow its "Sign up" / "Create account" link. False = none found."""
    for c in await snapshot(page):
        if c.kind in ("button", "link") and _SIGNUP.search(c.name):
            if c.href.startswith(("http://", "https://")):
                await page.goto(c.href, wait_until="domcontentloaded", timeout=60000)
            else:
                try:
                    await (await locate(page, c.id)).click(timeout=5000)
                except PlaywrightTimeout:  # behind a popup: a newsletter "Sign up", not this form's
                    continue
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("networkidle", timeout=10000)
            return True
    return False


async def signup_link_needed(page: Page) -> bool:
    """Not on a sign-up form yet: a sign-in form, or a page with only Sign in / Sign up buttons."""
    if await login_form(page):
        return True
    fields = [c for c in await snapshot(page) if c.kind not in ("button", "link")]
    return _user_box(fields) is None


async def enter_code(page: Page, code: str) -> bool:
    """Type an emailed verification code into the box asking for it and confirm."""
    controls = await snapshot(page)
    boxes = [c for c in controls if c.kind in ("text", "number", "tel")]
    named = [c for c in boxes if _CODE.search(f"{c.name} {c.html_name}")]
    box = named[0] if named else (boxes[0] if len(boxes) == 1 else None)
    if box is None:
        return False
    await (await locate(page, box.id)).fill(code)
    if (button := _button(controls, _LOGIN_BUTTON)) is not None:
        await (await locate(page, button.id)).click()
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=10000)
    return True


async def press_apply(page: Page, result: StepResult) -> None:
    """On a job ad: close the popup covering it, then open the application in this tab. A link
    is followed by its address; a button that opens a new tab has that tab's address loaded
    here and the tab closed, so the job keeps one page."""
    if result.action != "open" or result.button is None:
        raise AgentError("only an Apply button may be pressed here")
    if result.dismiss is not None:
        with contextlib.suppress(Exception):  # popups often close themselves meanwhile
            await (await locate(page, result.dismiss.id)).click(timeout=3000)
    href = result.button.href
    here = page.url.split("#")[0]
    if href.startswith(("http://", "https://")) and href.split("#")[0] != here:
        await page.goto(href, wait_until="domcontentloaded", timeout=60000)
        return  # a "#" link is a script button: clicked below
    target = await locate(page, result.button.id)
    try:
        async with page.context.expect_page(timeout=8000) as new:
            await target.click()
    except PlaywrightTimeout:  # same-tab navigation or an in-page form
        return
    tab = await new.value
    with contextlib.suppress(Exception):
        await tab.wait_for_load_state("domcontentloaded", timeout=30000)
    url = tab.url
    await tab.close()
    if url.startswith(("http://", "https://")):
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)


async def captcha_shown(page: Page) -> bool:
    """A CAPTCHA challenge frame is visible, on the page or inside one of its frames."""
    for frame in await frames_of(page):
        found = frame.locator(CAPTCHA)
        if any([await found.nth(i).is_visible() for i in range(await found.count())]):
            return True
    return False
