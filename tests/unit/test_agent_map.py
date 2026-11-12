"""Pure parts of the generic form agent: the model's field map is never trusted."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from linkit_all.apply.agent import (
    Control,
    FieldMap,
    FieldSpec,
    clean_map,
    pick_button,
    scrub,
    secrets_seen,
    to_questions,
)
from linkit_all.apply.answers import sensitive_category


def test_clean_map_drops_unknown_ids_and_never_both_buttons() -> None:
    controls = [
        Control("a0", "text", "Name"),
        Control("a1", "button", "Next", type="button"),
        Control("a2", "button", "Send", type="submit"),
    ]
    fmap = FieldMap(
        fields=[
            FieldSpec(id="a0", question="Name", kind="text"),
            FieldSpec(id="a0", question="Dup", kind="text"),
            FieldSpec(id="zz", question="Ghost", kind="text"),
            FieldSpec(id="a1", question="A button", kind="text"),
        ],
        next_button="a1",
        submit_button="a1",
    )
    out = clean_map(fmap, controls)
    assert [f.id for f in out.fields] == ["a0"]
    assert (out.next_button, out.submit_button) == (None, "a1")  # one button is never both
    assert (
        clean_map(FieldMap(next_button="nope", submit_button="a0"), controls).submit_button is None
    )


def test_to_questions_keeps_the_pages_own_text_for_sensitive_rules() -> None:
    controls = [
        Control(
            "a0", "radio", "Are you legally authorized to work in the US?", True, ["Yes", "No"]
        ),
        Control("a1", "text", "Nickname"),  # optional and not mapped: left alone
        Control("a2", "text", "Phone", True, html_name="phone"),
    ]
    fmap = FieldMap(
        fields=[
            FieldSpec(id="a0", question="Tell us more", kind="text"),
            FieldSpec(id="a2", question="Mobile", kind="tel"),
        ]
    )
    qs = to_questions(controls, fmap)
    assert [q.key for q in qs] == ["a0", "a2"]
    assert qs[0].kind == "radio"  # the page decides structure, not the model
    assert sensitive_category(qs[0]) == "work_authorization"
    assert (qs[1].kind, qs[1].name) == ("tel", "phone")


def test_pick_button_treats_a_submit_looking_next_as_submit() -> None:
    nxt = Control("a1", "button", "Continue", type="button")
    send = Control("a2", "button", "Submit application", type="submit")
    assert pick_button([nxt, send], FieldMap(next_button="a1")) == ("next", nxt)
    assert pick_button([nxt, send], FieldMap(next_button="a2")) == ("submit", send)
    assert pick_button([nxt, send], FieldMap()) == ("submit", send)  # lone submit-looking button
    assert pick_button([nxt], FieldMap()) == ("stop", None)
    saving = Control("a3", "button", "Save and continue", type="submit")
    assert not saving.submit_like and pick_button([saving], FieldMap(next_button="a3"))[0] == "next"


# --- sensitive answers never reach the AI (CLAUDE.md section 2) ---------------------------------


def test_scrub_whole_words_case_longest_first() -> None:
    from linkit_all.apply.agent import scrub

    assert scrub("Notice period: No. no!", ["No"]) == "Notice period: [hidden]. [hidden]!"
    assert scrub("Yes, yesterday", ["yes"]) == "[hidden], yesterday"
    assert (
        scrub("I am not a protected veteran", ["I am not a protected veteran", "not"]) == "[hidden]"
    )
    assert scrub("abc", ["", "  "]) == "abc"
    assert scrub("salary 30000 USD", ["30000"]) == "salary [hidden] USD"


def test_field_map_scrubs_filled_sensitive_answers_from_the_prompt() -> None:
    import asyncio

    from linkit_all.apply import agent
    from linkit_all.apply.answers import ApplicationAnswers, Question

    class Spy:
        prompt = ""

        async def complete(self, prompt: str, schema: type) -> FieldMap:
            self.prompt = prompt
            return FieldMap(page_kind="review")

    q = Question(key="a1", label="Are you a protected veteran?", kind="text")
    agent.remember_secrets(
        ApplicationAnswers(nationality="Zorbian"), [q], {"a1": "Not a veteran-xyz"}
    )
    spy = Spy()
    asyncio.run(
        agent.field_map(
            spy,  # type: ignore[arg-type]
            [],
            "Review",
            "Summary: Veteran status: not a veteran-xyz. Nationality ZORBIAN. Name Ann",
        )
    )
    assert "veteran-xyz" not in spy.prompt and "zorbian" not in spy.prompt.lower()
    assert "Name Ann" in spy.prompt


@pytest.fixture(autouse=True)
def _no_secrets() -> Iterator[None]:
    secrets_seen.clear()
    yield
    secrets_seen.clear()


def test_scrub_multiline_separators_and_glued_symbols() -> None:
    assert scrub("pay: I want\n  to  leave", ["I want to\nleave"]) == "pay: [hidden]"
    assert scrub("asked 5,000 or 5.000 or 5 000 or 5000", ["5000"]) == (
        "asked [hidden] or [hidden] or [hidden] or [hidden]"
    )
    assert scrub("got 15000 and 15,000", ["5000"]) == "got 15000 and 15,000"
    assert scrub("USD$5,000 and +20 100 5", ["$5,000", "+20 100"]) == "USD[hidden] and [hidden] 5"
    assert scrub("الجنسية: مصري.", ["مصري"]) == "الجنسية: [hidden]."
    assert scrub("M or MM", ["M"]) == "[hidden] or MM"


def test_field_map_hides_secrets_in_names_title_and_at_the_cut() -> None:
    from linkit_all.apply import agent

    class Spy:
        prompt = ""

        async def complete(self, prompt: str, schema: type) -> FieldMap:
            self.prompt = prompt
            return FieldMap()

    secrets_seen.update(["Zorbianland", "90000"])
    spy = Spy()
    text = "a " * 397 + "Zorbianland and more"  # the secret starts at character 794
    asyncio.run(
        agent.field_map(
            spy,  # type: ignore[arg-type]
            [Control("a0", "text", "Salary 90000 please")],
            "Review 90000",
            text,
        )
    )
    assert "90000" not in spy.prompt and "Zorbia" not in spy.prompt
    assert spy.prompt.count("[hidde") >= 3


class _Spy:
    """A provider that records every prompt and answers every question with a text."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, prompt: str, schema: type) -> Any:
        import re

        from linkit_all.apply.assist import Draft, Drafts

        self.prompts.append(prompt)
        if schema is Drafts:
            keys = re.findall(r"- key: (\w+)", prompt)
            return Drafts(answers=[Draft(key=k, known=True, answer="Fine") for k in keys])
        return FieldMap()


