"""Names: split on spaces, and written in the other script without any AI."""

import pytest

from linkit_all.apply.answers import ApplicationAnswers, Context, Question, standard_answer
from linkit_all.core.names import name_in, name_part, script_of, translate


@pytest.mark.parametrize(
    ("full", "first", "middle", "all_middle", "third", "last"),
    [
        ("", "", "", "", "", ""),
        ("Madonna", "Madonna", "", "", "", ""),
        ("Sara Ahmed", "Sara", "", "", "", "Ahmed"),
        ("Sara Mona Ahmed", "Sara", "Mona", "Mona", "Ahmed", "Ahmed"),
        ("Omar  Ali Hassan Fahmy", "Omar", "Ali", "Ali Hassan", "Hassan", "Fahmy"),
        ("Abdel Rahman Ali", "Abdel", "Rahman", "Rahman", "Ali", "Ali"),
    ],
)
def test_the_name_splits_on_spaces(
    full: str, first: str, middle: str, all_middle: str, third: str, last: str
) -> None:
    assert name_part(full, "first_name") == first
    assert name_part(full, "middle_name") == middle
    assert name_part(full, "middle_names") == all_middle
    assert name_part(full, "third_name") == third
    assert name_part(full, "last_name") == last


def _answer(label: str, full: str, name: str = "", other: str = "") -> object:
    ctx = Context(
        full_name=full,
        email="",
        phone="",
        location="",
        answers=ApplicationAnswers(name_other=other),
    )
    return standard_answer(Question(key="q", label=label, kind="text", name=name), ctx)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("First name", "Omar"),
        ("Middle name", "Ali"),
        ("Middle names", "Ali Hassan"),
        ("Third name", "Hassan"),
        ("Father's name", "Ali"),
        ("Grandfather name", "Hassan"),
        ("Last name", "Fahmy"),
        ("Full name", "Omar Ali Hassan Fahmy"),
    ],
)
def test_each_name_box_gets_its_part(label: str, expected: str) -> None:
    assert _answer(label, "Omar Ali Hassan Fahmy") == expected


def test_a_form_asking_for_both_languages_gets_each_one() -> None:
    assert _answer("Name in English", "Omar Ali", other="عمر علي") == "Omar Ali"
    assert _answer("Name in Arabic", "Omar Ali", other="عمر على") == "عمر على"
    assert _answer("الاسم بالعربية", "Omar Ali", other="عمر علي") == "عمر علي"
    assert _answer("First Name (Arabic)", "Omar Ali", other="عمر علي") == "عمر"
    assert _answer("x", "Omar Ali", name="last_name_ar", other="عمر علي") == "علي"
    assert _answer("Full name in English", "عمر علي", other="Omer Aly") == "Omer Aly"


def test_with_nothing_written_the_name_list_supplies_the_other_script() -> None:
    assert _answer("Arabic Name", "Mohamed Hassan") == "محمد حسن"
    assert _answer("English Name", "محمد حسن") == "Mohamed Hassan"


def test_a_name_list_hit_ignores_hamza_spelling() -> None:
    assert translate("اسامة") == translate("أسامة") == "Osama"


def test_a_name_on_no_list_is_spelled_out() -> None:
    assert script_of(translate("Zxqvor")) == "ar"
    assert translate("زكسقور").isascii()


def test_a_form_that_names_no_language_gets_the_name_as_typed() -> None:
    assert name_in("محمد", None, "Mohamed") == "محمد"
