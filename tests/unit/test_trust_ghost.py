# ruff: noqa: RUF001
"""Offline ghost scorer: every signal in English and Arabic, the text cap, and batched history."""

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event

from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobSighting, Run
from linkit_all.matching.trust import Verdict
from linkit_all.matching.trust.ghost import (
    NO_HISTORY,
    GhostHistory,
    ghost_histories,
    has_pay,
    score_ghost,
    vagueness,
)
from linkit_all.matching.trust.normalize import light

NOW = datetime(2026, 10, 25, 12, 0)

SPECIFIC = (
    "You will report to the VP of Engineering and lead a team of 6 engineers building the Kafka "
    "ingestion platform. Responsibilities include designing Postgres schemas, deploying services "
    "to AWS with Terraform, reviewing pull requests and writing runbooks for on-call. "
    "Requirements: 5+ years of backend experience using Python or Go, strong SQL, and experience "
    "operating systems that process 20 million events per day. Salary $120,000 - $150,000 per year. "
) * 4


def run(
    desc: str = SPECIFIC,
    *,
    title: str = "Backend Engineer",
    posted: datetime | None = None,
    history: GhostHistory = NO_HISTORY,
    salary: Any = None,
) -> Verdict:
    return score_ghost(title, "Acme", desc, posted, salary, history, NOW)


def codes(v: Verdict) -> dict[str, int]:
    return {s.code: s.weight for s in v.signals}


def hist(**kw: Any) -> GhostHistory:
    base: dict[str, Any] = {
        "first_seen": None,
        "seen_runs": 0,
        "span_days": 0.0,
        "urls_seen": 0,
        "company_open_now": 0,
        "company_open_median": 0.0,
    }
    return GhostHistory(**(base | kw))


# ---- time signals ------------------------------------------------------------------------------


@pytest.mark.parametrize(("days", "weight"), [(10, None), (44, None), (45, 15), (89, 15), (90, 25)])
def test_stale_posting_tiers(days: int, weight: int | None) -> None:
    assert codes(run(posted=NOW - timedelta(days=days))).get("stale_posting") == weight


def test_age_uses_first_seen_when_posted_missing_or_later() -> None:
    assert codes(run(history=hist(first_seen=NOW - timedelta(days=100)))).get("stale_posting") == 25
    v = run(posted=NOW - timedelta(days=5), history=hist(first_seen=NOW - timedelta(days=50)))
    assert codes(v).get("stale_posting") == 15
    assert "stale_posting" not in codes(run(posted=NOW + timedelta(days=3)))  # future date ignored


def test_aware_datetimes_are_accepted() -> None:
    v = run(posted=(NOW - timedelta(days=100)).replace(tzinfo=UTC))
    assert codes(v)["stale_posting"] == 25


def test_still_open_tiers_and_minimum_runs() -> None:
    assert codes(run(history=hist(seen_runs=4, span_days=30)))["still_open"] == 15
    assert codes(run(history=hist(seen_runs=6, span_days=60)))["still_open"] == 25
    assert "still_open" not in codes(run(history=hist(seen_runs=3, span_days=90)))
    assert "still_open" not in codes(run(history=hist(seen_runs=9, span_days=29)))


def test_stale_and_still_open_share_a_budget_of_30() -> None:
    v = run(posted=NOW - timedelta(days=120), history=hist(seen_runs=8, span_days=100))
    c = codes(v)
    assert c["stale_posting"] == 25
    assert c["still_open"] == 5
    mid = run(posted=NOW - timedelta(days=50), history=hist(seen_runs=4, span_days=40))
    assert codes(mid)["stale_posting"] + codes(mid)["still_open"] == 30


def test_reposted_under_new_url() -> None:
    assert codes(run(history=hist(urls_seen=2)))["reposted"] == 20
    assert "reposted" not in codes(run(history=hist(urls_seen=1)))


def test_hiring_surge() -> None:
    assert (
        codes(run(history=hist(company_open_now=30, company_open_median=10)))["hiring_surge"] == 10
    )
    assert "hiring_surge" not in codes(
        run(history=hist(company_open_now=30, company_open_median=11))
    )
    assert "hiring_surge" not in codes(
        run(history=hist(company_open_now=30, company_open_median=0))
    )
    assert "hiring_surge" not in codes(
        run(history=hist(company_open_now=19, company_open_median=1))
    )


# ---- text signals ------------------------------------------------------------------------------


def test_specific_description_is_not_vague() -> None:
    assert vagueness(SPECIFIC, "Backend Engineer", False)[0] == 0
    assert "vague_description" not in codes(run())


def test_vague_description_english_scaled_to_20() -> None:
    desc = "We are a fast-paced team looking for a passionate rockstar to join us. " * 3
    v = run(desc)
    assert vagueness(desc, "Engineer", False)[0] == 30
    assert codes(v)["vague_description"] == 20


