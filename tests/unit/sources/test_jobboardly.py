import asyncio
from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.ats.jobboardly import Jobboardly
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Task
from linkit_all.sources.http import Http
from linkit_all.sources.runner import company_tasks


def test_boards_come_from_the_company_list() -> None:
    entries = [
        "https://hire-mamas.jobboardly.com/jobs",
        "jobboardly:Remote-Dev",
        "https://www.jobboardly.com",
        "https://example.com/careers",
        "greenhouse:stripe",
    ]
    assert [detect(e) for e in entries] == [
        ("jobboardly", "hire-mamas"),
        ("jobboardly", "Remote-Dev"),
        None,
        None,
        ("greenhouse", "stripe"),
    ]
    cfg = SearchConfig.model_validate({"sources": {"companies": entries}})

    async def resolve() -> tuple[list[Task], list[str]]:
        transport = httpx.MockTransport(lambda req: httpx.Response(404))
        async with httpx.AsyncClient(transport=transport) as client:
            return await company_tasks(cfg, Http(client, default_rate=1000, attempts=1), registry())

    tasks, unsupported = asyncio.run(resolve())
    assert [t.key for t in tasks if t.source == "jobboardly"] == [
        "jobboardly:hire-mamas",
        "jobboardly:Remote-Dev",
    ]
    assert not [u for u in unsupported if "jobboardly" in u]
    assert Jobboardly.cdx_hosts == ("*.jobboardly.com",)


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    data = load_fixture("jobboardly/jobs.json")
    pages = search_pages(
        Jobboardly(), lambda req: httpx.Response(200, json=data), board="hire-mamas", calls=calls
    )
    assert calls == ["https://hire-mamas.jobboardly.com/jobs.json"]
    stubs = pages[0]
    assert len(stubs) == 4
    k8s, svc, gig, mamas = stubs
    assert k8s.title == "Kubernetes Platform Engineer" and k8s.company == "Booz Allen Hamilton"
    assert k8s.location == "Fort Bragg, North Carolina, United States" and k8s.remote == "onsite"
    assert k8s.url == "https://kubernetesjobs.com/jobs/kubernetes-platform-engineer-1da9413c"
    assert k8s.extra["id"] == "kubernetes-platform-engineer-1da9413c"
    assert k8s.ats == "workday" and "myworkdayjobs.com" in (k8s.apply_url or "")
    assert (k8s.salary_min, k8s.salary_max, k8s.salary_currency) == (69400, 158000, "USD")
    assert k8s.salary_interval == "year"
    assert "cloud environments" in k8s.description and "<" not in k8s.description
    assert k8s.posted_at is not None and k8s.posted_at.date().isoformat() == "2026-10-16"
    assert svc.remote == "remote" and svc.location == "US"
    assert svc.ats == "jazzhr" and "applytojob.com" in (svc.apply_url or "")
    assert gig.ats == "jobboardly"  # an apply page no ATS plugin knows
    assert gig.salary_interval == "hour" and gig.salary_min == 80
    assert mamas.apply_url == mamas.url  # the apply link was an e-mail address


def test_empty_board_and_limit(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert search_pages(Jobboardly(), lambda req: httpx.Response(200, json=[]), board="x") == []
    data = load_fixture("jobboardly/jobs.json")
    pages = search_pages(
        Jobboardly(), lambda req: httpx.Response(200, json=data), board="x", limit=2
    )
    assert [len(p) for p in pages] == [2]
    assert (
        search_pages(
            Jobboardly(), lambda req: httpx.Response(200, json=data), board="x", start_page=1
        )
        == []
    )


def test_salary_edge_cases() -> None:
    assert Jobboardly.salary(None) == {}
    assert (
        Jobboardly.salary({"schedule": "weekly", "minimum": {"cents": 100, "currency_iso": "USD"}})
        == {}
    )
    mixed = {
        "schedule": "yearly",
        "minimum": {"cents": 100000, "currency_iso": "USD"},
        "maximum": {"cents": 200000, "currency_iso": "EUR"},
    }
    assert Jobboardly.salary(mixed) == {}
