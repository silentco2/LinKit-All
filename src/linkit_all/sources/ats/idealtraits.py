"""IdealTraits career sites (app.idealtraits.com), a hiring platform used mostly by US insurance
agencies: the career site's own pagination XHR answers JSON holding the cards' HTML, and each
posting page carries a schema.org JobPosting plus a "Remote Type" field. Logic adapted from
freehire (MIT)."""

import base64
import binascii
import re
from collections.abc import AsyncIterator
from urllib.parse import unquote

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f13 import name_from_slug
from linkit_all.sources.ats._f15 import fetch_html, posting_stub
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http

MAX_PAGES = 50  # a ceiling, never the way a walk ends
# The same URL with this header answers the listing as JSON, whatever the slug in the path.
XHR = {"X-Requested-With": "XMLHttpRequest"}
_CARD = re.compile(r"^https://app\.idealtraits\.com/career/[^/]+/(\d+)[A-Za-z]*$")
_MODES: dict[str, Remote] = {"No": "onsite", "Hybrid Remote": "hybrid", "Fully Remote": "remote"}
_BENEFITS = re.compile(r"[^<>]*###[^<>]*")  # the benefits picklist, stored as one "###" string


def business_id(board: str) -> str:
    """The numeric business id of a board given as that id or as the base64 form in career-site
    URLs (`.../<slug>/MTE2MjI5Mg==/careers`)."""
    if board.isdigit():
        return board
    try:
        decoded = base64.b64decode(unquote(board)).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        decoded = ""
    if not decoded.isdigit():
        raise ValueError(f"idealtraits: board {board!r} is not a business id")
    return decoded


def list_url(board: str, page: int) -> str:
    key = base64.b64encode(business_id(board).encode()).decode()
    return f"https://app.idealtraits.com/company/{key}/careers?page={page}"


def cards(fragment: str) -> list[tuple[str, str, str]]:
    """(posting id, url, title) of every card; a commented-out copy of a card is not an element."""
    found = []
    for node in LexborHTMLParser(fragment or "<p></p>").css(".opportunity-card"):
        url = (node.attributes.get("data-landingpage") or "").strip()
        if m := _CARD.match(url):
            h5 = node.css_first("h5")
            found.append((m[1], url, " ".join(h5.text().split()) if h5 else ""))
    return found


def benefit_lists(body: str) -> str:
    """Turn each "A###B###" run in the body into the list it is."""

    def to_list(m: re.Match[str]) -> str:
        items = [i.strip() for i in m[0].split("###") if i.strip()]
        return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else ""

    return _BENEFITS.sub(to_list, body)


class IdealTraits(Source):
    """The board is the employer's numeric business id (or its base64 form from a career-site
    URL, which this decodes)."""

    name = "idealtraits"
    kind = "ats"
    url_patterns = (
        re.compile(r"app\.idealtraits\.com/[\w-]+/([A-Za-z0-9+]+(?:=|%3D)*)/careers", re.I),
    )

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # boards have 1-5 postings and fit one page
            return
        board = business_id(task.board)
        found: dict[str, tuple[str, str]] = {}  # posting id -> (url, title)
        total = -1
        for page in range(1, MAX_PAGES + 1):
            url = list_url(board, page)
            if not await http.allowed(url):
                raise Unsupported(f"robots.txt does not allow fetching {url}")
            resp = await http.get(url, headers=XHR)
            resp.raise_for_status()
            data = resp.json()
            total = int(data.get("jobcount") or 0) if total < 0 else total
            before = len(found)
            for job_id, link, title in cards(data.get("joblist") or ""):
                found.setdefault(job_id, (link, title))
            if len(found) >= total or len(found) == before:
                break
        if len(found) != total:  # never hand back a silently truncated board
            raise ValueError(f"idealtraits: read {len(found)} postings of {total} on {board}")
        stubs = []
        for job_id, (link, title) in found.items():
            html = await fetch_html(http, link)
            if html is None:
                continue
            stub = posting_stub(
                html, source=self.name, url=link, board=board, id=job_id, company="",
                prep=benefit_lists,
            )  # fmt: skip
            if stub is None:
                continue
            node = LexborHTMLParser(html).css_first("#remote-type")
            remote = _MODES.get(node.text().strip()) if node else None
            org = stub.company.replace("-", " ")  # the posting names the URL slug "Comma-Insurance"
            stubs.append(
                stub.model_copy(
                    update={
                        "title": stub.title or title,
                        "company": org or name_from_slug(board),
                        "remote": remote or stub.remote,
                    }
                )
            )
        yield stubs
