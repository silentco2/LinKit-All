import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.greenhouse import Greenhouse
from linkit_all.sources.http import Http
from linkit_all.sources.lever import Lever
from linkit_all.sources.recruitee import Recruitee
from linkit_all.sources.runner import discover, enrich
from linkit_all.sources.smartrecruiters import SmartRecruiters
from linkit_all.sources.store import Deduper
from linkit_all.sources.text import normalize_url
from linkit_all.sources.workable import Workable
from linkit_all.sources.workday import Workday, parse_posted

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


def test_smartrecruiters_stub_and_details() -> None:
    posting = load("smartrecruiters/bosch_postings.json")["content"][0]  # type: ignore[index]
    stub = SmartRecruiters.stub(posting, "BoschGroup")
    assert stub.ats == "smartrecruiters" and stub.company == "Bosch Group"
    assert stub.url == "https://jobs.smartrecruiters.com/BoschGroup/744000155868389"
    assert stub.extra["board"] == "BoschGroup" and stub.extra["id"] == "744000155868389"
    assert stub.posted_at is not None and stub.posted_at.tzinfo is None
    assert stub.description == ""  # the list carries no description

    detail = load("smartrecruiters/bosch_posting_detail.json")
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json=detail)

    async def go() -> JobStub:
        # enrich passes a bare stub rebuilt from the DB, so ids come from the URL alone
        bare = JobStub(source="smartrecruiters", url=stub.url, title="t", company="c")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await SmartRecruiters().fetch_details(Http(client), bare)

    full = asyncio.run(go())
    assert seen == ["/v1/companies/BoschGroup/postings/744000155868389"]
    assert "<" not in full.description and "&#" not in full.description
    assert "Gestão de projetos" in full.description and "Qualificações" in full.description
    assert full.apply_url and full.apply_url.startswith("https://jobs.smartrecruiters.com/")


