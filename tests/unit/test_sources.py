import asyncio
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobState, SourceCheckpoint
from linkit_all.core.runs import current_run
from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.ashby import Ashby
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Task
from linkit_all.sources.greenhouse import Greenhouse
from linkit_all.sources.http import Http
from linkit_all.sources.lever import Lever
from linkit_all.sources.runner import discover, enrich
from linkit_all.sources.store import Deduper
from linkit_all.sources.text import normalize_url

FIX = Path(__file__).parent.parent / "fixtures"


def load(name: str) -> object:
    return json.loads((FIX / name).read_text("utf-8"))


def test_greenhouse_stub() -> None:
    data = load("greenhouse/stripe_jobs.json")
    stub = Greenhouse.stub(data["jobs"][0], "stripe")  # type: ignore[index]
    assert stub.company == "Stripe" and stub.ats == "greenhouse"
    assert stub.url.startswith("https://stripe.com/jobs/search?gh_jid=")
    assert "<" not in stub.description and "&lt;" not in stub.description
    assert stub.posted_at is not None and stub.posted_at.tzinfo is None


def test_lever_stub() -> None:
    stub = Lever.stub(load("lever/palantir_postings.json")[0], "palantir")  # type: ignore[index]
    assert stub.company == "Palantir" and stub.remote == "hybrid"
    assert stub.apply_url and stub.apply_url.endswith("/apply")
    assert len(stub.description) > 200


def test_ashby_stub_reads_salary() -> None:
    data = load("ashby/openai_job_board.json")
    stub = Ashby.stub(data["jobs"][0], "openai")  # type: ignore[index]
    assert (stub.salary_min, stub.salary_max, stub.salary_currency) == (257000, 335000, "USD")
    assert stub.salary_interval == "year"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://boards.greenhouse.io/stripe", ("greenhouse", "stripe")),
        ("https://job-boards.greenhouse.io/airbnb/jobs/123", ("greenhouse", "airbnb")),
        ('<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme">', ("greenhouse", "acme")),
        ("https://jobs.lever.co/palantir/abc", ("lever", "palantir")),
        ("https://jobs.eu.lever.co/mistral", ("lever", "mistral")),
        ("https://jobs.ashbyhq.com/openai", ("ashby", "openai")),
        ("lever:netflix", ("lever", "netflix")),
        ("https://acme.wd5.myworkdayjobs.com/en-US/External", ("workday", "acme.wd5.myworkdayjobs.com/en-US/External")),
        ("https://example.com/careers", None),
    ],
)  # fmt: skip
def test_ats_detector(text: str, expected: tuple[str, str] | None) -> None:
    assert detect(text) == expected


def test_normalize_url() -> None:
    assert (
        normalize_url("HTTPS://www.Stripe.com/jobs/search/?utm_source=li&gh_jid=81&gh_src=x#top")
        == "https://stripe.com/jobs/search?gh_jid=81"
    )


def stub(title: str, company: str = "Acme", url: str = "", loc: str = "Cairo") -> JobStub:
    return JobStub(source="t", url=url or f"https://x.io/{title}", title=title, company=company,
                   location=loc)  # fmt: skip


