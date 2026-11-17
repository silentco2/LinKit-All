"""rexx systems job portals. A portal runs on the employer's own host (jobs.acme.com,
karriere.acme.de), so no address pattern finds one: add it as "rexx:https://jobs.acme.com" or
with its list page. The list is server-rendered, one card per posting, paged with `?start=`;
the page size is the portal's own, so the walk advances by the cards a page carried. Cards
have no date or body: `fetch_details` reads both from the posting page's JobPosting data.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import name_from_host, node_text, safe_date
from linkit_all.sources.text import html_to_text

LIST_PAGE = "stellenangebote.html"
MAX_PAGES = 200
_DETAIL = re.compile(r"-j(\d+)\.html$", re.I)


def list_url(board: str) -> str:
    """The portal's list page: the address given, or `stellenangebote.html` under a bare host
    or folder. Query and fragment are dropped."""
    parts = urlsplit(board if "://" in board else f"https://{board}")
    path = parts.path or "/"
    return f"https://{parts.hostname}{path + LIST_PAGE if path.endswith('/') else path}"


class Rexx(Source):
    name = "rexx"
    kind = "ats"

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        # ponytail: a resumed run restarts at the first page (the offset depends on page sizes
        # only known by walking); the store drops what it already has.
        base = list_url(task.board)
        seen: set[str] = set()
        offset = 0
        for _ in range(MAX_PAGES):
            html = (await get_page(http, f"{base}?start={offset}" if offset else base)).text
            cards = self.cards(html, base, task.board)
            new = [s for s in cards if s.extra["id"] not in seen]
            seen.update(s.extra["id"] for s in new)
            if not new:
                return
            yield new
            offset += len(cards)

    @staticmethod
    def cards(html: str, base: str, board: str) -> list[JobStub]:
        host = urlsplit(base).hostname or ""
        stubs = []
        for card in LexborHTMLParser(html).css(".joboffer_container"):
            for a in card.css("a[href]"):
                url = urljoin(base, a.attributes.get("href") or "").split("#")[0].split("?")[0]
                m, title = _DETAIL.search(url), node_text(a)
                if m and title and urlsplit(url).hostname == host:
                    break
            else:
                continue
            # Newer skins mark the place; older ones list plain columns with the place last.
            where = node_text(card.css_first(".job_standort"))
            if not where:
                boxes = [t for b in card.css("div.joboffer_informations") if (t := node_text(b))]
                where = boxes[-1] if boxes else ""
            stubs.append(
                JobStub(
                    source="rexx",
                    url=url,
                    title=title,
                    company=name_from_host(host),
                    location=where,
                    ats="rexx",
                    apply_url=url,
                    remote=remote_from_text(where, title),
                    extra={"board": board, "id": m[1]},
                )
            )
        return stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        if not found:
            return stub
        body = html_to_text(str(found[0].get("description") or ""))
        update = {"description": body, "posted_at": safe_date(found[0].get("datePosted"))}
        return stub.model_copy(update={k: v for k, v in update.items() if v})
