"""linkit apply-probe: which jobs it picks and how it reports them."""

from pathlib import Path

from linkit_all.apply.probe import ProbeRow, pick, report
from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobState


def test_one_job_per_source_failed_first_and_only_with_an_apply_link(tmp_path: Path) -> None:
    db = init_db(tmp_path / "db.sqlite")
    rows = [
        ("glassdoor", JobState.scored, 9, "https://glassdoor.com/j/1"),
        (
            "glassdoor",
            JobState.failed,
            5,
            "https://glassdoor.com/j/2",
        ),  # failed beats a higher score
        ("telegram", JobState.below_threshold, 2, "mailto:hr@acme.test"),
        ("forasna", JobState.scored, 8, "not a link"),
        ("lever", JobState.applied, 9, "https://jobs.lever.co/acme/1"),  # already done
    ]
    with db.begin() as s:
        for n, (source, state, score, link) in enumerate(rows):
            s.add(Job(source=source, url=link, title="t", company="c", location="", description="",
                      dedupe_hash=str(n), state=state, score=score, data={"apply_url": link}))  # fmt: skip
    got = pick(db)
    with db() as s:
        picked = {s.get_one(Job, i).source: s.get_one(Job, i).url for i in got}
    assert picked == {"glassdoor": "https://glassdoor.com/j/2", "telegram": "mailto:hr@acme.test"}
    assert pick(db, ids=[5]) == [5]


def test_report_is_a_markdown_table(tmp_path: Path) -> None:
    row = ProbeRow(7, "builtin", "builtin.com", "needs_user", "a | b", "apply_by_hand", "x.png")
    text = report([row], tmp_path).read_text("utf-8")
    assert "| 7 | builtin | builtin.com | needs_user | apply_by_hand | a / b | x.png |" in text


def test_a_borrowed_job_goes_back_with_its_card_closed(tmp_path: Path) -> None:
    from linkit_all.apply.probe import _queue, give_back
    from linkit_all.core.models import ActionItem, ActionKind, ActionStatus, JobEvent
    from linkit_all.core.state import transition

    db = init_db(tmp_path / "db.sqlite")
    with db.begin() as s:
        s.add(Job(source="x", url="https://x.test/1", title="t", company="c", location="",
                  description="", dedupe_hash="1", state=JobState.below_threshold, data={}))  # fmt: skip
    assert _queue(db, 1) == JobState.below_threshold
    with db.begin() as s:  # what a park does
        job = s.get_one(Job, 1)
        transition(s, job, JobState.tailored, "cv")
        transition(s, job, JobState.applying, "fill")
        transition(s, job, JobState.needs_user, "stuck")
        s.add(ActionItem(job_id=1, kind=ActionKind.apply_by_hand))
    give_back(db, 1, JobState.below_threshold)
    with db() as s:
        assert s.get_one(Job, 1).state == JobState.below_threshold
        assert s.query(ActionItem).one().status == ActionStatus.dismissed
        assert s.query(JobEvent).filter_by(code="probe_restored").count() == 1


def test_restore_puts_back_what_an_old_test_left_parked(tmp_path: Path) -> None:
    from linkit_all.apply.probe import _queue, give_back_all
    from linkit_all.core.state import transition

    db = init_db(tmp_path / "db.sqlite")
    with db.begin() as s:
        for n, state in enumerate([JobState.below_threshold, JobState.failed], 1):
            s.add(Job(source="x", url=f"https://x.test/{n}", title="t", company="c", location="",
                      description="", dedupe_hash=str(n), state=state, data={}))  # fmt: skip
    for job_id in (1, 2):
        _queue(db, job_id)
        with db.begin() as s:
            transition(s, s.get_one(Job, job_id), JobState.failed, "crashed")
    assert give_back_all(db) == 1  # the weak match goes back; the failed one was yours anyway
    assert give_back_all(db) == 0
    with db() as s:
        assert s.get_one(Job, 1).state == JobState.below_threshold
        assert s.get_one(Job, 2).state == JobState.failed
