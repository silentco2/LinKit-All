"""InRecruiting, Zucchetti's ATS (formerly Intervieweb): {board}.intervieweb.it/it/career. The
career page is server-rendered, 15 cards a page; later pages come from the POST the page's own
script sends, to the guest URL and with the `section` token the page carries. Cards have no
date and no body. Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, page_text, post_form
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import clean, name_from_slug
from linkit_all.sources.text import html_to_text

CAREER = "https://{board}.intervieweb.it/it/career"
MAX_PAGES = 200
_CARD = re.compile(
    r"<a[^>]+href=[\"'](https://[a-z0-9-]+\.intervieweb\.it/jobs/[^\"'#?]+)[\"'][^>]*>"
    r"\s*<h3[^>]*>(.*?)</h3>",
    re.I | re.S,
)
_PLACE = re.compile(
    r"mi-location_on.*?</i>\s*(?:<span[^>]*sr-only[^>]*>.*?</span>)?(.*?)</span>", re.I | re.S
)
_ANNOUNCES = re.compile(r"id=[\"']url-for-announces[\"'][^>]*value=[\"']([^\"']+)[\"']", re.I)
_SECTION = re.compile(r"['\"]section['\"]\s*:\s*['\"]([A-Za-z0-9_-]+)['\"]")
_NEXT = re.compile(
    r"pagination_next[\"'][^>]*onclick=[\"']researchAnnounces\(\s*(\d+)\s*,\s*'([a-z_]+)'", re.I
)
_ID = re.compile(r"-(\d+)/[a-z]{2}/?$")
_FILTERS = ("country", "region", "function", "project", "text", "division", "company")


class InRecruiting(Source):
    name = "inrecruiting"
    kind = "ats"
    url_patterns = (
        re.compile(
            r"(?<![\w.-])(?!(?:www|inrecruiting)\.)([a-z0-9][a-z0-9-]*)\.intervieweb\.it", re.I
        ),
    )
    cdx_hosts = ("*.intervieweb.it",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = f"{task.board.lower()}.intervieweb.it"
        html = (await get_page(http, CAREER.format(board=task.board.lower()))).text
        announces, section = _ANNOUNCES.search(html), _SECTION.search(html)
        seen: set[str] = set()
        for page in range(MAX_PAGES):
            stubs = [s for s in self.cards(html, task.board) if s.url not in seen]
            seen.update(s.url for s in stubs)
            if page >= start_page and stubs:
                yield stubs
            nxt = _NEXT.search(html)
            if not (nxt and announces and section):
                return
            # Only the query of the page's guest URL is used; the host stays the tenant's own.
            url = f"https://{host}/app.php?{urlsplit(announces[1].replace('&amp;', '&')).query}"
            form = {
                "act1": "vacancyListCareer",
                "section": section[1],
                "order": nxt[2],
                "page": nxt[1],
                **dict.fromkeys(_FILTERS, ""),
            }
            data = (await post_form(http, url, form)).json()
            if not isinstance(data, dict) or data.get("success") is not True:
                raise ValueError("inrecruiting: the next page did not answer success")
            html = str(data.get("data") or "")

    @staticmethod
    def cards(html: str, board: str) -> list[JobStub]:
        found = list(_CARD.finditer(html))
        stubs = []
        for i, m in enumerate(found):
            end = found[i + 1].start() if i + 1 < len(found) else len(html)
            place = _PLACE.search(html, m.end(), end)
            title, where = clean(html_to_text(m[2])), clean(html_to_text(place[1])) if place else ""
            if not title:
                continue
            jid = _ID.search(m[1])
            stubs.append(
                JobStub(
                    source="inrecruiting",
                    url=m[1],
                    title=title,
                    company=name_from_slug(board),
                    location=where,
                    ats="inrecruiting",
                    apply_url=m[1],
                    remote=remote_from_text(where, title),
                    extra={"board": board, "id": jid[1] if jid else ""},
                )
            )
        return stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        body = html_to_text(str(found[0].get("description") or "")) if found else ""
        return stub.model_copy(update={"description": body}) if body else stub
