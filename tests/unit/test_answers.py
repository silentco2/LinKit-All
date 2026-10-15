"""Answer engine, using the real question wording seen on Airbnb (Greenhouse), Palantir
(Lever) and OpenAI (Ashby) application forms."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from test_matching import fake_embed

from linkit_all.apply.answers import (
    ApplicationAnswers,
    Context,
    Question,
    country_of,
    resolve_static,
    sensitive_category,
)  # fmt: skip
from linkit_all.apply.assist import AnswerBank, answer_questions
from linkit_all.core.db import init_db
from linkit_all.providers.base import LLMProvider

AUTH = Question(
    "q1",
    "Are you legally authorized to work in the country where the job is located?",
    "combobox",
    True,
    [
        "Yes, I am currently legally authorized to work in the country where the job is located.",
        "No, I am not currently legally authorized to work in the country where the job is located.",
    ],
)
SPONSOR = Question(
    "q2",
    "Will you now or in the future require company sponsorship to retain or obtain authorization to work in the country where the job is located?",
    "combobox",
    True,
    [
        "Yes, I will require immigration sponsorship now to legally work in the country where the job is located.",
        "Yes, I will require immigration sponsorship in the future to legally work in the country where the job is located.",
        "No, I do not and will not require immigration sponsorship to legally work in the country where the job is located.",
    ],
)
GENDER = Question(
    "q3", "Gender", "combobox", True, ["Male", "Female", "Other", "Decline to Self Identify"]
)
VETERAN = Question(
    "q4",
    "Veteran Status",
    "radio",
    False,
    [
        "I identify as one or more of the classifications of protected veteran",
        "I am not a protected veteran",
        "I decline to self-identify for protected veteran status",
    ],
)
PRIVACY = Question(
    "q5",
    "Before submitting your application please review the points below:",
    "multi",
    True,
    ["I acknowledge receipt of the Airbnb Candidate Data Privacy Notice"],
)
HEARD = Question(
    "q6", "How did you hear about this job?", "multi", False, ["Twitter", "LinkedIn", "Glassdoor"]
)
YEARS = Question("q7", "Years of experience", "radio", True, ["7+", "5-7", "2-4", "0-1"])
FIRST = Question("first_name", "First Name", "text", True, name="first_name")
LAST = Question("last_name", "Last Name", "text", True, name="last_name")
RESUME = Question("resume", "Resume/CV", "file", True, name="resume")
CRIMINAL = Question("q8", "Have you ever been convicted of a felony?", "yesno", True, ["Yes", "No"])
WHY = Question("q9", "Why do you want to work at Acme?", "textarea", True)
CLEARANCE = Question(
    "q10", "Do you hold an active security clearance?", "yesno", True, ["Yes", "No"]
)
LETTER = Question("q11", "Cover Letter", "textarea", False, name="cover_letter_text")  # fmt: skip


def ctx(**answers: Any) -> Context:
    return Context(full_name="Jane Q Doe", email="j@x.io", phone="+20 100", location="Cairo",
                   answers=ApplicationAnswers(**answers), job_location="Cairo, Egypt",
                   job_source="linkedin", resume_path="cv.pdf")  # fmt: skip


@pytest.mark.parametrize(
    ("q", "category"),
    [(AUTH, "work_authorization"), (SPONSOR, "sponsorship"), (GENDER, "eeo_gender"), (VETERAN, "eeo_veteran"),
     (PRIVACY, "acknowledge_privacy"), (CRIMINAL, "criminal"), (HEARD, None), (WHY, None)],
)  # fmt: skip
def test_sensitive_category(q: Question, category: str | None) -> None:
    assert sensitive_category(q) == category


def test_privacy_acknowledgement_by_option_text() -> None:
    q = Question(
        "x", "I acknowledge receipt of the Candidate Data Privacy Notice", "checkbox", True
    )
    assert sensitive_category(q) == "acknowledge_privacy"


@pytest.mark.parametrize(
    ("text", "country"),
    [("Cairo, Egypt", "egypt"), ("Please contact us", None), ("authorized to work in the US?", "united states"),
     ("Dubai", "united arab emirates"), ("Giza, EG", "egypt"), ("Remote", None)],
)  # fmt: skip
def test_country_of(text: str, country: str | None) -> None:
    assert country_of(text) == country


def test_authorized_locally_means_no_sponsorship() -> None:
    r = resolve_static([AUTH, SPONSOR], ctx(authorized_countries=["Egypt"]))
    assert r.answers["q1"].startswith("Yes, I am currently")
    assert r.answers["q2"].startswith("No, I do not")


def test_abroad_uses_saved_sponsorship_need() -> None:
    c = ctx(authorized_countries=["Egypt"], needs_sponsorship=True)
    c.job_location = "Dublin"
    r = resolve_static([AUTH, SPONSOR], c)
    assert r.answers["q1"].startswith("No, I am not")
    assert r.answers["q2"].startswith("Yes, I will require immigration sponsorship now")


def test_sensitive_without_profile_data_goes_to_user() -> None:
    r = resolve_static([AUTH, SPONSOR, GENDER, PRIVACY, CRIMINAL], ctx())
    assert {m.question.key for m in r.missing} == {"q1", "q2", "q3", "q5", "q8"}
    assert all(m.sensitive for m in r.missing) and not r.pending  # none of them reach the AI


def test_saved_demographics_and_acknowledgements() -> None:
    r = resolve_static([GENDER, VETERAN, PRIVACY],
                       ctx(eeo_gender="decline", eeo_veteran="not_veteran", acknowledge_privacy=True))  # fmt: skip
    assert r.answers == {"q3": "Decline to Self Identify", "q4": "I am not a protected veteran",
                         "q5": ["I acknowledge receipt of the Airbnb Candidate Data Privacy Notice"]}  # fmt: skip


def test_standard_fields_files_and_defaults() -> None:
    r = resolve_static([FIRST, LAST, RESUME, HEARD, YEARS], ctx(years_experience=6))
    assert r.answers == {"first_name": "Jane", "last_name": "Q Doe", "resume": "cv.pdf",
                         "q6": ["LinkedIn"], "q7": "5-7"}  # fmt: skip


class FakeAI(LLMProvider):
    name = "fake"

    def __init__(self) -> None:
        super().__init__("fake")
        self.calls: list[str] = []

    async def _call(self, prompt: str) -> str:
        self.calls.append(prompt)
        if "cover letter" in prompt.lower() and "Write a short" in prompt:
            return json.dumps({"text": "Dear Hiring Team,\nI build Python services.\nJane"})
        keys = re.findall(r"- key: (\w+)", prompt)
        answers = [{"key": k, "known": k == "q9", "answer": "Your APIs match my Python work." if k == "q9" else None}
                   for k in keys]  # fmt: skip
        return json.dumps({"answers": answers})


def test_answer_questions_bank_then_ai(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    bank = AnswerBank(db, fake_embed)
    bank.save(CRIMINAL.label, "No", "user", sensitive=True)  # answered once in the Action Center
    ai = FakeAI()
    run = lambda: asyncio.run(answer_questions(  # noqa: E731
        [FIRST, CRIMINAL, WHY, CLEARANCE, LETTER], ctx(), bank, ai, "CV text", "profile", {"title": "Dev", "company": "Acme"}, tmp_path))  # fmt: skip

    r = run()
    assert r.answers["q8"] == "No" and r.sources["q8"] == "bank"  # user's own sensitive answer
    assert r.answers["q9"] == "Your APIs match my Python work." and r.sources["q9"] == "ai"
    assert r.answers["q11"].startswith("Dear Hiring Team")
    assert [m.question.key for m in r.missing] == ["q10"]  # the AI said it doesn't know
    assert all("convicted" not in p for p in ai.calls)  # sensitive text never sent to the AI

    ai.calls.clear()
    r = run()
    assert r.sources["q9"] == "bank"  # the AI draft was saved and reused
    assert not any("- key: q9" in p for p in ai.calls)