def test_tiny_description_is_vague_but_empty_is_not_loaded() -> None:
    assert vagueness("Great job apply now", "x", False)[0] == 30
    assert vagueness("", "x", False) == (0, "")
    v = run("")
    assert "vague_description" not in codes(v)
    assert "no_salary" not in codes(v)


def test_vague_description_arabic() -> None:
    desc = "نبحث عن موظف شغوف للانضمام الى فريقنا في بيئة عمل ديناميكية وسريعة الوتيرة. " * 2
    v = run(desc, title="موظف")
    assert codes(v)["vague_description"] == 20


def test_question_marks_and_buzzword_density() -> None:
    base = " ".join(["word"] * 300)
    assert vagueness(base, "t", True)[0] == 25  # no specificity flags at all
    assert vagueness(base + " ?" * 6, "t", True)[0] == 30
    buzz = base + " rockstar ninja guru maverick"  # > 1 per 100 words
    assert vagueness(buzz, "t", True)[0] == 30
    # buzzwords present in the title are ignored
    assert vagueness(buzz, "Rockstar Ninja Guru Maverick", True)[0] == 25


@pytest.mark.parametrize(
    "text",
    [
        "Candidates need 3 years of experience in welding.",
        "يتطلب الدور خبرة ٣ سنوات في المبيعات",
        "المطلوب سنوات خبرة في المحاسبة",
        "الوظيفة يتبع صاحبها مدير المبيعات",
        "You will report to the CTO",
    ],
)
def test_specificity_flag_reduces_penalty(text: str) -> None:
    pad = " ".join(["filler"] * 300)
    assert vagueness(f"{text} {pad}", "t", True)[0] < 25


def test_arabic_reporting_years_and_scope_count_as_flags() -> None:
    pad = " ".join(["كلمة"] * 300)
    three = f"يتبع المدير العام. المطلوب خبرة ٥ سنوات. فريق من ٨ موظفين. {pad}"
    assert vagueness(three, "t", True)[0] == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Pay is $20/hr plus bonus", True),
        ("Salary: $50,000 - $70,000", True),
        ("Salary 15,000-20,000 EGP", True),
        ("5000 egp monthly", True),
        ("الراتب ٥٠٠٠ جنيه شهريا", True),
        ("Raised $50 million in funding", False),
        ("Competitive salary and benefits", False),
        ("Job 12345 in building 7", False),
    ],
)
def test_pay_detector(text: str, expected: bool) -> None:
    assert has_pay(light(text)) is expected


@pytest.mark.parametrize(
    "text",
    [
        "We are always looking for great people.",
        "Join our talent pool for future opportunities.",
        "This is a general application for any role.",
        "Submit an expression of interest.",
        "Help us build a talent pipeline of engineers.",
        "نبحث دائما عن المواهب",
        "انضم الى بنك المواهب لدينا",
        "فرص مستقبلية في شركتنا",
    ],
)
def test_evergreen_language(text: str) -> None:
    assert codes(run(f"{text} {SPECIFIC}"))["evergreen_language"] == 15


def test_data_pipeline_is_not_evergreen() -> None:
    assert "evergreen_language" not in codes(
        run(f"Own the CI pipeline and data pipeline. {SPECIFIC}")
    )


@pytest.mark.parametrize(
    "title",
    [
        "Various Positions",
        "Multiple roles - Cairo",
        "Open Application",
        "Talent Pool",
        "وظائف متعددة",
        "بنك المواهب",
    ],
)
def test_vague_title(title: str) -> None:
    assert codes(run(title=title))["vague_title"] == 10


def test_no_salary_small_and_cleared_by_structured_pay() -> None:
    desc = SPECIFIC.replace("Salary $120,000 - $150,000 per year.", "")
    assert codes(run(desc))["no_salary"] == 5
    assert "no_salary" not in codes(run(desc, salary={"min": 1000}))
    assert "no_salary" not in codes(run())


# ---- scoring, cap, bands -----------------------------------------------------------------------


def test_text_only_never_reaches_likely() -> None:
    desc = "We are always looking for a rockstar. Join our talent pool. " * 2
    v = run(desc, title="Various Positions")
    assert sum(s.weight for s in v.signals) == 45
    assert v.score == 45
    assert v.band == "medium"
    assert {"vague_description", "evergreen_language", "vague_title"} <= set(codes(v))


def test_fresh_specific_job_is_low() -> None:
    fresh = hist(first_seen=NOW - timedelta(days=3), seen_runs=1, urls_seen=1)
    v = run(posted=NOW - timedelta(days=3), history=fresh)
    assert v.score == 0
    assert v.band == "low"
    assert v.signals == ()


def test_old_evergreen_vague_reposted_job_is_high() -> None:
    desc = "We are always looking for a passionate rockstar. Join our talent pool for future opportunities."
    old = hist(first_seen=NOW - timedelta(days=110), seen_runs=6, span_days=110, urls_seen=3)
    v = run(desc, title="Various Positions", posted=NOW - timedelta(days=120), history=old)
    assert v.band == "high"
    assert v.score >= 50
    assert {"stale_posting", "still_open", "reposted", "evergreen_language", "vague_title"} <= set(
        codes(v)
    )


