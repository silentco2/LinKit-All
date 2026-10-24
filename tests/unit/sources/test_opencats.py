from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import opencats
from linkit_all.sources.ats.opencats import OpenCats, listed
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def make_handler(
    load_fixture: Callable[[str], Any], listing: str = "listing.html", **details: str
) -> Callable[[httpx.Request], httpx.Response]:
    """Details are keyed by posting id, e.g. `ID51="detail.html"`."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("robots.txt"):
            return httpx.Response(404)
        query = str(req.url.query, "ascii")
        if "p=showAll" in query:
            return httpx.Response(200, text=load_fixture(f"opencats/{listing}"))
        for key, fixture in details.items():
            if query.endswith(key.replace("ID", "ID=")):
                return httpx.Response(200, text=load_fixture(f"opencats/{fixture}"))
        return httpx.Response(404)

    return handler


def test_listing_skips_general_application_and_actions(
    load_fixture: Callable[[str], Any],
) -> None:
    found = listed(load_fixture("opencats/listing.html"), "https://careers.boomit.pt/careers/")
    assert [(x.id, x.title) for x in found] == [
        ("51", "MuleSoft Platform Support Engineer (L2)"),
        ("60", "Application Security Engineer"),  # "Application" alone is not an open application
    ]
    assert found[0].url == "https://careers.boomit.pt/careers/index.php?m=careers&p=showJob&ID=51"


def test_listing_reads_rewritten_templates_and_clickable_rows(
    load_fixture: Callable[[str], Any],
) -> None:
    found = listed(load_fixture("opencats/listing_rewritten.html"), "https://atscareers.g4s.com/")
    assert [(x.id, x.title) for x in found] == [
        ("30156", "Security Analyst"),
        ("30157", "Night Guard"),
    ]
    assert found[1].url == "https://atscareers.g4s.com/index.php?m=careers&p=showJob&ID=30157"


def test_search_maps_listing_and_detail(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    handler = make_handler(load_fixture, ID51="detail.html", ID60="detail_renamed.html")
    pages = search_pages(OpenCats(), handler, board="careers.boomit.pt/careers")
    first, second = pages[0]
    assert first.title == "MuleSoft Platform Support Engineer (L2)" and first.ats == "opencats"
    assert first.company == "Boomit"
    assert first.url == "https://careers.boomit.pt/careers/index.php?m=careers&p=showJob&ID=51"
    assert first.location == "Lisboa, Lisboa"  # the labelled field, not the listing column
    assert "Suporte L2" in first.description and "alert" not in first.description
    assert "está" in first.description  # accented prose survives
    assert first.extra == {"board": "careers.boomit.pt/careers", "id": "51"}
    # the renamed body container ("job-decription") is a known one
    assert second.location == "Gulberg 3, Lahore"
    assert "Build and maintain PHP services" in second.description


def test_localised_label_falls_back_to_first_details_row(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    handler = make_handler(load_fixture, ID51="detail_localised.html", ID60="detail.html")
    pages = search_pages(OpenCats(), handler, board="opencats.gorgany.com/careers")
    assert pages[0][0].location == "Київ, Україна"
    assert "Робота в магазині" in pages[0][0].description


def test_root_mounted_board_and_unreadable_detail(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    handler = make_handler(load_fixture, "listing_rewritten.html", ID30156="detail.html")
    pages = search_pages(OpenCats(), handler, board="atscareers.g4s.com", calls=calls)
    assert [j.title for j in pages[0]] == ["Security Analyst"]  # the unreadable posting is dropped
    assert "https://atscareers.g4s.com/index.php?m=careers&p=showAll" in calls


def test_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(opencats, "CHUNK", 1)
    handler = make_handler(load_fixture, ID51="detail.html", ID60="detail.html")
    assert len(search_pages(OpenCats(), handler, board="a.example.com")) == 2
    resumed = search_pages(OpenCats(), handler, board="a.example.com", start_page=1)
    assert [j.title for p in resumed for j in p] == ["Application Security Engineer"]


def test_bad_board(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(ValueError, match="not a portal root"):
        search_pages(OpenCats(), lambda r: httpx.Response(200), board="acme")


def test_shorthand() -> None:
    assert detect("opencats:careers.boomit.pt/careers") == ("opencats", "careers.boomit.pt/careers")
