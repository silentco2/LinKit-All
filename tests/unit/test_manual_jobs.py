"""Jobs added by hand (sources/manual.py, POST /api/jobs/add): read without AI, stored at
`enriched`, past the hard rules, the one-per-company rule and the off-title trash."""

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_api import SAME_ORIGIN, client  # noqa: F401
from test_matching import CFG, db, fake_embed, job  # noqa: F401

from linkit_all.api import routes
from linkit_all.core.models import Job, JobEvent, JobState
from linkit_all.matching.rank import rank_jobs
from linkit_all.sources.base import JobStub
from linkit_all.sources.manual import store

POSTING = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Backend Engineer",
    "description": "<p>Build Python APIs for payments.</p>",
    "hiringOrganization": {"@type": "Organization", "name": "Acme"},
    "jobLocation": {"@type": "Place", "address": {"addressLocality": "Berlin"}},
}
PAGES = {
    "job-boards.greenhouse.io/acme/jobs/123": "<html><head><title>Job</title>"
    f'<script type="application/ld+json">{json.dumps(POSTING)}</script></head><body></body></html>',
    "app.example.com/jobs/7": '<html><head><title>Loading</title></head><body><div id="root">'
    "</div></body></html>",
}


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoint's HTTP client answers from PAGES (host + path); anything else is a 404."""

    def handler(req: httpx.Request) -> httpx.Response:
        page = PAGES.get(f"{req.url.host}{req.url.path}")
        return httpx.Response(404) if page is None else httpx.Response(200, text=page)

    monkeypatch.setattr(
        routes, "make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def add(c: TestClient, **body: Any) -> Any:
    return c.post("/api/jobs/add", json=body, headers=SAME_ORIGIN)


def test_add_links(client: TestClient, web: None) -> None:  # noqa: F811
    gh, js, gone = (f"https://{p}" for p in [*PAGES, "gone.example.org/jobs/1"])
    r = add(client, links=[gh, js, gone, gh, " "])
    assert r.status_code == 200
    got = {x["url"]: (x["status"], x["title"]) for x in r.json()["results"]}
    assert got == {gh: ("added", "Backend Engineer"), js: ("needs_text", ""),
                   gone: ("unreadable", "")}  # fmt: skip
    assert add(client, links=[gh]).json()["results"][0]["status"] == "duplicate"

    # the page JavaScript draws: its text pasted instead
    text = "We need a Go developer to build our billing services. " * 5
    r = add(client, links=[js], text=text, title="Go Developer", company="Initech")
    assert r.json()["results"][0]["status"] == "added"

    with client.app.state.db() as s:  # type: ignore[attr-defined]
        jobs = {j.title: j for j in s.scalars(select(Job))}
        codes = set(s.scalars(select(JobEvent.code)))
    assert set(jobs) == {"Backend Engineer", "Go Developer"}
    gh_job = jobs["Backend Engineer"]
    assert (gh_job.state, gh_job.source, gh_job.ats) == (JobState.enriched, "manual", "greenhouse")
    assert gh_job.data["manual"] and "Python APIs" in gh_job.description
    assert jobs["Go Developer"].company == "Initech" and "added_by_you" in codes


@pytest.mark.parametrize(
    "body",
    [
        {"links": ["not a link"]},
        {"links": []},
        {"links": ["https://a.example/1", "https://b.example/2"], "text": "x", "title": "T"},
        {"links": ["https://a.example/1"], "text": "the posting", "company": "C"},
    ],
)
def test_add_rejects(client: TestClient, body: dict[str, Any]) -> None:  # noqa: F811
    assert add(client, **body).status_code == 422


def test_manual_jobs_skip_the_hard_rules(db: sessionmaker[Session]) -> None:  # noqa: F811
    stub = JobStub(source="manual", url="https://x.example/sales", title="Sales Lead",
                   company="Acme", location="Berlin", description="Sell Python tooling")  # fmt: skip
    with db.begin() as s:  # a rule-filtered job at the same company
        s.add(job(title="Backend Engineer", company="Acme", state=JobState.enriched))
    assert store(db, stub)[0] == "added"
    rank_jobs(db, CFG, fake_embed)
    with db() as s:
        states = {j.title: j.state for j in s.scalars(select(Job))}
    # off-title, outside "egypt / remote", and a second job at Acme: ranked all the same
    assert states["Sales Lead"] == JobState.ranked


def test_a_rule_drop_comes_back_when_added_by_hand(db: sessionmaker[Session]) -> None:  # noqa: F811
    with db.begin() as s:
        s.add(job(title="Data Analyst", url="https://x.example/da", state=JobState.enriched))
        s.add(job(title="Scam Job", url="https://x.example/scam", state=JobState.filtered_out,
                  data={"trust_filter": "scam"}))  # fmt: skip
    rank_jobs(db, CFG, fake_embed)
    again = JobStub(source="manual", url="https://x.example/da", title="Data Analyst",
                    company="Acme")  # fmt: skip
    assert store(db, again)[0] == "brought_back"
    scam = JobStub(source="manual", url="https://x.example/scam", title="Scam Job", company="Acme")
    assert store(db, scam)[0] == "duplicate"  # a scam is cleared with "not a scam", not here
    rank_jobs(db, CFG, fake_embed)
    with db() as s:
        da = s.scalars(select(Job).filter_by(title="Data Analyst")).one()
    assert da.state == JobState.ranked and da.data["manual"]


def _pdf(text: str) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(72, 72, 520, 770), text, fontsize=10)
    return bytes(doc.tobytes())


