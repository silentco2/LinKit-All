"""Knock-out pre-scan (apply/knockout.py): rules only, fires only on a stated requirement."""

from typing import Any

import pytest

from linkit_all.apply import knockout
from linkit_all.apply.answers import ApplicationAnswers, Context, Question

YN = ["Yes", "No"]


def ctx(**answers: Any) -> Context:
    return Context(full_name="Jane Q Doe", email="j@x.io", phone="+20 100", location="Cairo",
                   answers=ApplicationAnswers(**answers), job_location="Berlin, Germany")  # fmt: skip


def q(label: str, kind: Any = "yesno", options: list[str] | None = None) -> Question:
    return Question("q", label, kind, True, YN if options is None else options)


@pytest.mark.parametrize(
    ("label", "years", "hit"),
    [
        ("Do you have at least 8 years of professional experience?", 5, True),
        ("Do you have at least 8 years of professional experience?", 8, False),
        ("Do you have more than 5 years of experience with Python?", 5, True),
        ("Do you have 3+ years of experience in sales?", 2, True),
        ("هل لديك خبرة 5 سنوات على الأقل؟", 3, True),
        ("Do you have at least 8 years of professional experience?", None, False),  # unknown
        ("Are you available to start within 2 years?", 1, False),  # not about experience
    ],
)
def test_years(label: str, years: int | None, hit: bool) -> None:
    found = knockout.find([q(label)], ctx(years_experience=years))
    assert [k.kind for k in found] == (["years"] if hit else [])


def test_years_ranges_are_not_a_knockout() -> None:
    ranges = Question("q", "Years of experience", "radio", True, ["7+", "5-7", "2-4", "0-1"])
    assert knockout.find([ranges], ctx(years_experience=1)) == []


@pytest.mark.parametrize(
    ("label", "cv", "hit"),
    [
        (
            "Do you have a Master's degree in Computer Science?",
            "B.Sc. Computer Science, Cairo",
            True,
        ),
        ("Do you have a Bachelor's degree?", "B.Sc. Computer Science, Cairo", False),
        ("Do you hold a PhD?", "MSc in Physics", True),
        ("Do you have a Bachelor's degree?", "Ten years of sales work", False),  # CV names none
        ("Do you have a Master's degree or equivalent experience?", "BSc Maths", False),
        ("هل لديك ماجستير؟", "بكالوريوس هندسة", True),
    ],
)
def test_degree(label: str, cv: str, hit: bool) -> None:
    found = knockout.find([q(label)], ctx(), cv)
    assert [k.kind for k in found] == (["degree"] if hit else [])


SPONSOR = "Will you now or in the future require sponsorship for employment visa status?"
AUTH = "Are you legally authorized to work in Germany?"


def test_needing_sponsorship_alone_is_not_a_knockout() -> None:
    assert knockout.find([q(SPONSOR)], ctx(visa_countries=["DE"])) == []


def test_sponsorship_when_the_posting_offers_none() -> None:
    jd = "Please note we are unable to sponsor visas for this role."
    found = knockout.find([q(SPONSOR), q(AUTH)], ctx(visa_countries=["DE"]), "", jd)
    assert [k.kind for k in found] == ["sponsorship", "work_authorization"]
    assert knockout.find([q(SPONSOR)], ctx(authorized_countries=["DE"]), "", jd) == []
    assert knockout.find([q(SPONSOR)], ctx(), "", jd) == []  # not in the profile: the usual flow


@pytest.mark.parametrize(
    ("label", "want", "currency", "hit"),
    [
        ("The salary for this role is $90,000. Is this acceptable?", "120000", "USD", True),
        ("The salary for this role is $90,000. Is this acceptable?", "85000", "USD", False),
        ("The range is 60k-80k EUR. Does this meet your expectations?", "95000", "EUR", True),
        ("The range is 60k-80k EUR. Does this meet your expectations?", "95000", "USD", False),
        (
            "The salary is 5,000 per month. Is this acceptable?",
            "70000",
            "",
            False,
        ),  # periods differ
        ("What are your salary expectations?", "120000", "USD", False),
    ],
)
def test_salary(label: str, want: str, currency: str, hit: bool) -> None:
    found = knockout.find([q(label)], ctx(salary_expectation=want, salary_currency=currency))
    assert [k.kind for k in found] == (["salary"] if hit else [])


def test_reason_quotes_the_question() -> None:
    (hit,) = knockout.find(
        [q("Do you have at least 8 years of experience?")], ctx(years_experience=2)
    )
    assert hit.reason == (
        'This form would reject you: it asks "Do you have at least 8 years of experience?" '
        "(your profile says 2 years)"
    )