def _answer(tmp_path: Path, qs: list[Any], spy: _Spy) -> Any:
    from test_answers import ctx
    from test_matching import fake_embed

    from linkit_all.apply.assist import AnswerBank, answer_questions
    from linkit_all.core.db import init_db

    db = init_db(tmp_path / "t.db")
    r = asyncio.run(
        answer_questions(qs, ctx(), AnswerBank(db, fake_embed), spy, "cv", "profile",  # type: ignore[arg-type]
                         {"title": "Dev", "company": "A"}, tmp_path)
    )  # fmt: skip
    with db() as s:
        from sqlalchemy import select

        from linkit_all.core.models import AnswerEntry

        saved = list(s.scalars(select(AnswerEntry.question)))
    return r, saved


def test_a_secret_in_a_sensitive_question_does_not_hide_it_from_the_rules(tmp_path: Path) -> None:
    secrets_seen.add("U.S. citizen")
    c = Control("a0", "text", "Are you a U.S. citizen?", required=True)
    (q,) = to_questions([c], FieldMap())
    assert q.label == "Are you a U.S. citizen?"  # the rules see the page's own words
    assert sensitive_category(q) is not None
    spy = _Spy()
    r, _ = _answer(tmp_path, [q], spy)
    assert not any("citizen" in p.lower() for p in spy.prompts)  # never sent
    assert "a0" not in r.answers


def test_answer_prompt_hides_a_secret_in_labels_not_in_options(tmp_path: Path) -> None:
    from linkit_all.apply.answers import Question

    secrets_seen.add("Zorbianland")
    text = Question("a0", "Why Zorbianland?", "text", True, description="Zorbianland office")
    pick = Question("a1", "Which site?", "select", True, options=["Zorbianland", "Elsewhere"])
    spy = _Spy()
    r, saved = _answer(tmp_path, [text, pick], spy)
    (prompt,) = spy.prompts
    assert "Why [hidden]?" in prompt and "([hidden] office)" in prompt
    assert "Why Zorbianland" not in prompt
    assert "options: Zorbianland || Elsewhere" in prompt  # copied exactly
    assert r.answers["a0"] == "Fine"  # under the original key
    assert "Why Zorbianland?" in saved  # and the bank keeps the original label


def test_short_secrets_are_kept_in_page_text_only(tmp_path: Path) -> None:
    from linkit_all.apply import agent
    from linkit_all.apply.answers import Question

    secrets_seen.add("No")
    spy = _Spy()
    asyncio.run(
        agent.field_map(
            spy,  # type: ignore[arg-type]
            [Control("a0", "radio", "No, thanks")],
            "Title",
            "Answer: No",
        )
    )
    (p,) = spy.prompts
    assert "No, thanks" in p and "Answer: [hidden]" in p
    q = Question("a1", "No fixed address?", "text", True)
    spy2 = _Spy()
    _answer(tmp_path, [q], spy2)
    assert "No fixed address?" in spy2.prompts[0]


def test_step_seeds_the_secrets_from_the_profile_and_the_answer_bank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linkit_all.apply import agent
    from linkit_all.apply.answers import ApplicationAnswers, Context
    from linkit_all.apply.assist import AnswerBank
    from linkit_all.core.db import init_db
    from linkit_all.core.models import AnswerEntry

    db = init_db(tmp_path / "db.sqlite")
    with db.begin() as s:
        s.add(AnswerEntry(question="Expected pay?", answer="777000", source="user", sensitive=True))
        s.add(AnswerEntry(question="Why us?", answer="fun", source="user", sensitive=False))
    seen: list[set[str]] = []

    async def fake_map(*a: Any) -> FieldMap:
        seen.append(set(secrets_seen))
        return FieldMap(page_kind="other")

    class Page:
        async def title(self) -> str:
            return "t"

    async def no(*a: Any) -> bool:
        return False

    async def snap(*a: Any) -> list[Control]:
        return [Control("a0", "text", "Name")]

    async def text(*a: Any) -> str:
        return ""

    monkeypatch.setattr(agent, "captcha_shown", no)
    monkeypatch.setattr(agent, "snapshot", snap)
    monkeypatch.setattr(agent, "page_text", text)
    monkeypatch.setattr(agent, "field_map", fake_map)
    ctx = Context("A B", "a@b.c", "1", "Cairo", ApplicationAnswers(nationality="Zorbian"))
    asyncio.run(
        agent.step(
            Page(),  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            ctx, AnswerBank(db), "", "", {}, tmp_path,
        )
    )  # fmt: skip
    assert seen == [{"Zorbian", "777000"}]
