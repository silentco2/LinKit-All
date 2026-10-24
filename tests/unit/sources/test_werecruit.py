from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.werecruit import WeRecruit, offers_of, split_board
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def handler_for(
    load_fixture: Callable[[str], Any],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/en/idiap":
            return httpx.Response(200, text=load_fixture("werecruit/listing.html"))
        if req.url.path.endswith("postdoctoral-researcher-49895d"):
            return httpx.Response(200, text=load_fixture("werecruit/detail.html"))
        return httpx.Response(404)  # the other offer's page is gone

    return handler


def test_lists_offers_and_reads_each_body(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(WeRecruit(), handler_for(load_fixture), board="en/idiap")
    assert len(pages) == 1 and len(pages[0]) == 1  # the second offer's page 404s: not stored
    job = pages[0][0]
    assert job.title == "Postdoctoral Researcher" and job.company == "Idiap"
    assert job.url == "https://careers.werecruit.io/en/idiap/offers/postdoctoral-researcher-49895d"
    assert job.location == "Martigny, Valais" and job.ats == "werecruit"
    assert job.description == "Join our research team."  # scoped to div.description, no script
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-08-20T15:07:34.260645"
    assert job.extra == {
        "board": "en/idiap",
        "id": "49895d7f-fe57-4d0d-92d7-126837be0ea3",
        "employment": "Full time",
        "country": "CH",
    }


def test_unconfigured_locale_is_empty_and_resume(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    nothing = lambda req: httpx.Response(200, text="<html><body>no offers</body></html>")  # noqa: E731
    assert search_pages(WeRecruit(), nothing, board="fr/idiap") == []
    assert (
        search_pages(WeRecruit(), handler_for(load_fixture), board="en/idiap", start_page=1) == []
    )


def test_offers_parsing_and_board_validation() -> None:
    assert offers_of("<script>window.allOffers = [];</script>") == []
    page = (
        'window.allOffers = [{"Id":"a","Url":"u","TitleTranslated":"[x] ]"}, {"Id":""}];\nrest ] ['
    )
    assert [o["Id"] for o in offers_of(page)] == ["a"]  # brackets in values and after the array
    assert split_board("en/idiap") == ("en", "idiap")
    for bad in ("", "en", "en/", "/idiap", "a/b/c"):
        with pytest.raises(ValueError, match="locale>/<tenant"):
            split_board(bad)


def test_url_patterns() -> None:
    url = "https://careers.werecruit.io/en/idiap/offers/postdoctoral-researcher-49895d"
    assert detect(url) == ("werecruit", "en/idiap")
    assert detect("https://careers.werecruit.io/fr-ch/acme") == ("werecruit", "fr-ch/acme")
    assert detect("werecruit:en/idiap") == ("werecruit", "en/idiap")
