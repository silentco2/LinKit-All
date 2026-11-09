"""Assist API for the LinkIt Fill extension: pairing token, origin, matching and "done"."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from linkit_all.api.app import create_app
from linkit_all.core.config import Settings
from linkit_all.core.models import ActionItem, ActionKind, ActionStatus, Job, JobEvent, JobState

BASE = "http://127.0.0.1:8765"
EXT = {"origin": "chrome-extension://abcdefghijklmnop"}
POST = "https://www.linkedin.com/jobs/view/42"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(data_dir=tmp_path / "data"))
    with app.state.db.begin() as s:
        job = Job(source="linkedin", url=POST, title="Backend Engineer", company="Acme",
                  location="Cairo", description="", dedupe_hash="h", state=JobState.needs_user,
                  data={"apply_url": POST, "cv_pdf": str(tmp_path / "cv.pdf")})  # fmt: skip
        s.add(job)
        s.flush()
        s.add(ActionItem(job_id=job.id, kind=ActionKind.apply_in_browser, code="apply_in_browser"))
    (tmp_path / "cv.pdf").write_bytes(b"%PDF-1.4 test")
    with TestClient(app, base_url=BASE) as c:
        yield c


def token(c: TestClient) -> dict[str, str]:
    return {"x-linkit-token": c.get("/api/assist/token").json()["token"]}


def test_every_call_needs_the_pairing_token(client: TestClient) -> None:
    assert client.get("/api/assist/hosts").status_code == 401
    assert client.get("/api/assist/hosts", headers={"x-linkit-token": "guess"}).status_code == 401
    other_site = {"sec-fetch-site": "cross-site"}
    assert client.get("/api/assist/token", headers=other_site).status_code == 403


def test_the_extension_origin_may_post_to_assist_only(client: TestClient) -> None:
    t = token(client)
    assert (
        client.post("/api/assist/done", json={"job_id": 99}, headers={**EXT, **t}).status_code
        == 404
    )
    assert client.put("/api/search", json={}, headers=EXT).status_code == 403  # nothing else


def test_match_cv_and_done(client: TestClient) -> None:
    t = token(client)
    assert client.get("/api/assist/hosts", headers=t).json() == {"hosts": ["linkedin.com"]}
    got = client.post(
        "/api/assist/match", json={"url": POST + "?trk=x"}, headers={**EXT, **t}
    ).json()
    assert got["title"] == "Backend Engineer" and got["hosts"] == ["linkedin.com"]
    other = client.post(
        "/api/assist/match", json={"url": "https://acme.test/x"}, headers={**EXT, **t}
    )
    assert other.status_code == 404
    assert client.get(f"/api/assist/cv/{got['job_id']}", headers=t).content == b"%PDF-1.4 test"
    body = {"job_id": got["job_id"], "text": "Your application was sent to Acme"}
    assert client.post("/api/assist/done", json=body, headers={**EXT, **t}).json()["confirmed"]
    db = client.app.state.db  # type: ignore[attr-defined]
    with db() as s:
        assert s.get_one(Job, got["job_id"]).state == JobState.applied
        assert s.query(ActionItem).one().status == ActionStatus.resolved
        assert s.query(JobEvent).filter_by(code="applied_by_hand").count() == 2
    assert client.get("/api/assist/hosts", headers=t).json() == {"hosts": []}


def waiting(c: TestClient, url: str, title: str, company: str) -> int:
    db = c.app.state.db  # type: ignore[attr-defined]
    with db.begin() as s:
        job = Job(source="board", url=url, title=title, company=company, location="", description="",
                  dedupe_hash=url + title, state=JobState.needs_user, data={"apply_url": url})  # fmt: skip
        s.add(job)
        s.flush()
        s.add(ActionItem(job_id=job.id, kind=ActionKind.apply_in_browser, code="x"))
        return job.id


def found(c: TestClient, **page: str) -> int | None:
    r = c.post("/api/assist/match", json=page, headers={**EXT, **token(c)})
    return r.json()["job_id"] if r.status_code == 200 else None


GD = "https://glassdoor.com/job-listing/j?jl="


def test_jobs_sharing_a_path_are_told_apart_by_the_sites_job_id(client: TestClient) -> None:
    a, b = waiting(client, GD + "1010", "Dev", "A"), waiting(client, GD + "2020", "QA", "B")
    assert found(client, url="https://www.glassdoor.com/job-listing/x-JV_KO0,3.htm?jl=2020") == b
    assert found(client, url="https://www.glassdoor.co.uk/Job/jobs.htm?jobListingId=1010") == a
    assert found(client, url=GD + "3030") is None  # another job on that site: never the newest


def test_linkedin_job_id_in_any_of_its_addresses(client: TestClient) -> None:
    a = waiting(client, "https://linkedin.com/jobs/view/4487773655", "Dev", "A")
    for url in (
        "https://www.linkedin.com/jobs/view/4487773655/?trk=x",
        "https://www.linkedin.com/jobs/view/dev-at-a-4487773655",
        "https://eg.linkedin.com/jobs/view/4487773655/apply/",
        "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4487773655",
    ):
        assert found(client, url=url) == a, url
    assert found(client, url="https://www.linkedin.com/jobs/view/9999999999") is None
    assert found(client, url="https://www.linkedin.com/feed/") is None


def test_a_step_under_the_jobs_address_is_that_job(client: TestClient) -> None:
    a = waiting(client, "https://builtin.com/job/dev/12086470", "Dev", "A")
    assert found(client, url="https://builtin.com/job/dev/12086470/apply") == a
    assert found(client, url="https://builtin.com/job/dev/120") is None


def test_title_and_company_on_the_page_identify_it(client: TestClient) -> None:
    a = waiting(client, "https://board.test/1", "Senior Data Engineer", "Globex LLC")
    url = "https://careers.globex.test/apply"
    assert found(client, url=url, title="Data Engineer", text="Join Globex today") == a
    assert found(client, url=url, title="Data Engineer", text="Join Initech") is None
    assert found(client, url=url, title="Careers", text="Globex data engineer") is None


def test_two_jobs_named_on_a_page_is_no_answer(client: TestClient) -> None:
    waiting(client, "https://board.test/1", "Dev", "Globex")
    waiting(client, "https://board.test/2", "Dev", "Globex")
    assert found(client, url="https://careers.test/a", title="Dev", text="Globex") is None
