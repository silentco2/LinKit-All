from collections.abc import Callable
from typing import Any

import httpx
import pytest
from boards_util import router, run_details, run_search

from linkit_all.core.search import SearchConfig
from linkit_all.sources.boards.pythonorg import PythonOrg, cards


def _routes(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    return {
        "www.python.org/jobs/?page=2": load_fixture("pythonorg/list_page2.html"),
        "www.python.org/jobs/?page=3": (404, "gone"),  # past the last page
        "python.org/jobs/": load_fixture("pythonorg/list_page1.html"),
        "www.python.org/jobs/8109/": load_fixture("pythonorg/posting_8109.html"),
    }


def test_cards_are_read_from_the_listing(load_fixture: Callable[[str], Any]) -> None:
    first = cards(load_fixture("pythonorg/list_page1.html"))
    assert [c.title for c in first] == [
        "Software Engineer - Full Stack",
        "Junior Machine Learning Engineer",
        "Machine Learning Engineer",
    ]
    assert first[1].company == "HFT Architecture" and first[1].location == "Remote, Worldwide"
    assert first[1].url == "https://www.python.org/jobs/8176/" and first[1].extra == {"id": "8176"}
    assert first[1].remote == "remote" and first[1].ats == "pythonorg"
    assert first[1].posted_at is not None and (
        first[1].posted_at.month,
        first[1].posted_at.day,
    ) == (10, 14)


def test_search_walks_pages_until_a_404(load_fixture: Callable[[str], Any]) -> None:
    calls: list[httpx.Request] = []
    pages = run_search(PythonOrg(), router(_routes(load_fixture), calls))
    assert [len(p) for p in pages] == [3, 3]
    assert pages[1][0].title == "Senior Backend Python Engineer"
    assert any(str(r.url).endswith("/jobs/?page=3") for r in calls)  # the walk probed past the end


def test_resume_starts_at_the_checkpoint_page(load_fixture: Callable[[str], Any]) -> None:
    pages = run_search(PythonOrg(), router(_routes(load_fixture)), start_page=1)
    assert [len(p) for p in pages] == [3]
    assert pages[0][0].extra == {"id": "8109"}


def test_limit_stops_the_walk(load_fixture: Callable[[str], Any]) -> None:
    calls: list[httpx.Request] = []
    pages = run_search(PythonOrg(), router(_routes(load_fixture), calls), limit=2)
    assert [len(p) for p in pages] == [2]
    assert not any("page=2" in str(r.url) for r in calls)


def test_first_page_failure_raises(load_fixture: Callable[[str], Any]) -> None:
    with pytest.raises(httpx.HTTPStatusError):
        run_search(PythonOrg(), router({"python.org": (403, "no")}))


def test_details_drop_the_title_heading(load_fixture: Callable[[str], Any]) -> None:
    stub = cards(load_fixture("pythonorg/list_page2.html"))[0]
    full = run_details(PythonOrg(), router(_routes(load_fixture)), stub)
    assert full.description.startswith("Job Description")
    assert "Our client is transforming" in full.description and "Job Title" not in full.description
    bare = run_details(PythonOrg(), router({"www.python.org/jobs/8109/": "<html></html>"}), stub)
    assert bare.description == ""


def test_task_needs_opt_in() -> None:
    cfg = SearchConfig.model_validate({"search": {"queries": ["python"]}})
    source = PythonOrg()
    assert source.kind == "board" and not source.is_enabled(cfg)
    assert [t.key for t in source.tasks(cfg)] == ["pythonorg:feed"]
