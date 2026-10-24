from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.hireology import Hireology
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_open_postings_are_mapped_and_the_rest_dropped(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Hireology(),
        lambda req: httpx.Response(200, json=load_fixture("hireology/careers.json")),
        board="acme",
        calls=calls,
    )
    assert calls == ["https://api.hireology.com/v1/careers/acme"]
    assert len(pages) == 1 and [s.title for s in pages[0]] == ["Pet Sitter", "Dispatcher"]
    sitter, dispatcher = pages[0]
    assert sitter.url == "https://careers.hireology.com/acme/25816/description"
    assert sitter.company == "Acme" and sitter.location == "Highlands Ranch, CO"
    assert sitter.description == "Sit pets." and sitter.remote is None
    assert sitter.extra == {"board": "acme", "id": "25816"} and sitter.ats == "hireology"
    # No career-site-url: the public page address is rebuilt from the ids.
    assert dispatcher.url == "https://careers.hireology.com/acme/25817/description"
    assert dispatcher.remote == "remote" and dispatcher.location == ""


def test_resume_and_url_patterns(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    handler = lambda req: httpx.Response(200, json=load_fixture("hireology/careers.json"))  # noqa: E731
    assert search_pages(Hireology(), handler, board="acme", start_page=1) == []
    assert detect("https://careers.hireology.com/acme/25816/description") == ("hireology", "acme")
    assert detect("https://api.hireology.com/v1/careers/acme") == ("hireology", "acme")
