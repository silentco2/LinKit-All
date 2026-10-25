"""HRM Direct career sites ({board}.hrmdirect.com): one server-rendered listing of every opening
and a job page with the body. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlsplit

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug
from linkit_all.sources.text import html_to_text

CHUNK = 20  # job pages fetched per yielded page
_ID = re.compile(r"^\d+$")


def _ref(href: str) -> tuple[str, str] | None:
    """(req, req_loc) of a job link. One requisition open in several places is listed once per
    place, so the pair is the identity, never req alone."""
    parts = urlsplit(href)
    if parts.path.rsplit("/", 1)[-1] != "job-opening.php":
        return None
    q = parse_qs(parts.query)
    req, loc = (q.get("req") or [""])[0], (q.get("req_loc") or [""])[0]
    return (req, loc) if _ID.match(req) and _ID.match(loc) else None


def _decode(raw: bytes) -> str:
    """The pages declare no charset and are served as windows-1252 (smart quotes pasted from a
    word processor); anything that is valid UTF-8 is taken as UTF-8."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


class HrmDirect(Source):
    """The board is the tenant subdomain: `acme` for acme.hrmdirect.com."""

    name = "hrmdirect"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w-])(?!www\.)([\w-]+)\.hrmdirect\.com", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.lower()
        base = f"https://{board}.hrmdirect.com/employment/"
        # search=true with no filter is the site's own "all openings" query: one page, no paging.
        html = (await get_page(http, f"{base}job-openings.php?search=true")).text
        urls: list[str] = []
        for a in LexborHTMLParser(html).css("a[href]"):
            ref = _ref(a.attributes["href"] or "")
            # Rebuilt from the ids: the site appends an empty parameter and a "#job" fragment.
            url = f"{base}job-opening.php?req={ref[0]}&req_loc={ref[1]}" if ref else ""
            if url and url not in urls:
                urls.append(url)
        for i in range(start_page * CHUNK, len(urls), CHUNK):
            posts = [await self.posting(http, u, board) for u in urls[i : i + CHUNK]]
            yield [p for p in posts if p]

    async def posting(self, http: Http, url: str, board: str) -> JobStub | None:
        await http.allowed(url)
        resp = await http.get(url)
        if resp.status_code in (404, 410):
            return None
        resp.raise_for_status()
        # Read inside the posting block: the tenant's welcome blurb above it is free-form HTML.
        block = LexborHTMLParser(_decode(resp.content)).css_first(".reqResult")
        title = block.css_first("h2") if block else None
        if block is None or title is None or not title.text().strip():
            return None
        location = ""
        for cell in block.css("td.viewFieldName"):
            if cell.text().strip().removesuffix(":") == "Location":
                value = cell.next
                while value is not None and value.tag == "-text":
                    value = value.next
                raw = value.text() if value is not None else ""
                # ", NY" when the city is empty, "" when both are.
                location = ", ".join(p.strip() for p in raw.split(",") if p.strip())
                break
        desc = block.css_first("div.jobDesc")
        ref = _ref(url)
        return JobStub(
            source="hrmdirect",
            url=url,
            title=" ".join(title.text().split()),
            company=name_from_slug(board),
            location=location,
            description=html_to_text(desc.html or "") if desc else "",
            ats="hrmdirect",
            apply_url=url,
            remote=remote_from_text(location),  # the platform states no work arrangement
            extra={"board": board, "id": "-".join(ref) if ref else ""},
        )