def test_smartrecruiters_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    data = load("smartrecruiters/bosch_postings.json")
    rows = data["content"]  # type: ignore[index]
    monkeypatch.setattr("linkit_all.sources.smartrecruiters.PAGE", 2)
    seen: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        q = req.url.params
        seen.append((q["limit"], q["offset"]))
        off = int(q["offset"])
        return httpx.Response(200, json={"totalFound": len(rows), "content": rows[off : off + 2]})

    async def go(start: int) -> list[list[JobStub]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = Task("smartrecruiters", "k", board="BoschGroup")
            src = SmartRecruiters()
            return [p async for p in src.search(Http(client), task, start)]

    pages = asyncio.run(go(0))
    assert [len(p) for p in pages] == [2, 1]
    assert seen == [("2", "0"), ("2", "2")]
    seen.clear()
    assert [len(p) for p in asyncio.run(go(1))] == [1]  # resume from the second page
    assert seen == [("2", "2")]


def test_recruitee_stub() -> None:
    offers = load("recruitee/bunq_offers.json")["offers"]  # type: ignore[index]
    stub = Recruitee.stub(offers[0], "bunq")
    assert stub.ats == "recruitee" and stub.company == "bunq" and stub.remote == "hybrid"
    assert stub.url == "https://careers.bunq.com/o/head-of-product-6"
    assert stub.apply_url == "https://careers.bunq.com/o/head-of-product-6/c/new"
    assert stub.extra["board"] == "bunq" and stub.extra["id"] == 2783543
    assert stub.location.startswith("Amsterdam")
    assert "<" not in stub.description and len(stub.description) > 200
    assert stub.posted_at is not None and stub.posted_at.tzinfo is None


def test_recruitee_search_reads_offers() -> None:
    data = load("recruitee/bunq_offers.json")

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "bunq.recruitee.com" and req.url.path == "/api/offers/"
        return httpx.Response(200, json=data)

    async def go() -> list[list[JobStub]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = Task("recruitee", "k", board="bunq")
            return [p async for p in Recruitee().search(Http(client), task, 0)]

    assert [len(p) for p in asyncio.run(go())] == [2]


def test_workable_widget_stub_and_details() -> None:
    widget = load("workable/careers_widget.json")
    job = widget["jobs"][0]  # type: ignore[index]
    stub = Workable.stub(job, "careers", widget["name"])  # type: ignore[index]
    assert stub.ats == "workable" and stub.company == "Workable"
    assert stub.url == "https://apply.workable.com/careers/j/A3269A621A/"
    assert stub.apply_url == "https://apply.workable.com/careers/j/A3269A621A/apply/"
    assert stub.location == "Athens, Attica, Greece"
    assert stub.extra["board"] == "careers" and stub.extra["id"] == "A3269A621A"
    assert stub.posted_at is not None and stub.posted_at.tzinfo is None
    assert "<" not in stub.description and len(stub.description) > 200

    detail = load("workable/careers_job_detail.json")
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json=detail)

    async def go() -> JobStub:
        bare = JobStub(source="workable", url=stub.url, title="t", company="c")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await Workable().fetch_details(Http(client), bare)

    full = asyncio.run(go())
    assert seen == ["/api/v2/accounts/careers/jobs/A3269A621A"]
    assert "<" not in full.description and len(full.description) > 200


def test_workable_search_is_one_page() -> None:
    widget = load("workable/careers_widget.json")

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v1/widget/accounts/careers"
        return httpx.Response(200, json=widget)

    async def go(start: int) -> list[list[JobStub]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = Task("workable", "k", board="careers")
            return [p async for p in Workable().search(Http(client), task, start)]

    pages = asyncio.run(go(0))
    assert [len(p) for p in pages] == [2] and pages[0][0].company == "Workable"
    assert asyncio.run(go(1)) == []  # a resumed task has nothing left


BOARD = "nvidia/wd5/NVIDIAExternalCareerSite"


def test_workday_stub() -> None:
    posting = load("workday/nvidia_jobs.json")["jobPostings"][1]  # type: ignore[index]
    stub = Workday.stub(posting, BOARD, "Nvidia")
    assert stub.ats == "workday" and stub.company == "Nvidia"
    assert stub.url == (
        "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"
        "/job/US-CA-Santa-Clara/Senior-Algorithm-Engineer--Map-Perception-Fusion_JR2027508"
    )
    assert stub.extra["board"] == BOARD and stub.extra["req_id"] == "JR2027508"
    assert stub.location == "3 Locations" and stub.description == ""
    assert stub.posted_at is not None and stub.posted_at.tzinfo is None


def test_workday_posted_on_is_relative() -> None:
    now = datetime(2026, 10, 16, 15, 30, tzinfo=UTC)
    assert parse_posted("Posted Today", now) == datetime(2026, 10, 16)
    assert parse_posted("Posted Yesterday", now) == datetime(2026, 10, 15)
    assert parse_posted("Posted 3 Days Ago", now) == datetime(2026, 10, 13)
    assert parse_posted("Posted 30+ Days Ago", now) == datetime(2026, 9, 16)
    assert parse_posted("Open until filled", now) is None and parse_posted(None, now) is None


def test_workday_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    data = load("workday/nvidia_jobs.json")
    rows = data["jobPostings"]  # type: ignore[index]
    monkeypatch.setattr("linkit_all.sources.workday.PAGE", 2)
    seen: list[tuple[str, int, int]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append((req.url.path, body["limit"], body["offset"]))
        off = body["offset"]
        # like the real API, only the first page reports a total
        return httpx.Response(
            200, json={"total": len(rows) if off == 0 else 0, "jobPostings": rows[off : off + 2]}
        )

    async def go(start: int) -> list[list[JobStub]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = Task("workday", "k", board=BOARD)
            return [p async for p in Workday().search(Http(client), task, start)]

    path = "/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"
    assert [len(p) for p in asyncio.run(go(0))] == [2, 1]
    assert seen == [(path, 2, 0), (path, 2, 2)]
    seen.clear()
    assert [len(p) for p in asyncio.run(go(1))] == [1]  # resume: no total, stops on a short page
    assert seen == [(path, 2, 2)]


def test_workday_details_from_url_only() -> None:
    detail = load("workday/nvidia_job_detail.json")
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(f"{req.url.host}{req.url.path}")
        return httpx.Response(200, json=detail)

    async def go() -> JobStub:
        url = (
            "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"
            "/job/US-CA-Santa-Clara/Senior-Engineer---Enterprise-Data-Governance_JR2024554"
        )
        bare = JobStub(source="workday", url=url, title="t", company="c")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await Workday().fetch_details(Http(client), bare)

    full = asyncio.run(go())
    assert seen == [
        "nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite"
        "/job/US-CA-Santa-Clara/Senior-Engineer---Enterprise-Data-Governance_JR2024554"
    ]
    assert "<" not in full.description and len(full.description) > 500
    assert full.apply_url and full.apply_url.startswith("https://nvidia.wd5.myworkdayjobs.com/")


def test_workday_tenants_are_rate_limited_to_one_per_second() -> None:
    async def go() -> float:
        async with httpx.AsyncClient() as client:
            return Http(client)._limiter("acme.wd3.myworkdayjobs.com").max_rate

    assert asyncio.run(go()) == 1.0


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
        ("https://jobs.smartrecruiters.com/BoschGroup/744000155868329-engenheiro", ("smartrecruiters", "BoschGroup")),
        ("https://careers.smartrecruiters.com/Visa", ("smartrecruiters", "Visa")),
        ("https://jobs.smartrecruiters.com/oneclick-ui/company/Visa/publication/abc", ("smartrecruiters", "Visa")),
        ("https://api.smartrecruiters.com/v1/companies/BoschGroup/postings", ("smartrecruiters", "BoschGroup")),
        ("smartrecruiters:Visa", ("smartrecruiters", "Visa")),
        ("https://bunq.recruitee.com/o/head-of-product", ("recruitee", "bunq")),
        ("https://bunq.recruitee.com", ("recruitee", "bunq")),
        ("recruitee:bunq", ("recruitee", "bunq")),
        ("https://acme.wd5.myworkdayjobs.com/en-US/External", ("workday", "acme/wd5/External")),
        ("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", ("workday", "nvidia/wd5/NVIDIAExternalCareerSite")),
        ("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA/Eng_JR1", ("workday", "nvidia/wd5/NVIDIAExternalCareerSite")),
        ("https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs", ("workday", "nvidia/wd5/NVIDIAExternalCareerSite")),
        ("workday:nvidia/wd5/NVIDIAExternalCareerSite", ("workday", "nvidia/wd5/NVIDIAExternalCareerSite")),
        ("https://apply.workable.com/careers/j/A3269A621A/", ("workable", "careers")),
        ("https://apply.workable.com/api/v1/widget/accounts/careers", ("workable", "careers")),
        ("workable:careers", ("workable", "careers")),
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
                    "https://nowhere.example/careers",  # no ATS found on the page
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
    # no ATS on the page: the generic careers source tried it (404 here -> an error, not a skip)
    assert "careers:https://nowhere.example/careers" in stats.errors  # type: ignore[attr-defined]
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
            "sources": {
                "jobspy": ["indeed", "glassdoor"],
                "jobspy_country": "egypt",
                "regional": ["bayt"],
            },
        }
    )
    indeed, linkedin, bayt = (JobSpySite(s, fake_scrape) for s in ("indeed", "linkedin", "bayt"))
    assert len(indeed.tasks(cfg)) == 4 and len(bayt.tasks(cfg)) == 4  # bayt via regional
    assert linkedin.tasks(cfg) == []
    glassdoor = JobSpySite("glassdoor", fake_scrape)
    assert {t.country for t in glassdoor.tasks(cfg)} == {""}  # Glassdoor gets no country
    assert {t.country for t in indeed.tasks(cfg)} == {"egypt"}

    async def pages(src: JobSpySite) -> list[JobStub]:
        task = src.tasks(cfg)[0] if src.tasks(cfg) else Task(src.name, "k", query="python")
        return [s async for page in src.search(Http(httpx.AsyncClient()), task, 0) for s in page]

    stubs = asyncio.run(pages(indeed))
    assert seen[0]["country_indeed"] == "egypt" and seen[0]["hours_old"] == 14 * 24
    asyncio.run(pages(glassdoor))
    assert "country_indeed" not in seen[-1]  # jobspy's own default applies
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


def test_wuzzuf_sitemap_filter_and_jsonld() -> None:
    from datetime import timedelta

    from linkit_all.core.models import utcnow
    from linkit_all.sources.wuzzuf import Wuzzuf

    recent = (utcnow() - timedelta(days=1)).isoformat() + "+00:00"
    old = (utcnow() - timedelta(days=60)).isoformat() + "+00:00"
    jobs = (FIX / "wuzzuf/sitemap-job-1.xml").read_text("utf-8").format(recent=recent, old=old)
    fetched: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        fetched.append(req.url.path)
        if req.url.path == "/sitemap.xml":
            return httpx.Response(200, text=(FIX / "wuzzuf/sitemap.xml").read_text("utf-8"))
        if req.url.path == "/sitemap-job-1.xml":
            return httpx.Response(200, text=jobs)
        if req.url.path.startswith("/jobs/p/"):
            return httpx.Response(200, text=(FIX / "wuzzuf/job.html").read_text("utf-8"))
        return httpx.Response(404)

    cfg = SearchConfig.model_validate(
        {"search": {"queries": ["python engineer", "nurse"]}, "sources": {"regional": ["wuzzuf"]}}
    )
    (task,) = Wuzzuf().tasks(cfg)

    async def go() -> list[JobStub]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            http = Http(c, per_host_rate={"wuzzuf.net": 1000})
            return [s async for page in Wuzzuf().search(http, task, 0) for s in page]

    (stub,) = asyncio.run(go())
    # Only the recent python+engineer slug is fetched: the developer one is too old,
    # the nutrition one matches no query, and the template sitemap is never read.
    assert [p for p in fetched if p.startswith("/jobs/p/")] == [
        "/jobs/p/rcqxngwvzmck-senior-fullstack-python-engineer-vertex-technologies-cairo-egypt"
    ]
    assert "/sitemap-job-template-1.xml" not in fetched
    assert stub.title == "Senior FullStack (Python) Engineer"
    assert stub.company == "Vertex Technologies" and stub.ats == "wuzzuf"
    assert stub.location == "Cairo, EG"
    assert "Job Requirements" in stub.description and "<" not in stub.description
    assert stub.posted_at is not None


def test_company_variants_normalize_together() -> None:
    from linkit_all.sources.text import norm_company

    assert norm_company("Merck Group") == norm_company("Merck KGaA") == "merck"
    assert norm_company("Nile Bits, LLC") == "nile bits"
    assert norm_company("Group Holdings SE") == "group holdings se"


def _forasna_run(
    queries: list[str],
    start_page: int = 0,
    robots: tuple[int, str] | None = None,
    extra_entries: str = "",
) -> tuple[list[list[JobStub]], list[str]]:
    from datetime import timedelta

    from linkit_all.core.models import utcnow
    from linkit_all.sources.forasna import Forasna

    d = FIX / "forasna"
    recent = (utcnow() - timedelta(days=1)).isoformat() + "+00:00"
    old = (utcnow() - timedelta(days=60)).isoformat() + "+00:00"
    jobs = (d / "sitemap5.xml").read_text("utf-8").format(recent=recent, old=old)
    jobs = jobs.replace("</urlset>", extra_entries.format(recent=recent) + "</urlset>")
    pages = {"444100": "job-purchasing.html", "444095": "job-data-entry.html"}
    fetched: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            status, text = robots or (200, (d / "robots.txt").read_text("utf-8"))
            return httpx.Response(status, text=text)
        fetched.append(path)
        if path == "/sitemap.xml":
            return httpx.Response(200, text=(d / "sitemap.xml").read_text("utf-8"))
        if path == "/sitemap1.xml":
            return httpx.Response(200, text=(d / "sitemap1.xml").read_text("utf-8"))
        if path == "/sitemap5.xml":
            return httpx.Response(200, text=jobs)
        page = pages.get(path.rsplit("-", 1)[-1])
        if path.startswith("/job/p/") and page:
            return httpx.Response(200, content=(d / page).read_bytes())
        return httpx.Response(404)

    cfg = SearchConfig.model_validate(
        {"search": {"queries": queries}, "sources": {"regional": ["forasna"]}}
    )
    (task,) = Forasna().tasks(cfg)

    async def go() -> list[list[JobStub]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            http = Http(c, per_host_rate={"forasna.com": 1000})
            return [p async for p in Forasna().search(http, task, start_page)]

    return asyncio.run(go()), fetched


def test_forasna_sitemap_match_and_jsonld_arabic() -> None:
    # Matches by Arabic and English slug words; the old hr entry and the unmatched ones are
    # skipped; 444098 (ERP) is in the sitemap but already gone (404): skipped, not an error.
    pages, fetched = _forasna_run(["مشتريات", "إدخال بيانات", "erp odoo", "hr specialist"])
    stubs = {s.title: s for page in pages for s in page}
    assert sorted(p.rsplit("-", 1)[-1] for p in fetched if p.startswith("/job/p/")) == [
        "444095", "444098", "444100"
    ]  # fmt: skip
    assert set(fetched) >= {"/sitemap.xml", "/sitemap1.xml", "/sitemap5.xml"}
    assert "/careers/sitemap_index.xml" not in fetched  # their blog, not jobs
    buy = stubs["مسئول مشتريات (مجال الاغذيه)"]
    assert buy.company == "نباتات" and buy.ats == "forasna" and buy.source == "forasna"
    assert buy.location == "مدينة العبور, القاهرة, EG"
    assert buy.posted_at is not None and buy.apply_url == buy.url
    assert buy.url.startswith("https://forasna.com/job/p/") and buy.url.endswith("-444100")
    assert "مسئول مشتريات ميداني" in buy.description and "<" not in buy.description
    assert (buy.salary_min, buy.salary_max, buy.salary_currency) == (15000, 20000, "EGP")
    entry = stubs["موظف إدخال بيانات"]
    assert entry.remote == "remote" and entry.location == "الرياض, SA"
    assert len(stubs) == 2


def test_forasna_no_query_no_tasks() -> None:
    from linkit_all.sources.forasna import Forasna

    off = SearchConfig.model_validate({"search": {"queries": ["x"]}})
    assert Forasna().tasks(off) == []
    on = SearchConfig.model_validate({"sources": {"regional": ["forasna"]}})
    assert Forasna().tasks(on) == []
    assert "forasna" in registry()


def test_forasna_robots_honored() -> None:
    # The wildcard Disallow /*uat* matches the "evaluation" slug, so it is never fetched.
    extra = (
        "<url><loc>https://forasna.com/job/p/evaluation-manager-444999</loc>"
        "<lastmod>{recent}</lastmod></url>"
    )
    _, fetched = _forasna_run(["evaluation manager", "مشتريات"], extra_entries=extra)
    assert "/job/p/evaluation-manager-444999" not in fetched
    assert any(p.endswith("-444100") for p in fetched)
    # robots.txt that closes the job pages: sitemaps are read, pages are not.
    pages, fetched = _forasna_run(["مشتريات"], robots=(200, "User-agent: *\nDisallow: /job/p/\n"))
    assert pages == [] and not [p for p in fetched if p.startswith("/job/p/")]
    # robots.txt that closes everything, or fails with a 5xx: nothing is fetched at all.
    for robots in ((200, "User-agent: *\nDisallow: /\n"), (503, "")):
        pages, fetched = _forasna_run(["مشتريات"], robots=robots)
        assert pages == [] and fetched == []


def test_forasna_resumes_from_checkpoint_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("linkit_all.sources.forasna.PAGE", 1)
    full, _ = _forasna_run(["مشتريات", "إدخال بيانات"])
    assert [len(p) for p in full] == [1, 1]
    rest, fetched = _forasna_run(["مشتريات", "إدخال بيانات"], start_page=1)
    assert [[s.url for s in p] for p in rest] == [[s.url for s in full[1]]]
    assert len([p for p in fetched if p.startswith("/job/p/")]) == 1  # page 0 not fetched again


class FakeSource(Source):
    """Yields one job per task after a delay; records how many of its tasks ran at once."""

    running = 0  # across all fake sources
    overlap = 0  # most tasks of any sources running at once

    def __init__(self, name: str, parallel: int = 1, priority: int = 0, delay: float = 0.05):
        self.name, self.parallel, self.priority, self.delay = name, parallel, priority, delay
        self.active = self.peak = 0

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, f"{self.name}:{i}", query=str(i)) for i in range(3)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        cls = type(self)
        self.active += 1
        cls.running += 1
        self.peak, cls.overlap = max(self.peak, self.active), max(cls.overlap, cls.running)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.active -= 1
            cls.running -= 1
        yield [
            JobStub(source=self.name, url=f"https://{self.name}.io/{task.query}",
                    title=f"Job {task.query}", company=f"Co {task.query}",
                    location="Cairo", ats=self.name, description=self.name * (3 - self.priority))
        ]  # fmt: skip


def run_discover(tmp_path: Path, sources: list[FakeSource]) -> tuple[Any, Any, float]:
    db = init_db(tmp_path / "t.db")
    FakeSource.running = FakeSource.overlap = 0

    async def go() -> Any:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(404))
        ) as c:
            return await discover(
                db,
                SearchConfig(),
                current_run(db),
                Http(c, attempts=1),
                {s.name: s for s in sources},
            )

    start = time.monotonic()
    stats = asyncio.run(go())
    return db, stats, time.monotonic() - start