def test_pdf_text_fills_the_paste_fields(client: TestClient) -> None:  # noqa: F811
    posting = "Backend Engineer\n\n" + "Build Python APIs for our payments team. " * 8
    r = client.post("/api/jobs/pdf-text?filename=job.pdf", content=_pdf(posting),
                    headers={**SAME_ORIGIN, "content-type": "application/octet-stream"})  # fmt: skip
    assert r.status_code == 200
    assert r.json()["title"] == "Backend Engineer" and "payments team" in r.json()["text"]
    for bad in (b"not a pdf", _pdf("Short")):  # broken file; a PDF with no real text (a scan)
        r = client.post("/api/jobs/pdf-text", content=bad, headers=SAME_ORIGIN)
        assert r.status_code == 422


def test_applied_before_on_the_job_page_and_add_results(client: TestClient, web: None) -> None:  # noqa: F811
    app_db = client.app.state.db  # type: ignore[attr-defined]
    with app_db.begin() as s:
        for title, company, state in [("Data Engineer", "Acme Inc.", JobState.applied),
                                      ("Old Post", "Unknown", JobState.applied),
                                      ("Still Queued", "ACME", JobState.queued_apply),
                                      ("Other Co Job", "Initech", JobState.applied)]:  # fmt: skip
            j = Job(source="t", url=f"https://x/{title}", title=title, company=company,
                    dedupe_hash=title, state=state)  # fmt: skip
            s.add(j)
            s.flush()
            if state == JobState.applied:
                s.add(JobEvent(job_id=j.id, to_state=JobState.applied, message="applied"))
    text = "We need a Go developer to build our billing services. " * 5
    r = add(client, links=["https://app.example.com/jobs/7"], text=text, title="Go Developer",
            company="ACME, Ltd.")  # fmt: skip
    got = r.json()["results"][0]
    assert [b["title"] for b in got["applied_before"]] == [
        "Data Engineer"
    ]  # not queued, not Initech
    detail = client.get(f"/api/jobs/{got['job_id']}").json()["applied_before"]
    assert detail[0]["title"] == "Data Engineer" and detail[0]["applied_at"]
    with app_db() as s:
        own = s.query(Job).filter_by(title="Data Engineer").one()
        unknown = s.query(Job).filter_by(title="Old Post").one()
    assert client.get(f"/api/jobs/{own.id}").json()["applied_before"] == []  # never itself
    assert client.get(f"/api/jobs/{unknown.id}").json()["applied_before"] == []  # "Unknown" never
