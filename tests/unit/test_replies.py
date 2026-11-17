"""Employer replies -> outcomes (apply/replies.py, C2). All mails are made up."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from loguru import logger

from linkit_all.apply.replies import Applied, apply_replies, classify, match
from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobState, Outcome

APPLIED = datetime(2026, 11, 1, tzinfo=UTC)


def at(days: int) -> datetime:
    return APPLIED + timedelta(days=days)


@pytest.mark.parametrize(
    ("subject", "text", "kind"),
    [
        (
            "Your application",
            "Unfortunately we have decided to move forward with other candidates.",
            "rejected",
        ),
        ("Update", "We regret to inform you that you were not selected.", "rejected"),
        (
            "Interview invitation",
            "We would like to invite you to an interview next week.",
            "interview",
        ),
        ("Next steps", "Please book a time to chat with our hiring manager.", "interview"),
        ("طلبك", "للأسف لم يتم اختيارك لهذه الوظيفة", "rejected"),
        ("Thanks for applying", "We received your application and will review it.", None),
        ("Update", "Unfortunately we cannot schedule an interview after all.", "rejected"),
    ],
)
def test_classify(subject: str, text: str, kind: str | None) -> None:
    assert classify(subject, text) == kind


JOBS = [
    Applied(1, "HP", "Data Engineer"),
    Applied(2, "Acme Labs", "Backend Engineer"),
    Applied(3, "Acme Labs", "Frontend Engineer"),
    Applied(4, "Globex", "Analyst"),
]


def test_match_by_sender_domain_name_and_title() -> None:
    assert match("talent@globex.com", "Your application", "", JOBS) == 4
    assert match("no-reply@greenhouse.io", "Globex: your application", "", JOBS) == 4
    assert match("x@hp.com", "Hello", "", JOBS) == 1
    # a short name only on a word boundary: "PHP" is not HP
    assert match("x@mail.io", "PHP developer role", "We use PHP.", JOBS) is None
    # two roles at one company: the title decides, or nothing does
    assert match("x@mail.io", "Acme Labs", "About the Backend Engineer role", JOBS) == 2
    assert match("x@mail.io", "Acme Labs", "About your application", JOBS) is None
    # two companies named: not sure, so nothing
    assert match("x@mail.io", "Globex and HP", "", JOBS) is None
    assert match("someone@gmail.com", "Hi", "", JOBS) is None


def seeded(tmp_path: Path) -> object:
    db = init_db(tmp_path / "t.db")
    with db.begin() as s:
        for jid, company, title in [(1, "HP", "Data Engineer"), (2, "Globex", "Analyst"),
                                    (3, "Initech", "Tester")]:  # fmt: skip
            s.add(Job(id=jid, source="t", url=f"https://x.io/{jid}", title=title, company=company,
                      dedupe_hash="h", state=JobState.applied,
                      data={"applied_at": APPLIED.isoformat()}))  # fmt: skip
        s.add(Job(id=4, source="t", url="https://x.io/4", title="Dev", company="Umbrella",
                  dedupe_hash="h", state=JobState.queued_apply))  # fmt: skip
    return db


def test_apply_replies_sets_outcomes_latest_wins_and_logs_no_mail_text(tmp_path: Path) -> None:
    db = seeded(tmp_path)
    marker = "PRIVATE-MAIL-BODY"
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")
    try:
        mails = [
            (
                at(5),
                "talent@globex.com",
                "Interview invitation",
                f"invite you to an interview {marker}",
            ),
            (at(9), "talent@globex.com", "Update", f"Unfortunately not selected {marker}"),
            (at(3), "x@hp.com", "Next steps", "We would like to speak with you"),
            (at(-5), "x@initech.com", "Update", "Unfortunately ..."),  # before applying
            (at(2), "x@umbrella.com", "Update", "Unfortunately ..."),  # not an applied job
            (at(2), "x@mail.io", "PHP meetup", "Unfortunately the PHP meetup is full"),
        ]
        counts = apply_replies(db, mails)  # type: ignore[arg-type]
    finally:
        logger.remove(sink)
    assert counts == {"read": 6, "rejected": 1, "interview": 2}
    with db() as s:  # type: ignore[operator]
        out = {j.id: j.outcome for j in s.query(Job)}
    assert out == {1: Outcome.interview, 2: Outcome.rejected, 3: None, 4: None}
    assert not any(marker in line for line in lines)


def test_a_user_set_outcome_is_never_changed_by_mail(tmp_path: Path) -> None:
    db = seeded(tmp_path)
    with db.begin() as s:  # type: ignore[attr-defined]
        job = s.get_one(Job, 2)
        job.outcome, job.data = Outcome.offer, {**job.data, "outcome_by": "user"}
    apply_replies(db, [(at(4), "talent@globex.com", "Update", "Unfortunately not selected")])  # type: ignore[arg-type]
    with db() as s:  # type: ignore[operator]
        assert s.get_one(Job, 2).outcome == Outcome.offer
