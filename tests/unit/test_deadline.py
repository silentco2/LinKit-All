"""B5 closing date from the description (matching/deadline.py)."""

from dataclasses import dataclass
from datetime import date, datetime

import pytest

from linkit_all.matching.deadline import closes_soon, closing_date, deadline_first

TODAY = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 9, 0)


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("Applications close on 16 November 2026.", date(2026, 11, 16)),
        ("Deadline: Nov 16, 2026", date(2026, 11, 16)),
        ("Apply by 2026-11-20 to be considered.", date(2026, 11, 20)),
        ("Closing date: 20/11/2026", date(2026, 11, 20)),
        ("Closing date: 11/20/2026", date(2026, 11, 20)),
        ("This vacancy closes 16th of November", date(2026, 11, 16)),
        ("Apply before January 5", date(2027, 1, 5)),  # no year: the next one
        ("آخر موعد للتقديم ١٦ نوفمبر ٢٠٢٦", date(2026, 11, 16)),
        ("Deadline 1 Dec 2026. Applications also close on 20 Nov 2026.", date(2026, 11, 20)),
    ],
)
def test_closing_date(text: str, want: date) -> None:
    assert closing_date(text, TODAY) == want


@pytest.mark.parametrize(
    "text",
    [
        "Posted on 16 November 2026. We work closely with banks.",
        "We meet every deadline. Founded in March 2019.",
        "Deadline: 31 February 2026",
        "The deadline will be announced later, and a long sentence follows 16 November 2026.",
        "",
    ],
)
def test_no_closing_date(text: str) -> None:
    assert closing_date(text, TODAY) is None


def test_closes_soon_is_today_to_three_days() -> None:
    assert closes_soon("Apply by 2026-11-14", NOW)
    assert closes_soon("Apply by 2026-11-17", NOW)
    assert not closes_soon("Apply by 2026-11-18", NOW)
    assert not closes_soon("Apply by 2026-11-13", NOW)  # already closed: not urgent
    assert not closes_soon("No date here", NOW)


@dataclass
class Ad:
    name: str
    description: str


def test_deadline_first_keeps_the_order_otherwise() -> None:
    ads = [
        Ad("a", "Great job."),
        Ad("b", "Deadline: 16 Nov 2026"),
        Ad("c", "Deadline: 16 Dec 2026"),
        Ad("d", "Apply by 2026-11-15"),
    ]
    assert [a.name for a in deadline_first(ads, NOW)] == ["b", "d", "a", "c"]
