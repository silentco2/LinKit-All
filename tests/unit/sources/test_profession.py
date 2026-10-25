from collections.abc import Callable
from typing import Any

import httpx
from boards_util import router, run_search

from linkit_all.sources.boards.profession import Profession, place

HYBRID = "backend-fejleszto-trendency-1111111"
REMOTE = "python-fejleszto-remote-2222222"
ONSITE = "devops-mernok-acme-3333333"
GONE = "regi-allas-9999999"


def _routes(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    return {
        "sitemap-listings-index-hu.xml": load_fixture("profession/index.xml"),
        "sitemap-listings-itdev-hu.xml": load_fixture("profession/itdev.xml"),
        "sitemap-listings-itops-hu.xml": load_fixture("profession/itops.xml"),
        f"/allas/{HYBRID}": load_fixture("profession/hybrid.html"),
        f"/allas/{REMOTE}": load_fixture("profession/remote.html"),
        f"/allas/{ONSITE}": load_fixture("profession/onsite.html"),
        f"/allas/{GONE}": load_fixture("profession/gone.html"),  # taken down: 200, no posting
    }


def test_only_the_it_categories_are_read(load_fixture: Callable[[str], Any]) -> None:
    calls: list[httpx.Request] = []
    pages = run_search(Profession(), router(_routes(load_fixture), calls))
    jobs = {s.extra["id"]: s for p in pages for s in p}
    assert set(jobs) == {"1111111", "2222222", "3333333"}  # the taken-down posting is skipped
    assert not any("education" in str(r.url) or "companies" in str(r.url) for r in calls)
    # the server cuts reused connections short, so each request asks for its own
    assert all(r.headers["Connection"] == "close" for r in calls if r.url.path != "/robots.txt")


def test_hybrid_posting_reads_the_badge_and_sections(load_fixture: Callable[[str], Any]) -> None:
    pages = run_search(Profession(), router(_routes(load_fixture)))
    jobs = {s.extra["id"]: s for p in pages for s in p}
    hybrid = jobs["1111111"]
    assert (hybrid.title, hybrid.company) == ("Backend fejlesztő", "TRENDENCY ONLINE Zrt.")
    assert hybrid.remote == "hybrid" and hybrid.location == "Budapest, Knézits utca"
    assert hybrid.url == f"https://www.profession.hu/allas/{HYBRID}" and hybrid.ats == "profession"
    assert hybrid.posted_at is not None and hybrid.posted_at.day == 2
    # the employer's sections under their headings; the blurb and contact box are not the posting
    assert "Feladatok" in hybrid.description and "Microservice-ek fejlesztése" in hybrid.description
    assert "Szakmai tréningek" in hybrid.description
    assert "180 fős" not in hybrid.description and "allas@trendency.hu" not in hybrid.description
    assert jobs["2222222"].remote == "remote" and jobs["2222222"].location == "Magyarország"
    assert (
        jobs["3333333"].remote == "onsite" and jobs["3333333"].location == "Budapest, Kerepesi út ."
    )


def test_place_splits_badge_and_strips_digits() -> None:
    assert place("Hibrid • 1092 Budapest, Knézits utca") == ("hybrid", "Budapest, Knézits utca")
    assert place("1087 Budapest, Kerepesi út 21.") == ("onsite", "Budapest, Kerepesi út .")
    assert place("Országos lefedettség") == ("onsite", "")  # "nationwide" names no place
    assert place("") == ("onsite", "")


def test_resume_limit_and_a_dropped_category(load_fixture: Callable[[str], Any]) -> None:
    assert run_search(Profession(), router(_routes(load_fixture)), start_page=1) == []
    (limited,) = run_search(Profession(), router(_routes(load_fixture)), limit=2)
    assert len(limited) <= 2
    routes = _routes(load_fixture)
    routes["sitemap-listings-itops-hu.xml"] = (404, "gone")
    pages = run_search(Profession(), router(routes))
    assert {s.extra["id"] for p in pages for s in p} == {"1111111", "2222222"}
