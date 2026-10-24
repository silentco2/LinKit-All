import httpx
import pytest

from linkit_all.sources.ats.avature import Avature, work_mode
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.careers import Unsupported

HOST = "jobs.example.avature.net"
JOB1 = f"https://{HOST}/en_US/careers/JobDetail/Senior-Product-Manager/214840"
JOB2 = f"https://{HOST}/en_US/careers/JobDetail/Quality-Designer/208332/"


def router(load_fixture, extra: dict[str, httpx.Response] | None = None):
    pages = {
        "/careers/sitemap_index.xml": httpx.Response(
            200, text=load_fixture("avature/sitemap_index.xml")
        ),
        "/en_US/careers/sitemap.xml": httpx.Response(
            200, text=load_fixture("avature/sitemap_en.xml")
        ),
        "/en_US/careers/JobDetail/Senior-Product-Manager/214840": httpx.Response(
            200, text=load_fixture("avature/job.html")
        ),
        "/en_US/careers/JobDetail/Quality-Designer/208332/": httpx.Response(
            200, text=load_fixture("avature/empty_job.html")
        ),
        **(extra or {}),
    }

    def handler(req: httpx.Request) -> httpx.Response:
        return pages.get(req.url.path, httpx.Response(404))

    return handler


def test_search_reads_the_en_us_sitemap_and_pages(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(Avature(), router(load_fixture), board=HOST, calls=calls)
    (stub,) = pages[0]  # the AgentCreate utility page is not a posting; the empty page is skipped
    assert stub.title == "Senior Product Manager"
    assert stub.company == "Example Games"
    assert stub.url == JOB1
    assert stub.location == "Austin, Texas, United States of America"
    assert stub.remote == "hybrid"
    assert "Build the games that connect the world" in stub.description
    assert "alert" not in stub.description
    assert stub.posted_at is not None and stub.posted_at.isoformat() == "2026-06-06T00:00:00"
    assert stub.extra == {"board": HOST, "id": "214840"}
    assert not any("es_ES" in c for c in calls)


def test_resume_past_the_end_yields_nothing(search_pages, load_fixture):
    assert search_pages(Avature(), router(load_fixture), board=HOST, start_page=1) == []


def test_other_portal_from_robots_txt(search_pages, load_fixture):
    index = f"https://{HOST}/global/sitemap_index.xml"
    sub = f"https://{HOST}/global/sitemap.xml"
    extra = {
        "/careers/sitemap_index.xml": httpx.Response(404),
        "/robots.txt": httpx.Response(
            200,
            text=f"Sitemap: https://other.example.com/x.xml\nSitemap: {index}\n",
        ),
        "/global/sitemap_index.xml": httpx.Response(
            200, text=f"<sitemapindex><sitemap><loc>{sub}</loc></sitemap></sitemapindex>"
        ),
        "/global/sitemap.xml": httpx.Response(
            200, text=f"<urlset><url><loc>{JOB1}</loc></url></urlset>"
        ),
    }
    pages = search_pages(Avature(), router(load_fixture, extra), board=HOST)
    assert [s.title for s in pages[0]] == ["Senior Product Manager"]


def test_no_postings_is_unsupported(search_pages):
    with pytest.raises(Unsupported):
        search_pages(Avature(), lambda req: httpx.Response(404), board=HOST)


def test_work_mode_and_patterns():
    assert work_mode("Fully Remote") == "remote"
    assert work_mode("On-site") == "onsite"
    assert work_mode("Flexible") is None
    assert detect("https://ea.avature.net/careers", [Avature()]) == ("avature", "ea.avature.net")
    assert detect("avature:jobs.ea.com", [Avature()]) == ("avature", "jobs.ea.com")
