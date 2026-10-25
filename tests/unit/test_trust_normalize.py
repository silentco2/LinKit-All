# ruff: noqa: RUF001, RUF003
"""Evasion-proof text folding and clause-scoped negation."""

import pytest

from linkit_all.matching.trust.normalize import Clauses, fold, fold_variants, light


def test_nfkc_and_casefold() -> None:
    assert fold("ＷＨＡＴＳＡＰＰ") == "whatsapp"
    assert fold("Straße") == "strasse"


def test_cyrillic_and_greek_homoglyphs() -> None:
    assert fold("tеlеgram") == "telegram"  # Cyrillic е
    assert fold("ΤΕLEGRAM".lower()) == "telegram"  # Greek τ, ε


def test_invisible_chars_and_emoji_are_dropped() -> None:
    assert fold("tele​gram") == "telegram"
    assert fold("Tele😀gram") == "telegram"


def test_leetspeak_only_next_to_letters() -> None:
    assert fold("t3l3gr@m") == "telegram"
    assert fold("regi5tration f33") == "registration fee"
    assert fold("wh4t$app") == "whatsapp"
    assert fold("salary 5000 per week") == "salary 5000 per week"  # pure numbers untouched
    assert fold("US$500") == "us$500"


def test_one_has_two_readings() -> None:
    views = fold_variants("te1egram and reg1stration")
    assert any("telegram" in v for v in views)
    assert any("registration" in v for v in views)
    assert len(fold_variants("no digits here")) == 1


def test_email_survives_leet_folding() -> None:
    assert "@gmail.com" in fold("Mail jobs2024@gmail.com now")


def test_letter_spacing_collapses() -> None:
    assert fold("w h a t s a p p") == "whatsapp"
    assert fold("t-e-l-e-g-r-a-m") == "telegram"
    assert fold("a b c") == "a b c"  # too short to be an evasion
    assert fold("Step 1 2 3 4") == "step 1 2 3 4"  # digits are not letters


def test_arabic_variants() -> None:
    assert fold("رُسُومٌ") == fold("رسوم") == "رسوم"
    assert fold("مقابلـــة") == "مقابله"  # tatweel, teh marbuta -> heh
    assert fold("أإآ") == "ااا"
    assert fold("على") == "علي"
    assert light("٣٠٠٠ دولار") == "3000 دولار"
    assert light("٣٬٠٠٠") == "3,000"


def test_apostrophes_removed() -> None:
    assert fold("we don't charge") == "we dont charge"
    assert fold("we don’t charge") == "we dont charge"


def _negated(text: str, needle: str) -> bool:
    folded = fold(text)
    return Clauses(folded).negated(folded.index(needle))


@pytest.mark.parametrize(
    "text",
    [
        "there is no registration fee",
        "we never ask for payment",
        "without any deposit",
        "لا توجد رسوم تسجيل",
        "بدون رسوم",
    ],
)
def test_negation_suppresses(text: str) -> None:
    needle = (
        "رسوم"
        if "رسوم" in text
        else ("payment" if "payment" in text else "fee" if "fee" in text else "deposit")
    )
    assert _negated(text, needle)


@pytest.mark.parametrize(
    "text",
    [
        "you must pay the registration fee",
        "you cannot start without the registration fee",
        "no experience needed, registration fee applies",  # comma ends the negation's scope
        "we never charge. registration fee is due",
        "no cost but the registration fee is due",
        "لا توجد رسوم لكن يجب دفع رسوم",
        "لا توجد خبره ويجب دفع رسوم",
    ],
)
def test_coercion_and_clause_scope_keep_the_hit(text: str) -> None:
    needle = "رسوم" if "رسوم" in text else "fee"
    folded = fold(text)
    assert not Clauses(folded).negated(folded.rindex(needle))


def test_negation_only_looks_backwards() -> None:
    folded = fold("registration fee, no interview")
    assert not Clauses(folded).negated(folded.index("fee"))


def test_clause_helpers() -> None:
    folded = fold("add me on skype, thanks")
    cl = Clauses(folded)
    assert cl.clause(folded.index("skype")) == "add me on skype"