def test_deduper(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    with db() as s:
        d = Deduper(s)
    assert d.add(stub("Backend Engineer", url="https://x.io/1?utm_source=a"))
    assert d.add(stub("Other", url="https://www.x.io/1/")) is None  # same URL
    assert d.add(stub("Backend Engineer", company="Acme Inc.", url="https://y.io/2")) is None
    assert d.add(stub("Engineer, Backend", url="https://z.io/3")) is None  # fuzzy, same company
    assert d.add(stub("Backend Engineer", company="Globex", url="https://z.io/4"))
    assert d.add(stub("Frontend Engineer", url="https://z.io/5"))


def mock_transport(calls: list[str]) -> httpx.MockTransport:
    gh, lv, ab = (
        load("greenhouse/stripe_jobs.json"),
        load("lever/palantir_postings.json"),
        load("ashby/openai_job_board.json"),
    )

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        host, path = req.url.host, req.url.path
        if host == "boards-api.greenhouse.io" and path.endswith("/stripe/jobs"):
            return httpx.Response(200, json=gh)
        if host == "api.lever.co" and path.endswith("/palantir"):
            return httpx.Response(200, json=lv)
        if host == "api.ashbyhq.com" and path.endswith("/openai"):
            return httpx.Response(200, json=ab)
        if host == "acme.example":
            html = '<script src="https://boards.greenhouse.io/embed/job_board/js?for=stripe">'
            return httpx.Response(200, text=html)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_discover_resume_and_enrich(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    cfg = SearchConfig.model_validate(
        {
            "sources": {
                "companies": [
                    "https://boards.greenhouse.io/stripe",
                    "https://acme.example/careers",  # embeds the same Stripe board
                    "lever:palantir",
                    "https://jobs.ashbyhq.com/openai",
                    "lever:gone",  # 404 on both Lever instances
                    "https://acme.wd1.myworkdayjobs.com/External",
                ]
            }
        }
    )
    calls: list[str] = []

    async def go(run_id: int) -> object:
        async with httpx.AsyncClient(transport=mock_transport(calls)) as client:
            return await discover(db, cfg, run_id, Http(client, attempts=1), registry())

    run_id = current_run(db)
    stats = asyncio.run(go(run_id))
    # Stripe posts two identical Dublin reqs; they collapse into one job.
    assert (stats.new, stats.duplicates) == (8, 1)  # type: ignore[attr-defined]
    assert "lever:gone" in stats.errors  # type: ignore[attr-defined]
    assert any("workday not supported" in u for u in stats.unsupported)  # type: ignore[attr-defined]
    with db() as s:
        assert s.query(Job).count() == 8
        assert all(c.done for c in s.scalars(select(SourceCheckpoint)))

    calls.clear()
    assert asyncio.run(go(run_id)).new == 0  # type: ignore[attr-defined]
    assert not any("boards-api" in c for c in calls)  # finished tasks are not refetched

    again = asyncio.run(go(current_run(db, new=True)))
    assert (again.new, again.duplicates) == (0, 9)  # type: ignore[attr-defined]

    async def run_enrich() -> int:
        async with httpx.AsyncClient(transport=mock_transport([])) as client:
            return await enrich(db, Http(client), registry())

    assert asyncio.run(run_enrich()) == 8
    with db() as s:
        assert {j.state for j in s.query(Job)} == {JobState.enriched}


def test_jobspy_tasks_mapping_and_linkedin_details(tmp_path: Path) -> None:
    from linkit_all.sources.jobspy_sites import JobSpySite

    rows = load("jobspy/python_cairo.json")
    seen: list[dict[str, object]] = []

    def fake_scrape(**kwargs: object) -> list[dict[str, object]]:
        seen.append(kwargs)
        return [r for r in rows if r["site"] == kwargs["site_name"][0]]  # type: ignore[index, union-attr]

    cfg = SearchConfig.model_validate(
        {
            "search": {"queries": ["python", "data"], "locations": ["Cairo", "Remote"]},
            "sources": {"jobspy": ["indeed"], "jobspy_country": "egypt", "regional": ["bayt"]},
        }
    )
    indeed, linkedin, bayt = (JobSpySite(s, fake_scrape) for s in ("indeed", "linkedin", "bayt"))
    assert len(indeed.tasks(cfg)) == 4 and len(bayt.tasks(cfg)) == 4  # bayt via regional
    assert linkedin.tasks(cfg) == []

    async def pages(src: JobSpySite) -> list[JobStub]:
        task = src.tasks(cfg)[0] if src.tasks(cfg) else Task(src.name, "k", query="python")
        return [s async for page in src.search(Http(httpx.AsyncClient()), task, 0) for s in page]

    stubs = asyncio.run(pages(indeed))
    assert seen[0]["country_indeed"] == "egypt" and seen[0]["hours_old"] == 14 * 24
    assert stubs and all(s.source == "indeed" for s in stubs)
    workable = [s for s in stubs if s.apply_url and "workable" in s.apply_url]
    assert workable and workable[0].ats == "workable"  # company ATS from job_url_direct

    li = asyncio.run(pages(linkedin))
    assert li and all(s.ats == "linkedin" for s in li)
    empty = next(s for s in li if not s.description)

    def handler(req: httpx.Request) -> httpx.Response:
        html = '<div class="show-more-less-html__markup"><p>Build APIs</p><ul><li>Python</li></ul></div>'
        return httpx.Response(200, text=html)

    async def details() -> JobStub:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await linkedin.fetch_details(Http(c), empty)

    assert asyncio.run(details()).description == "Build APIs\nPython"


def test_jobspy_logged_error_with_no_rows_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import logging

    import jobspy
    import pandas as pd

    from linkit_all.sources.jobspy_sites import _scrape_jobs

    def fake(**kwargs: object) -> pd.DataFrame:
        logging.getLogger("JobSpy:LinkedIn").error("LinkedIn response status code 429")
        return pd.DataFrame()

    monkeypatch.setattr(jobspy, "scrape_jobs", fake)
    with pytest.raises(RuntimeError, match="429"):  # so the task stays open for a resume
        _scrape_jobs(site_name=["linkedin"])
