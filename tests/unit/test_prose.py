"""apply/prose.py: stock phrases and clause dashes never reach a recruiter (rules only)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from linkit_all.apply.answers import Question
from linkit_all.apply.assist import ai_drafts, write_cover_letter
from linkit_all.apply.email_apply import compose
from linkit_all.apply.prose import clean, retry_note, tells
from linkit_all.providers.base import LLMProvider

STOCK = (
    "I hope this email finds you well. I am writing to express my strong interest in the role. "
    "I'm thrilled to bring Python — and Django — to your dynamic team."
)


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        (
            STOCK,
            "I am applying for the role. I would like to bring Python, and Django, to your team.",
        ),
        ("Leveraging AWS, I cut costs.", "Using AWS, I cut costs."),
        ("She leverages and utilizes tools.", "She uses and uses tools."),
        ("I am passionate about APIs.", "I am keen on APIs."),
        ("Done.\n\nMoreover, it shipped.", "Done.\n\nAlso, it shipped."),
        ("Done. Furthermore, it shipped.", "Done. Also, it shipped."),
        ("In today's fast-paced world, speed wins. I ship.", "I ship."),
        ("My unwavering focus is a testament to care.", "My focus shows care."),
        # left alone: ranges, hyphenated words, bullets, plain prose
        ("From 2019–2021 I built well-known tools.", "From 2019–2021 I built well-known tools."),  # noqa: RUF001
        ("Skills:\n- Python\n- SQL", "Skills:\n- Python\n- SQL"),
        ("I build APIs in Python.", "I build APIs in Python."),
    ],
)
def test_clean(raw: str, want: str) -> None:
    assert clean(raw) == want
    assert tells(clean(raw)) == []


def test_tells_and_retry_note() -> None:
    assert tells("I build APIs.") == [] and retry_note("I build APIs.") == ""
    note = retry_note(STOCK)
    assert "I'm thrilled to" in note and "dashes" in note


class Fake(LLMProvider):
    """Answers from `replies` in order (the last one repeats); keeps every prompt."""

    name = "fake"

    def __init__(self, *replies: dict[str, Any]) -> None:
        super().__init__("fake")
        self.replies = list(replies)
        self.prompts: list[str] = []

    async def _call(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.replies[min(len(self.prompts), len(self.replies)) - 1])


JOB = {"title": "Dev", "company": "Acme", "description": "Python"}


@pytest.mark.parametrize("second", ["Dear Hiring Team, I build APIs.", STOCK])
def test_cover_letter_retried_once_then_cleaned(tmp_path: Path, second: str) -> None:
    ai = Fake({"text": STOCK}, {"text": second})
    text, _ = asyncio.run(write_cover_letter(ai, "cv", "profile", JOB, tmp_path))
    assert len(ai.prompts) == 2 and "stock phrases" in ai.prompts[1]
    assert tells(text) == []  # a second bad draft is cleaned, not sent as is


def test_plain_cover_letter_is_not_retried(tmp_path: Path) -> None:
    ai = Fake({"text": "Dear Hiring Team, I build APIs."})
    asyncio.run(write_cover_letter(ai, "cv", "profile", JOB, tmp_path))
    assert len(ai.prompts) == 1


def test_application_email_retried_once_then_cleaned() -> None:
    ai = Fake({"subject_suffix": None, "body": STOCK})
    draft = asyncio.run(compose(ai, to="hr@acme.com", job=JOB, cv="cv", profile_facts="p",
                                full_name="Jane Doe", phone="", linkedin="", author=None))  # fmt: skip
    assert len(ai.prompts) == 2 and "stock phrases" in ai.prompts[1]
    assert tells(draft.body) == [] and draft.problem is None


def test_free_text_answers_cleaned_option_answers_kept() -> None:
    ai = Fake({"answers": [
        {"key": "why", "known": True, "answer": "I'm excited to leverage Python — daily."},
        {"key": "pick", "known": True, "answer": "Leverage — the brand"},
    ]})  # fmt: skip
    qs = [Question("why", "Why us?", "textarea", True),
          Question("pick", "Favourite tool", "select", True, options=["Leverage — the brand", "Other"])]  # fmt: skip
    got = asyncio.run(ai_drafts(ai, qs, "cv", "profile", JOB))
    assert got == {"why": "I would like to use Python, daily.", "pick": "Leverage — the brand"}
