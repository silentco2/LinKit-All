"""C3 sources: Gradcracker (UK graduates), Jobindex (Denmark), Naukri (India, via python-jobspy)."""

import asyncio
from pathlib import Path

import httpx

from linkit_all.core.presets import country_preset, source_preset
from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.base import JobStub, Task
from linkit_all.sources.boards.gradcracker import Gradcracker, disciplines, parse_cards
from linkit_all.sources.boards.jobindex import Jobindex, results
from linkit_all.sources.http import Http
from linkit_all.sources.jobspy_sites import JOBSPY_SITES

FIX = Path(__file__).parents[1] / "fixtures"
GC = (FIX / "gradcracker" / "listing.html").read_text("utf-8")
JI = (FIX / "jobindex" / "search.html").read_text("utf-8")


def crawl(
    source: Gradcracker | Jobindex, task: Task, pages: dict[str, str]
) -> tuple[list[JobStub], list[str]]:
    asked: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        asked.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        page = pages.get(req.url.query.decode() or "first")
        return httpx.Response(200, text=page or "<html></html>")

    async def go() -> list[JobStub]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            http = Http(client, default_rate=1000, attempts=1)
            return [s async for page in source.search(http, task, 0) for s in page]

    return asyncio.run(go()), asked


def test_gradcracker_cards_skip_the_honeypot() -> None:
    cards = parse_cards(GC)
    assert len(cards) == 3 and all("featured-graduate-employer" not in c.url for c in cards)
    acc = next(c for c in cards if c.company == "Accenture")
    assert acc.fields["Location"] == "Glasgow (Hybrid)" and "£36,400" in acc.fields["Salary"]
    stub = Gradcracker().stub(acc)
    assert (stub.location, stub.remote, stub.apply_url) == ("Glasgow", "hybrid", acc.url)
    assert "Salary: £36,400 per year" in stub.description and "Disciplines: IT" in stub.description


def test_gradcracker_disciplines_from_titles() -> None:
    assert disciplines(["Software Engineer", "Data Analyst"]) == ["technology-it"]
    assert disciplines(["Electrical Engineer", "Civil Engineer"]) == [
        "electronic-electrical", "civil-building"]  # fmt: skip
    assert disciplines(["Nurse"]) == ["all-disciplines"] and disciplines([]) == ["all-disciplines"]
    cfg = SearchConfig()
    cfg.search.queries = ["Python Developer"]
    assert [t.board for t in Gradcracker().tasks(cfg)] == ["technology-it"]


def test_gradcracker_reads_pages_until_one_has_nothing_new() -> None:
    task = Task("gradcracker", "gradcracker:technology-it", board="technology-it", limit=100)
    got, asked = crawl(Gradcracker(), task, {"first": GC, "page=2": GC})  # page 2 repeats page 1
    assert len(got) == 3 and asked[-1].endswith("/search/technology-it/graduate-jobs?page=2")


def test_jobindex_reads_the_page_data() -> None:
    rows, pages = results(JI)
    assert len(rows) == 3 and pages == 11
    assert results("<html>no data</html>") == ([], 0)
    task = Task("jobindex", "jobindex:python@", query="python developer", limit=2)
    got, asked = crawl(Jobindex(), task, {"q=python+developer": JI})
    assert len(got) == 2 and "q=python+developer" in asked[-1]  # the limit stops paging
    job = got[0]
    assert job.url.startswith("https://www.jobindex.dk/vis-job/") and job.company == "Energinet"
    assert job.apply_url.startswith("https://candidate.hr-manager.net/")  # the employer's form
    assert job.location == "Fredericia" and job.posted_at is not None and len(job.description) > 300


def test_naukri_and_the_new_boards_are_registered_and_suggested() -> None:
    assert "naukri" in JOBSPY_SITES
    found = registry()
    assert {"gradcracker", "jobindex", "naukri"} <= set(found)
    assert found["gradcracker"].kind == found["jobindex"].kind == "board"
    india = source_preset(country_preset("India"), "tech")
    assert "naukri" in india["regional"]
    assert "gradcracker" in source_preset(country_preset("United Kingdom"), "tech")["enabled"]
    assert (
        "gradcracker" not in source_preset(country_preset("United Kingdom"), "general")["enabled"]
    )
    for track in ("tech", "general"):
        assert "jobindex" in source_preset(country_preset("Denmark"), track)["enabled"]
    cfg = SearchConfig.model_validate({"sources": {"regional": ["naukri"]},
                                       "search": {"queries": ["python"], "locations": ["Pune"]}})  # fmt: skip
    assert [t.key for t in found["naukri"].tasks(cfg)] == ["naukri:python@Pune"]
