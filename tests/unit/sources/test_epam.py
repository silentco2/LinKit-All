import gzip
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import epam
from linkit_all.sources.companies.epam import Epam

CLOUD = "cloud-engagement-leader-aws-life-sciences-healthcare-blt4utjubjixgbsyjbk_en"


def make_handler(
    load_fixture: Callable[[str], Any], gzipped: bool = False
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/sitemap.xml.gz":
            xml = load_fixture("epam/sitemap.xml").encode()
            return httpx.Response(200, content=gzip.compress(xml) if gzipped else xml)
        if path.endswith(CLOUD):
            return httpx.Response(200, text=load_fixture("epam/vacancy.html"))
        return httpx.Response(404)  # the other vacancy has been taken down

    return handler


@pytest.mark.parametrize("gzipped", [False, True])
def test_sitemap_then_vacancy(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    gzipped: bool,
) -> None:
    pages = search_pages(Epam(), make_handler(load_fixture, gzipped))
    assert len(pages) == 1 and len(pages[0]) == 1  # only English vacancy pages, 404 dropped
    job = pages[0][0]
    assert job.title == "Cloud Engagement Leader – AWS Life Sciences & Healthcare"  # noqa: RUF001
    assert job.company == "EPAM Systems" and job.location == "London, UK"
    assert job.url == f"https://careers.epam.com/en/vacancy/{CLOUD}"
    assert job.remote == "remote"  # jobLocationType TELECOMMUTE
    assert "Responsibilities" in job.description and "Benefits" in job.description
    assert job.posted_at is not None and job.posted_at.isoformat().startswith("2026-09-29")
    assert job.extra == {"id": "blt4utjubjixgbsyjbk"} and job.source == "epam"


def test_chunks_resume_and_task(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(epam, "CHUNK", 1)
    assert len(search_pages(Epam(), make_handler(load_fixture))) == 2
    # sorted by URL: the live cloud page comes first, the taken-down "senior" page second
    assert search_pages(Epam(), make_handler(load_fixture), start_page=1) == [[]]
    assert Epam().tasks(SearchConfig())[0].key == "epam:careers"


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="epam", url=f"https://careers.epam.com/en/vacancy/{CLOUD}", title="t", company="c"
    )
    assert "Benefits" in fetch_details(Epam(), make_handler(load_fixture), stub).description


def test_not_enabled_unless_listed() -> None:
    cfg = SearchConfig()
    assert not Epam().is_enabled(cfg)
    cfg.sources.enabled = ["epam"]
    assert Epam().is_enabled(cfg)