def test_time_evidence_bands() -> None:
    two = run(posted=NOW - timedelta(days=100), history=hist(urls_seen=2))
    assert (two.score, two.band) == (45, "medium")  # 25 + 20
    assert (
        run(
            posted=NOW - timedelta(days=100), title="Open Application", history=hist(urls_seen=2)
        ).band
        == "high"
    )
    assert run(posted=NOW - timedelta(days=50)).band == "low"


def test_evidence_is_short() -> None:
    v = run(
        "always looking " + "x " * 5000, title="Open Application", posted=NOW - timedelta(days=99)
    )
    assert all(len(s.evidence) <= 80 for s in v.signals)


def test_speed_report() -> None:
    desc = (SPECIFIC + " Join our talent pool. " + "We value teamwork and growth. " * 40)[:3000]
    start = time.perf_counter()
    for i in range(10_000):
        score_ghost(
            f"Engineer {i}", "Acme", desc, NOW - timedelta(days=i % 120), None, NO_HISTORY, NOW
        )
    print(f"score_ghost x10000: {time.perf_counter() - start:.2f}s")  # reported, never asserted


# ---- ghost_histories ---------------------------------------------------------------------------


def seed(tmp_path: Path) -> tuple[Any, list[int], datetime]:
    db = init_db(tmp_path / "g.db")
    base = datetime(2026, 6, 1)
    with db.begin() as s:
        runs = []
        for _ in range(5):
            r = Run()
            s.add(r)
            s.flush()
            runs.append(r.id)
        ids = []
        for i in range(6):
            j = Job(
                source="t",
                url=f"https://x.io/{i}",
                title=f"J{i}",
                company="Acme" if i < 4 else "Beta",
                dedupe_hash=f"h{i}",
            )
            s.add(j)
            s.flush()
            ids.append(j.id)

        def sight(job: int, run_i: int, days: int, url: str) -> None:
            s.add(
                JobSighting(
                    job_id=ids[job],
                    run_id=runs[run_i],
                    seen_at=base + timedelta(days=days),
                    url=url,
                    source="t",
                )
            )

        for k in range(5):  # job 0: every run, 30 days apart, URL changed once
            sight(0, k, 30 * k, "https://x.io/0" if k < 3 else "https://x.io/0b")
        sight(1, 0, 0, "u1")
        sight(2, 0, 0, "u2")
        sight(2, 4, 120, "u2")
        sight(3, 4, 120, "u3")
        for k in range(4):  # Beta: one job per early run, nothing in the latest run
            sight(4, k, 30 * k, "u4")
    return db, ids, base


def test_ghost_histories_seeded(tmp_path: Path) -> None:
    db, ids, base = seed(tmp_path)
    with db() as s:
        jobs = [j for i in ids if (j := s.get(Job, i)) is not None]
        h = ghost_histories(s, jobs)
        assert ghost_histories(s, []) == {}
    h0 = h[ids[0]]
    assert (h0.first_seen, h0.seen_runs, h0.urls_seen) == (base, 5, 2)
    assert h0.span_days == pytest.approx(120)
    # Acme: latest run has jobs 0, 2, 3 -> 3 now; earlier runs hold 3, 1, 1, 1 -> median 1
    assert h0.company_open_now == 3
    assert h0.company_open_median == 1.0
    assert h[ids[1]].seen_runs == 1
    assert h[ids[1]].span_days == 0
    beta = h[ids[4]]
    assert beta.company_open_now == 0
    assert beta.company_open_median == 1.0
    no_sightings = h[ids[5]]  # company stats still apply to a job with no sightings of its own
    assert (no_sightings.first_seen, no_sightings.seen_runs, no_sightings.urls_seen) == (None, 0, 0)


def test_ghost_histories_bounded_queries(tmp_path: Path) -> None:
    db = init_db(tmp_path / "b.db")
    base = datetime(2026, 1, 1)
    with db.begin() as s:
        r1, r2 = Run(), Run()
        s.add_all([r1, r2])
        s.flush()
        for i in range(1000):
            j = Job(
                source="t", url=f"https://x.io/{i}", title="T", company=f"C{i}", dedupe_hash=f"h{i}"
            )
            s.add(j)
            s.flush()
            s.add(JobSighting(job_id=j.id, run_id=r1.id, seen_at=base, url=j.url, source="t"))
            s.add(
                JobSighting(
                    job_id=j.id,
                    run_id=r2.id,
                    seen_at=base + timedelta(days=40),
                    url=j.url,
                    source="t",
                )
            )
    with db() as s:
        jobs = list(s.query(Job))
        n = 0

        def count(*_a: object) -> None:
            nonlocal n
            n += 1

        bind = s.get_bind()
        event.listen(bind, "before_cursor_execute", count)
        out = ghost_histories(s, jobs)
        event.remove(bind, "before_cursor_execute", count)
    assert len(out) == 1000
    assert n <= 5