def test_discover_runs_sources_side_by_side(tmp_path: Path) -> None:
    a, b = FakeSource("a", delay=0.2), FakeSource("b", delay=0.2)
    _, stats, took = run_discover(tmp_path, [a, b])
    assert stats.tasks_done == 6
    assert (a.peak, b.peak) == (1, 1)  # parallel=1: one task at a time per source
    assert FakeSource.overlap == 2  # but the two sources overlapped
    assert took < 1.0  # sum would be 1.2 s; max(source) is 0.6 s


def test_discover_parallel_source_runs_tasks_together(tmp_path: Path) -> None:
    api = FakeSource("api", parallel=3, delay=0.1)
    _, stats, _ = run_discover(tmp_path, [api, FakeSource("slow", delay=0.1)])
    assert stats.tasks_done == 6
    assert api.peak == 3


def test_discover_overall_cap_bounds_running_tasks(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    srcs = [FakeSource(n, parallel=3, delay=0.02) for n in "abc"]
    FakeSource.running = FakeSource.overlap = 0

    async def go() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(404))
        ) as c:
            await discover(db, SearchConfig(), current_run(db), Http(c, attempts=1),
                           {s.name: s for s in srcs}, max_running=4)  # fmt: skip

    asyncio.run(go())
    assert FakeSource.overlap == 4


