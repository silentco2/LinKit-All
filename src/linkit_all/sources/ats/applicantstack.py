"""ApplicantStack career sites (<board>.applicantstack.com), a server-rendered ATS for small US
employers. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub
from linkit_all.sources.text import html_to_text

LISTING = "https://{board}.applicantstack.com/x/openings"
DETAIL = "https://{board}.applicantstack.com/x/detail/{id}"
MAX_PAGES = 50  # 100 rows a page
_ID = re.compile(r"/x/detail/([A-Za-z0-9_-]+)")
_TOTAL = re.compile(r"\bof\s+(\d+)")
_URL = re.compile(r"//([\w-]+)\.applicantstack\.com/x/detail/", re.I)


class ApplicantStack(Source):
    name = "applicantstack"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.applicantstack\.com", re.I),)
    # robots.txt asks for Crawl-delay 5 per tenant host; Http applies it after reading robots.

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.lower()
        company = board.replace("-", " ").title()
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            url = LISTING.format(board=board) + (f"?pge={page}" if page > 1 else "")
            if not await http.allowed(url):
                raise Unsupported(f"robots.txt does not allow fetching {url}")
            resp = await http.get(url)
            resp.raise_for_status()
            rows, total = self.parse_listing(resp.text, board, company)
            fresh = [s for s in rows if s.extra["id"] not in seen]
            seen.update(s.extra["id"] for s in fresh)
            if fresh:
                yield fresh
            # ponytail: an out-of-range page has no table and raises above; a stalled pager
            # (a page adding nothing) just ends the walk.
            if not fresh or total is None or page * 100 >= total:
                return

    @staticmethod
    def parse_listing(html: str, board: str, company: str) -> tuple[list[JobStub], int | None]:
        """Rows of one listing page and the total its pager states (None = no pager). A page
        without the openings table is no listing (unknown tenants redirect to the vendor site)."""
        tree = LexborHTMLParser(html)
        table = tree.css_first("#data-table")
        if table is None:
            raise Unsupported(f"{board}.applicantstack.com has no openings table")
        heads = [" ".join(th.text().split()).lower() for th in table.css("thead th")]
        loc_col = heads.index("location") if "location" in heads else None
        rows = []
        for tr in table.css("tbody tr"):
            link, job_id = next(
                ((a, m) for a in tr.css("a") if (m := _ID.search(a.attributes.get("href") or ""))),
                (None, None),
            )
            if link is None or job_id is None:
                continue
            cells = tr.css("td")
            place = (
                " ".join(cells[loc_col].text().split())
                if loc_col is not None and loc_col < len(cells)
                else ""
            )
            url = DETAIL.format(board=board, id=job_id[1])
            rows.append(
                JobStub(
                    source="applicantstack",
                    url=url,
                    title=" ".join(link.text().split()),
                    company=company,
                    location=place,
                    ats="applicantstack",
                    apply_url=url,
                    remote=remote_from_text(place),
                    extra={"board": board, "id": job_id[1]},
                )
            )
        pager = tree.css_first(".tablepager")
        m = _TOTAL.search(pager.text()) if pager else None
        if pager is None and rows:
            raise ValueError("listing rows but no pager stating a total")
        return rows, int(m[1]) if m else None

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m or not await http.allowed(stub.url):
            return stub
        resp = await http.get(stub.url)
        resp.raise_for_status()
        postings = job_postings(resp.text)[:1]  # its own "title" is often null: keep the row's
        if not postings:
            return stub
        found = to_stub(postings[0], self.name, stub.url, self.name)
        return stub.model_copy(
            update={
                "description": html_to_text(postings[0].get("description") or ""),
                "location": stub.location or found.location,
                "posted_at": found.posted_at,
                "remote": stub.remote or found.remote or remote_from_text(found.location),
            }
        )
