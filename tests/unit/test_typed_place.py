"""A home place typed in one box: city, state and country, split on , / or -."""

from datetime import date
from typing import Any

import pytest

from linkit_all.apply.answers import ApplicationAnswers, Context, Question, standard_answer
from linkit_all.core import geo
from linkit_all.core.infer import CvFacts, infer
from linkit_all.core.profile import ProfileFields


def parts(text: str) -> tuple[str, str, str] | None:
    row = geo.typed_place(text)
    return (row["city"], row["state"], row["iso2"]) if row else None


@pytest.mark.parametrize(
    "text",
    [
        "Maadi, Cairo, Egypt",
        "Maadi / Cairo / Egypt",
        "Maadi - Cairo - Egypt",
        "Maadi-Cairo-Egypt",
        "Maadi،Cairo،Egypt",
        "Maadi — Cairo / Egypt",
        "Egypt - Cairo - Maadi",  # country first, as often written in Arabic
    ],
)
def test_every_separator_gives_the_same_place(text: str) -> None:
    assert parts(text) == ("Maadi", "Cairo", "EG")


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("Cairo, Egypt", ("Cairo", "", "EG")),
        ("Cairo-Egypt", ("Cairo", "", "EG")),
        ("القاهرة - مصر", ("Cairo", "", "EG")),  # stored in English
        ("مصر / القاهرة", ("Cairo", "", "EG")),
        ("Maadi, Cairo", ("Maadi", "Cairo", "EG")),  # the country comes from the governorate
        ("Street 9, Maadi, Cairo, Egypt", ("Maadi", "Cairo", "EG")),
        ("Cairo, Eg", ("Cairo", "", "EG")),  # still typing the country
        ("Zzqy, Xxqw", ("Zzqy", "Xxqw", "")),
    ],
)
def test_parts_are_read(text: str, want: tuple[str, str, str]) -> None:
    assert parts(text) == want


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("Denver, CO", ("Denver", "CO", "US")),  # Colorado, not Colombia
        ("Los Angeles, CA", ("Los Angeles", "CA", "US")),
        ("Bogota, CO", ("Bogotá", "", "CO")),
        ("Austin, TX, USA", ("Austin", "TX", "US")),
    ],
)
def test_two_letter_codes(text: str, want: tuple[str, str, str]) -> None:
    got = parts(text)
    assert got is not None and (geo._norm(got[0]), got[1], got[2]) == (
        geo._norm(want[0]),
        *want[1:],
    )


@pytest.mark.parametrize(
    "text", ["Winston-Salem", "Aix-en-Provence", "Al-Mansoura", "Cairo", "Cairo,", "Egypt/"]
)
def test_one_name_is_not_split(text: str) -> None:
    assert geo.typed_place(text) is None


def test_a_hyphenated_city_keeps_its_hyphen_among_parts() -> None:
    assert parts("Winston-Salem, NC, USA") == ("Winston-Salem", "NC", "US")
    assert parts("Winston-Salem-USA") == ("Winston-Salem", "", "US")


def test_search_returns_the_one_typed_place_with_both_labels() -> None:
    got = geo.search_places("Giza / Egypt")
    assert [r["kind"] for r in got] == ["typed"]
    assert got[0]["label"] == "Giza, Egypt"
    assert got[0]["label_ar"].endswith("مصر") and "،" in got[0]["label_ar"]
    assert geo.search_places("cairo")[0]["kind"] != "typed"


def test_location_includes_the_state() -> None:
    p = ProfileFields(home_city="Maadi", home_state=" Cairo ", home_country="EG")
    assert p.location == "Maadi, Cairo, Egypt"
    assert ProfileFields(home_city="Cairo", home_country="EG").location == "Cairo, Egypt"


def ctx(**kw: Any) -> Context:
    return Context(full_name="J D", email="j@x.co", phone="1", location="Egypt",
                   answers=ApplicationAnswers(), **kw)  # fmt: skip


@pytest.mark.parametrize(
    ("label", "name"),
    [
        ("State", ""),
        ("State/Province", ""),
        ("Governorate", ""),
        ("State / Region", ""),
        ("المحافظة", ""),
        ("Where do you live", "address_state"),
    ],
)
def test_state_questions_are_answered_from_the_profile(label: str, name: str) -> None:
    q = Question("a", label, "text", name=name)
    assert standard_answer(q, ctx(home_state="Cairo")) == "Cairo"


@pytest.mark.parametrize(
    "label", ["State why you want this job", "United States experience", "Statement of purpose"]
)
def test_other_uses_of_the_word_are_not_state_questions(label: str) -> None:
    assert standard_answer(Question("a", label, "text"), ctx(home_state="Cairo")) is None


def test_no_state_saved_leaves_the_question_open() -> None:
    assert standard_answer(Question("a", "State", "text"), ctx()) is None


def test_a_cv_location_in_three_parts_gives_the_state() -> None:
    day = date(2026, 11, 9)
    v = infer(CvFacts(location="Maadi, Cairo, Egypt"), day)
    assert (v["profile.home_city"].value, v["profile.home_state"].value) == ("Maadi", "Cairo")
    assert "profile.home_state" not in infer(CvFacts(location="Cairo, Egypt"), day)
