"""AppliTrack (Frontline Education), the applicant tracking system of school districts; a tenant
is a path segment of www.applitrack.com. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import datetime
from urllib.parse import quote
from urllib.parse import quote_plus as qp

from selectolax.lexbor import LexborHTMLParser
from selectolax.lexbor import LexborNode as Node

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

BASE = "https://www.applitrack.com"
# The pages are JavaScript: Output.asp document.writes the whole page, and the markup only
# exists once its string arguments are unescaped. Nothing is served as HTML.
_WRITE = re.compile(r"document\.write\('((?:[^'\\]|\\.)*)'\)", re.S)
_OPEN = "document.write('"
_UNESCAPE = re.compile(r"\\(.)", re.S)
_ID = re.compile(r"AppliTrackJobId(?:=|%3D)(\d+)", re.I)
_URL = re.compile(
    r"applitrack\.com/([^/]+)/onlineapp/jobpostings/view\.asp\?AppliTrackJobId=(\d+)", re.I
)


def directory(board: str) -> str:
    return f"{BASE}/{quote(board)}/onlineapp/jobpostings/"


def written(body: str) -> str:
    """The markup the response's document.write('...') calls emit, JS escapes undone. A call that
    runs off the end means a cut-short response: refuse it rather than read a partial listing."""
    out, pos = [], 0
    while (start := body.find(_OPEN, pos)) >= 0:
        m = _WRITE.match(body, start)
        if m is None:
            raise ValueError("truncated response: a document.write ran off the end of the body")
        out.append(_UNESCAPE.sub(r"\1", m[1]))
        pos = m.end()
    return "".join(out)


def decode(raw: bytes) -> str:
    """The pages declare no character set and are served as windows-1252."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def us_date(text: str) -> datetime | None:
    """9/1/2026 (month first, not padded); free text such as "ASAP" gives None."""
    try:
        return datetime.strptime(text.strip(), "%m/%d/%Y")
    except ValueError:
        return None


def _is(node: Node, tag: str, cls: str) -> bool:
    return node.tag == tag and cls in (node.attributes.get("class") or "").split()


def label_text(cell: Node, label: str) -> str:
    """Text after the `<span class=label>label:</span>` in a listing cell, up to the next label."""
    out, on = [], False
    for child in cell.iter(include_text=True):
        if _is(child, "span", "label"):
            on = child.text().strip().rstrip(":").strip() == label
        elif on:
            out.append(child.text())
    return " ".join("".join(out).split())


class AppliTrack(Source):
    name = "applitrack"
    kind = "ats"
    url_patterns = (re.compile(r"applitrack\.com/([\w-]+)/onlineapp", re.I),)

    async def _page(self, http: Http, url: str) -> LexborHTMLParser:
        if not await http.allowed(url):
            raise Unsupported(f"robots.txt does not allow fetching {url}")
        resp = await http.get(url)
        resp.raise_for_status()
        return LexborHTMLParser(written(decode(resp.content)))

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        # "all=1" is the site's own "All Vacancies"; "condensed" keeps bodies out of the rows.
        url = directory(task.board) + "Output.asp?AppliTrackLayoutMode=condensed&all=1"
        yield self.parse_listing(await self._page(http, url), task.board)

    @staticmethod
    def parse_listing(tree: LexborHTMLParser, board: str) -> list[JobStub]:
        company = board.replace("-", " ").replace("_", " ").title()
        out: dict[str, JobStub] = {}
        for span in tree.css("span.title"):
            link = span.css_first("a")
            m = _ID.search(link.attributes.get("href") or "") if link else None
            if link is None or m is None or m[1] in out:  # a consortium lists one id per district
                continue
            row = span.parent.parent if span.parent else None  # <tr><td><span>
            cells = row.css("td") if row else []
            details = row.next if row else None  # the row beneath: ID and Location labels
            cell = details.css_first("td") if details else None
            place = label_text(cell, "Location") if cell else ""
            url = directory(board) + f"view.asp?AppliTrackJobId={qp(m[1])}"
            out[m[1]] = JobStub(
                source="applitrack",
                url=url,
                title=" ".join(span.text().removesuffix(link.text()).split()),
                company=company,
                location=place,
                posted_at=us_date(cells[1].text()) if len(cells) > 1 else None,
                ats="applitrack",
                apply_url=url,
                remote=remote_from_text(place),
                extra={"board": board, "id": m[1]},
            )
        return list(out.values())

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m:
            return stub
        board, job = m.groups()
        tree = await self._page(http, directory(board) + f"Output.asp?AppliTrackJobId={qp(job)}")
        # The endpoint answers an id the board no longer carries with 200 and an empty list, so
        # the block is selected by the id asked for.
        block = tree.css_first(f'[id="p{job}_"]')
        if block is None:
            return stub
        body = next(
            (n for n in block.css("span.normal") if not _in_li(n, block)),
            None,
        )
        if body is None:
            return stub
        fields = {}
        for label in block.css("span.label"):
            sib = label.next
            while sib is not None and not _is(sib, "span", "normal"):
                sib = sib.next
            if sib is not None:
                fields[label.text().strip().rstrip(":").strip()] = " ".join(sib.text().split())
        place = fields.get("Location", "") or stub.location
        return stub.model_copy(
            update={
                "description": html_to_text(body.html or ""),
                "location": place,
                "posted_at": us_date(fields.get("Date Posted", "")) or stub.posted_at,
                "remote": remote_from_text(place),
            }
        )


def _in_li(node: Node, block: Node) -> bool:
    """Is `node` inside one of the block's field rows? (The body holds lists of its own.)"""
    parent = node.parent
    while parent is not None and parent.mem_id != block.mem_id:
        if parent.tag == "li":
            return True
        parent = parent.parent
    return False
