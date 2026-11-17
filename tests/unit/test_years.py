"""B1 years of experience from the description, and B2 dealbreakers (matching/years.py, rules.py)."""

from typing import Any

import pytest

from linkit_all.core.models import Job, JobState, utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.matching.reasons import job_reason
from linkit_all.matching.rules import dealbreaker, rule_violation
from linkit_all.matching.years import sentences, years_required


@pytest.mark.parametrize(
    ("text", "floor", "label"),
    [
        ("5+ years of experience in backend development.", 5, "5+"),
        ("3-5 years of professional experience.", 3, "3-5"),
        ("Between 3 and 5 years of experience required.", 3, "3-5"),
        ("At least five (5) years of experience in software engineering.", 5, "5+"),
        ("Minimum 7 yrs experience.", 7, "7+"),
        ("Experience: 4+ years.", 4, "4+"),
        ("7 years of experience with a Bachelor's, or 5 with a Master's degree.", 7, "7+"),
        ("خبرة 5 سنوات في مجال المبيعات", 5, "5+"),
        ("خبرة لا تقل عن ٣ سنوات", 3, "3+"),
        ("خبرة من 3-5 سنوات", 3, "3-5"),
        ("خبرة سنتين في خدمة العملاء", 2, "2+"),
        ("No prior experience required. Training is provided.", 0, "0+"),
    ],
)
def test_required_overall_figure(text: str, floor: float, label: str) -> None:
    got = years_required(text)
    assert (got.floor, got.label, got.kind, got.confident) == (floor, label, "required", True)


@pytest.mark.parametrize(
    ("text", "kind", "label"),
    [
        ("10 years of Java preferred.", "preferred", "10+"),
        ("Ideally 8+ years of experience in fintech.", "preferred", "8+"),
        ("Nice to have:\n- 6+ years of experience in leadership", "preferred", "6+"),
        ("3+ years of experience with SQL.", "skill", "3+"),
        ("يفضل خبرة 5 سنوات", "preferred", "5+"),
    ],
)
def test_preferred_and_skill_figures_never_gate(text: str, kind: str, label: str) -> None:
    got = years_required(text)
    assert (got.floor, got.confident, got.kind, got.label) == (None, False, kind, label)


@pytest.mark.parametrize(
    "text",
    [
        "We are a great team.",
        "Our company was founded 15 years ago.",
        "We have 20 years of experience building payment systems.",
        "A 4-year degree in computer science.",
        "You must be at least 18 years of age.",
        "Up to 10 years of experience.",
        "You will work with engineers with 10+ years of experience.",
        "A 2 year contract term with renewal.",
        "Grow revenue within the first 2 years.",
    ],
)
def test_figures_that_are_not_a_requirement(text: str) -> None:
    assert years_required(text) == years_required("")


def test_lowest_required_bar_gates_and_soft_bars_are_not_confident() -> None:
    both = years_required("5+ years of experience in software.\n2+ years of experience leading.")
    assert (both.floor, both.confident) == (2, True)
    alt = years_required(
        "8+ years of experience in finance, or an equivalent combination of education "
        "and experience."
    )
    assert (alt.floor, alt.confident) == (8, False)
    unknown = years_required("About the role:\nThe team ships with 6+ years of experience.")
    assert (unknown.floor, unknown.confident) == (6, False)
    sub = years_required("Requires 7+ years of experience, including 2 years of managing people.")
    assert sub.floor == 7
    degree = years_required("A Bachelor's degree or 4 years of relevant experience.")
    assert degree.floor is None


def test_sentences_keep_abbreviations_whole() -> None:
    assert sentences("B.S. in CS required. Must travel.\n- Night shifts; weekends") == [
        "B.S. in CS required.",
        "Must travel.",
        "Night shifts",
        "weekends",
    ]


# --- the hard rule ---------------------------------------------------------------------


def job(description: str) -> Job:
    return Job(source="x", title="Backend Developer", company="Acme", location="Cairo",
               dedupe_hash="h", description=description, data={})  # fmt: skip


def cfg(**filters: Any) -> SearchConfig:
    return SearchConfig.model_validate({"filters": filters})


def test_years_filter_is_off_by_default() -> None:
    row = job("10+ years of experience required.")
    assert rule_violation(row, cfg(), utcnow()) is None
    assert "years_required" not in row.data


def test_years_label_marks_but_keeps_the_job() -> None:
    row = job("10+ years of experience required.")
    assert rule_violation(row, cfg(max_years_required=4), utcnow()) is None
    assert row.data["years_required"] == {"label": "10+", "kind": "required", "above": True}
    within = job("3-5 years of experience required.")
    assert rule_violation(within, cfg(max_years_required=4, years_action="drop"), utcnow()) is None
    assert within.data["years_required"] == {"label": "3-5", "kind": "required", "above": False}


def test_years_drop_needs_a_clear_overall_requirement() -> None:
    drop = cfg(max_years_required=4, years_action="drop")
    row = job("10+ years of experience required.")
    reason = rule_violation(row, drop, utcnow())
    assert reason == "asks for 10+ years of experience, above your 4"
    row.state = JobState.filtered_out
    assert job_reason(row, (reason, None, {})) == (
        "Asks for 10+ years of experience, above your 4",
        "years",
        {"years": "10+", "limit": "4"},
    )
    for soft in (
        "10 years of Java preferred.",
        "10+ years of experience with SQL.",
        "10+ years of experience, or an equivalent combination of education and experience.",
        "A friendly team.",
    ):
        assert rule_violation(job(soft), drop, utcnow()) is None


def test_dealbreaker_filters_with_the_sentence_that_says_it() -> None:
    text = "Great team. This role requires Night Shifts every week. Free lunch."
    row = job(text)
    assert dealbreaker(text, ["night  shifts"]) == (
        "night  shifts",
        "This role requires Night Shifts every week.",
    )
    reason = rule_violation(row, cfg(dealbreakers=["commission only", "night shifts"]), utcnow())
    assert reason == "dealbreaker 'night shifts': \"This role requires Night Shifts every week.\""
    row.state = JobState.filtered_out
    assert job_reason(row, (reason, None, {})) == (
        'Says "night shifts": This role requires Night Shifts every week.',
        "dealbreaker",
        {"phrase": "night shifts", "sentence": "This role requires Night Shifts every week."},
    )


def test_dealbreaker_absent_passes() -> None:
    row = job("Great team. Day shifts only.")
    assert rule_violation(row, cfg(dealbreakers=["night shifts", " "]), utcnow()) is None
    assert dealbreaker("anything", []) is None
