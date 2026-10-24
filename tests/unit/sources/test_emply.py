import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import emply
from linkit_all.sources.ats.emply import Emply, host_of
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_pages_map_and_skip_talent_pool(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(emply, "PAGE", 2)
    data = {0: load_fixture("emply/page0.json"), 2: load_fixture("emply/page1.json")}
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/integration/vacancy/get-page"
        body = json.loads(req.content)
        bodies.append(body)
        return httpx.Response(200, json=data[body["offset"]])

    pages = search_pages(Emply(), handler, board="paychex")
    assert [b["offset"] for b in bodies] == [0, 2] and bodies[0]["filters"] == []
    assert [len(p) for p in pages] == [1, 2]  # the talent-pool entry is dropped
    kok = pages[0][0]
    assert kok.title == "ØRESUNDSLINJEN søger passioneret kok"  # no English: first language
    assert (
        kok.url
        == "https://paychex.career.emply.com/ad/oresundslinjen-soger-passioneret-kok/2exc7k/da"
    )
    assert kok.location == "Færgevej, 8, 3000, Helsingør" and kok.company == "Paychex"
    assert kok.description and "<p>" not in kok.description
    assert kok.posted_at is not None and kok.posted_at.year == 2026
    assert kok.extra == {"board": "paychex", "id": "2exc7k"} and kok.ats == "emply"
    assert pages[1][1].url.endswith("/account-executive-m-f-d/t8sgwl/en")  # English preferred


def test_resume_and_bad_answer(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(emply, "PAGE", 2)
    offsets: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        offsets.append(json.loads(req.content)["offset"])
        return httpx.Response(200, json=load_fixture("emply/page1.json"))

    assert len(search_pages(Emply(), handler, board="midtjob.dk", start_page=1)) == 1
    assert offsets == [2]
    with pytest.raises(ValueError, match="vacancies"):
        search_pages(Emply(), lambda r: httpx.Response(200, json={"error": 1}), board="x")


def test_host_and_url_patterns() -> None:
    assert host_of("MolsLinjen") == "molslinjen.career.emply.com"
    assert host_of("midtjob.dk") == "midtjob.dk"
    assert detect("https://molslinjen.career.emply.com/ad/x/abc") == ("emply", "molslinjen")
    assert detect("emply:midtjob.dk") == ("emply", "midtjob.dk")