def test_discover_higher_priority_duplicate_upgrades_stored_job(tmp_path: Path) -> None:
    # Same titles/companies/locations from two sources; the better one is slower, so the
    # lower-priority copy is stored first.
    best = FakeSource("best", priority=0, delay=0.3)
    other = FakeSource("other", priority=1, delay=0.0)
    db, stats, _ = run_discover(tmp_path, [best, other])
    assert (stats.new, stats.duplicates) == (3, 3)
    with db() as s:
        jobs = list(s.scalars(select(Job)))
        assert len(jobs) == 3
        assert {(j.source, j.ats, j.url.split("/")[2]) for j in jobs} == {
            ("best", "best", "best.io")
        }
        assert all(j.description == "bestbestbest" for j in jobs)  # the longer description
    # keys stay consistent: the lower-priority URL is still a duplicate on the next run
    with db() as s:
        d = Deduper(s)
        assert d.add(stub("Job 0", company="Co 0", url="https://other.io/0")) is None
        assert d.add(stub("Job 0", company="Co 0", url="https://best.io/0")) is None


def test_lower_priority_duplicate_does_not_replace(tmp_path: Path) -> None:
    best = FakeSource("best", priority=0, delay=0.0)
    other = FakeSource("other", priority=1, delay=0.2)
    db, stats, _ = run_discover(tmp_path, [best, other])
    assert (stats.new, stats.duplicates) == (3, 3)
    with db() as s:
        assert {j.source for j in s.scalars(select(Job))} == {"best"}
