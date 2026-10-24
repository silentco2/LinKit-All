from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import hrmdirect
from linkit_all.sources.ats.hrmdirect import HrmDirect
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def _handler(fixtures_dir: Any, calls: list[str]) -> Any:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(str(req.url))
        if req.url.path.endswith("job-openings.php"):
            return httpx.Response(200, content=(fixtures_dir / "hrmdirect/list.html").read_bytes())
        q = req.url.params
        name = f"hrmdirect/job_{q['req']}_{q['req_loc']}.html"
        return httpx.Response(200, content=(fixtures_dir / name).read_bytes())

    return handler


def test_one_row_per_requisition_and_location(
    search_pages: Callable[..., list[list[JobStub]]], fixtures_dir: Any
) -> None:
    calls: list[str] = []
    pages = search_pages(HrmDirect(), _handler(fixtures_dir, calls), board="acme")
    base = "https://acme.hrmdirect.com/employment/"
    assert calls == [
        base + "job-openings.php?search=true",
        base + "job-opening.php?req=100&req_loc=11",
        base + "job-opening.php?req=100&req_loc=12",
        base + "job-opening.php?req=200&req_loc=21",
    ]  # the repeated row and the filter-form link are not postings
    austin, remote, support = pages[0]
    assert austin.title == "Senior Platform Engineer" and austin.company == "Acme"
    assert austin.url == base + "job-opening.php?req=100&req_loc=11"
    assert austin.location == "Austin, TX" and austin.remote is None
    assert austin.extra == {"board": "acme", "id": "100-11"} and austin.ats == "hrmdirect"
    # windows-1252 right single quote, decoded; the script is gone.
    assert austin.description == "Own the platform\u2019s roadmap."
    assert remote.location == "Remote" and remote.remote == "remote"  # ", Remote" loses its comma
    assert remote.extra["id"] == "100-12"  # same requisition, its own identity
    assert support.location == "" and support.description == "Lead the desk."


def test_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    fixtures_dir: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hrmdirect, "CHUNK", 2)
    pages = search_pages(HrmDirect(), _handler(fixtures_dir, []), board="acme")
    assert [len(p) for p in pages] == [2, 1]
    calls: list[str] = []
    pages = search_pages(HrmDirect(), _handler(fixtures_dir, calls), board="acme", start_page=1)
    assert [len(p) for p in pages] == [1] and not any("req_loc=11" in c for c in calls)


def test_a_page_without_a_posting_block_is_skipped(
    search_pages: Callable[..., list[list[JobStub]]], fixtures_dir: Any
) -> None:
    inner = _handler(fixtures_dir, [])

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.params.get("req") == "200":
            return httpx.Response(200, text="<html><body>maintenance</body></html>")
        return inner(req)

    pages = search_pages(HrmDirect(), handler, board="acme")
    assert [s.extra["id"] for s in pages[0]] == ["100-11", "100-12"]


def test_job_ref_and_url_patterns() -> None:
    ref = hrmdirect._ref
    assert ref("job-opening.php?req=100&req_loc=11&&#job") == ("100", "11")
    assert ref("job-opening.php?req_loc=11&src=email&req=100") == ("100", "11")
    assert ref("job-opening.php?req=100") is None  # one requisition spans several locations
    assert ref("job-opening.php?req=abc&req_loc=11") is None
    assert ref("job-openings.php?search=true&dept=7") is None
    assert detect("https://acme.hrmdirect.com/employment/job-openings.php") == ("hrmdirect", "acme")
