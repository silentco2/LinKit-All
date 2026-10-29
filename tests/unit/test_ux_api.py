# ruff: noqa: F811
"""UX backend extras: presets, the plain-language reason on job rows, the go-live card data."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_api import SAME_ORIGIN, client, mem_keyring  # noqa: F401  (fixtures)

from linkit_all.core.models import Job, JobEvent, JobState, TailoredCV, Tier, utcnow
from linkit_all.core.presets import PACE, PICKINESS
from linkit_all.core.search import SearchConfig
from linkit_all.core.state import transition
from linkit_all.matching.reasons import job_reason
from linkit_all.matching.rules import rule_violation


def put_cfg(client: TestClient, **sections: dict[str, Any]) -> None:
    body = SearchConfig.model_validate(sections).model_dump(mode="json")
    assert client.put("/api/search", json=body, headers=SAME_ORIGIN).status_code == 200


# --- presets ------------------------------------------------------------------------


def test_presets_payload_and_current(client: TestClient) -> None:
    got = client.get("/api/presets").json()
    assert got["pace"] == PACE and got["pickiness"] == PICKINESS
    assert got["defaults"] == SearchConfig().model_dump(mode="json")
    assert got["current"] == {"pace": "balanced", "pickiness": "balanced"}  # nothing saved yet

    put_cfg(client, apply=PACE["careful"], matching=PICKINESS["wide"])
    assert client.get("/api/presets").json()["current"] == {"pace": "careful", "pickiness": "wide"}

    put_cfg(client, apply={**PACE["fast"], "min_pause_s": 11}, matching={"tier_high": 10})
    assert client.get("/api/presets").json()["current"] == {"pace": None, "pickiness": None}


# --- reason: one case per code -------------------------------------------------------

JOB = dict(source="x", title="Backend Developer", company="Acme", location="Cairo",
           dedupe_hash="h", data={})  # fmt: skip
NOW = utcnow()


def drop(job: Job, cfg: SearchConfig) -> tuple[str, str | None, dict[str, Any]]:
    """The event rank.py would write: the real rule message, no stage code."""
    message = rule_violation(job, cfg, NOW)
    assert message is not None
    return message, None, {}


def reason_of(job: Job, event: tuple[str, str | None, dict[str, Any]] | None = None) -> Any:
    job.state = JobState.filtered_out
    return job_reason(job, event)


@pytest.mark.parametrize(
    ("filters", "search", "job", "code", "text", "params"),
    [
        ({"title_include": ["python"]}, {}, {}, "title_not_included",
         "Title has none of your wanted words", {}),
        ({"title_exclude": ["intern"]}, {}, {"title": "Intern Developer"}, "title_excluded",
         'Title contains "intern"', {"word": "intern"}),
        ({"work_modes": ["remote"]}, {}, {"location": "Hybrid, Cairo"}, "work_mode",
         "Work mode hybrid is not one you chose", {"mode": "hybrid"}),
        ({"locations": ["Dubai"]}, {}, {}, "location",
         "Location not in your places", {"location": "Cairo"}),
        ({"seniority": ["junior"]}, {}, {"title": "Senior Developer"}, "seniority",
         "Seniority senior is not one you want", {"level": "senior"}),
        ({}, {"posted_within_days": 14}, {"posted_at": NOW - timedelta(days=40)}, "too_old",
         "Posted 40 days ago", {"limit": 14, "days": 40}),
        ({"salary_floor_monthly": 50000, "salary_currency": "EGP"}, {},
         {"data": {"salary_max": 20000, "salary_currency": "EGP", "salary_interval": "month"}},
         "salary", "Salary below your floor", {"amount": 20000, "currency": "EGP"}),
        ({"company_blacklist": ["Acme"]}, {}, {}, "blacklist", "Company on your blacklist", {}),
    ],
)  # fmt: skip
def test_reason_for_each_hard_rule(
    filters: dict[str, Any],
    search: dict[str, Any],
    job: dict[str, Any],
    code: str,
    text: str,
    params: dict[str, Any],
) -> None:
    cfg = SearchConfig.model_validate({"filters": filters, "search": search})
    row = Job(**{**JOB, **job})
    assert reason_of(row, drop(row, cfg)) == (text, code, params)


def test_reason_for_posting_without_a_date_uses_the_limit() -> None:
    row = Job(**JOB)
    event = ("posted more than 14 days ago", None, {})
    assert reason_of(row, event) == ("Posted more than 14 days ago", "too_old", {"limit": 14})


def test_reason_for_company_rule_and_trust_drops() -> None:
    row = Job(**JOB)
    assert reason_of(row, ("already in your pipeline for this company", None, {}))[1:] == (
        "one_per_company",
        {},
    )
    better = reason_of(row, ("a better match at this company ranked higher", None, {}))
    assert better[1] == "one_per_company_better"
    scam = reason_of(row, ("looks like a scam (score 72): fees", "scam_suspected", {"score": 72}))
    assert scam == ("Likely scam (score 72)", "scam", {"score": 72})
    ghost = reason_of(row, ("looks like a ghost job", "ghost_suspected", {"score": 55}))
    assert ghost == ("Possibly stale posting (score 55)", "ghost", {"score": 55})
    reported = reason_of(row, ("you reported this posting", "trust_reported", {}))
    assert reported == ("You reported this posting", "reported", {})
    assert reason_of(row, ("something new", None, {})) == ("Something new", "other", {})
    assert reason_of(row, None) == ("Filtered out by your rules", "other", {})


def test_reason_for_low_tier() -> None:
    row = Job(**JOB, state=JobState.below_threshold, score=3)
    assert job_reason(row) == ("AI score 3 of 10", "low_score", {"score": 3, "out_of": 10})
    row.score = None
    assert job_reason(row) == ("Outside your top matches", "low_rank", {})
    row.data = {"trust": {"ghost_demoted": True, "ghost": {"score": 55}}}
    assert job_reason(row) == ("Possibly stale posting (score 55)", "ghost", {"score": 55})


@pytest.mark.parametrize("state", [JobState.ranked, JobState.awaiting_review, JobState.applied])
def test_no_reason_for_normal_states(state: JobState) -> None:
    assert job_reason(Job(**JOB, state=state, score=6)) is None


# --- reason through GET /api/jobs and the job detail ----------------------------------


def seed(client: TestClient, title: str, state: JobState, **kw: Any) -> int:
    """A job that really walked to `state`, so its events are the ones the pipeline writes."""
    message, code, params = kw.pop("drop", ("", None, {}))
    with client.app.state.db.begin() as s:  # type: ignore[attr-defined]
        job = Job(source="x", url=f"https://x/{title}", title=title, company=title,
                  dedupe_hash=title, state=JobState.enriched, **kw)  # fmt: skip
        s.add(job)
        s.flush()
        if state == JobState.filtered_out:
            transition(s, job, state, message, code=code, params=params)
        else:
            job.state = state
        return job.id


def test_jobs_rows_carry_reason(client: TestClient) -> None:
    out = seed(client, "Cut", JobState.filtered_out, drop=("company is blacklisted", None, {}))
    again = seed(client, "Again", JobState.filtered_out, drop=("title has none", None, {}))
    with client.app.state.db.begin() as s:  # type: ignore[attr-defined]
        job = s.get_one(Job, again)  # dropped, re-checked, dropped again: the last drop counts
        transition(s, job, JobState.enriched, "passes your filters now: checked again")
        transition(s, job, JobState.filtered_out, "location 'Paris' not in your locations")
    low = seed(client, "Low", JobState.below_threshold, score=3, tier=Tier.low)
    mid = seed(client, "Mid", JobState.awaiting_review, score=6, tier=Tier.mid)

    rows = {r["id"]: r for r in client.get("/api/jobs").json()}
    assert rows[out]["reason"] == "Company on your blacklist" and rows[out]["reason_code"] == (
        "blacklist"
    )
    assert rows[again]["reason_code"] == "location"
    assert rows[again]["reason_params"] == {"location": ""}
    assert rows[low]["reason"] == "AI score 3 of 10" and rows[low]["reason_code"] == "low_score"
    assert rows[mid]["reason"] is None and rows[mid]["reason_code"] is None
    assert rows[mid]["reason_params"] == {}

    detail = client.get(f"/api/jobs/{out}").json()
    assert detail["reason_code"] == "blacklist" and detail["state"] == "filtered_out"
    assert client.get(f"/api/jobs/{mid}").json()["reason"] is None
    only = client.get("/api/jobs", params={"state": "awaiting_review"}).json()
    assert [r["reason"] for r in only] == [None]


# --- go-live card -----------------------------------------------------------------------


def dry_run(client: TestClient, title: str, shots: int = 1, code: str = "dry_run_filled") -> int:
    """A job with a dry-run event: returns the event id."""
    job_id = seed(client, title, JobState.enriched)
    with client.app.state.db.begin() as s:  # type: ignore[attr-defined]
        job = s.get_one(Job, job_id)
        job.state = JobState.applying
        event = JobEvent(job=job, from_state=job.state, to_state=job.state, code=code,
                         message="dry run", artifacts=[f"{title}-{i}.png" for i in range(shots)])  # fmt: skip
        s.add(event)
        s.flush()
        return event.id


def test_golive_without_samples(client: TestClient) -> None:
    got = client.get("/api/golive").json()
    assert got["eligible"] is False and got["live"] is False and got["samples"] == []
    assert got["checklist"] == {"cv_approved": False, "answers_reviewed": False,
                                "caps_set": True, "confirm_each": True}  # fmt: skip


def test_golive_samples_are_recent_dry_runs_with_screenshots(client: TestClient) -> None:
    dry_run(client, "Email", code="dry_run_email")  # not a filled form
    dry_run(client, "NoShots", shots=0)
    old = dry_run(client, "A")
    dry_run(client, "B", shots=2)
    dry_run(client, "C", code="dry_run_agent")
    last = dry_run(client, "D")
    with client.app.state.db.begin() as s:  # type: ignore[attr-defined]
        job_d = s.get_one(JobEvent, last).job_id
        s.add(TailoredCV(job_id=job_d, docx_path="d.docx", pdf_path="d.pdf"))
        # a second dry run of the same job must not make a second sample
        s.add(JobEvent(job_id=job_d, from_state=JobState.applying, to_state=JobState.applying,
                       code="dry_run_filled", artifacts=["again.png"]))  # fmt: skip

    got = client.get("/api/golive").json()
    assert got["eligible"] is True
    titles = [x["title"] for x in got["samples"]]
    assert titles == ["D", "C", "B"] and old  # newest first, at most 3
    d, c, b = got["samples"]
    assert d["tailored"] is True and c["tailored"] is False
    assert len(b["screenshots"]) == 2
    event_url = d["screenshots"][0]
    assert event_url.startswith(f"/api/jobs/{d['job_id']}/events/") and event_url.endswith("/0")
    assert set(d) == {"job_id", "title", "company", "screenshots", "tailored"}


def test_golive_screenshot_url_is_servable(client: TestClient) -> None:
    shot = client.app.state.settings.data_dir / "applications" / "form.png"  # type: ignore[attr-defined]
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(b"png")
    job_id = seed(client, "Form", JobState.enriched)
    with client.app.state.db.begin() as s:  # type: ignore[attr-defined]
        job = s.get_one(Job, job_id)
        s.add(JobEvent(job=job, from_state=job.state, to_state=job.state, code="dry_run_filled",
                       artifacts=[str(shot)]))  # fmt: skip
    url = client.get("/api/golive").json()["samples"][0]["screenshots"][0]
    assert client.get(url).status_code == 200


def test_golive_checklist_flags(client: TestClient) -> None:
    client.put("/api/profile", json={"full_name": "J", "email": "j@x.io"}, headers=SAME_ORIGIN)
    checklist = client.get("/api/golive").json()["checklist"]
    assert checklist["cv_approved"] is False  # no CV uploaded yet

    from test_tailor import make_cv

    cv = make_cv(client.app.state.settings.data_dir.parent / "cv.docx").read_bytes()  # type: ignore[attr-defined]
    client.post("/api/profile/cv", params={"filename": "cv.docx"}, content=cv, headers=SAME_ORIGIN)
    assert client.get("/api/golive").json()["checklist"]["cv_approved"] is True

    # saving the untouched defaults is not "reviewed"; a changed answer is
    client.put("/api/profile/answers", json={}, headers=SAME_ORIGIN)
    assert client.get("/api/golive").json()["checklist"]["answers_reviewed"] is False
    body = {"authorized_countries": ["Egypt"]}
    client.put("/api/profile/answers", json=body, headers=SAME_ORIGIN)
    assert client.get("/api/golive").json()["checklist"]["answers_reviewed"] is True

    put_cfg(client, apply={"daily_cap_per_site": 41, "submit_without_asking": True, "live": True})
    got = client.get("/api/golive").json()
    assert got["live"] is True
    assert got["checklist"]["caps_set"] is False and got["checklist"]["confirm_each"] is False
    put_cfg(client, apply={"daily_cap_per_site": 40})
    assert client.get("/api/golive").json()["checklist"]["caps_set"] is True
