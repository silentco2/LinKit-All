"""Factorial (FactorialHR) career sites: the careers root lists every /job_posting/<slug>-<id> link
and each job page is plain HTML. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f13 import fetch_all, get_page, name_from_host
from linkit_all.sources.base import JobStub, Remote, Source, Task, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

CHUNK = 15  # job pages read together per page of stubs
_ID = re.compile(r"-(\d+)/?$")
# "Ibrido (Milano, Lombardia, Italia)": a work-mode word, then places. The comma inside the
# brackets keeps a team row such as "S - Partnerships (PAR)" out.
_PAREN = re.compile(r"^(.+?)\s*\(([^()]*,[^()]*)\)\s*$")
_MODES: dict[str, Remote] = {
    **dict.fromkeys(("ibrido", "híbrido", "hibrido", "hybrid", "hibride"), "hybrid"),
    **dict.fromkeys(
        ("da remoto", "remoto", "remota", "remote", "en remoto", "teletrabajo"), "remote"
    ),
    **dict.fromkeys(
        ("in sede", "presencial", "presenziale", "on-site", "on site", "onsite", "no escritório",
         "no local"),
        "onsite",
    ),
}  # fmt: skip


def location_of(rows: list[str]) -> tuple[str, Remote | None]:
    """The location among a job's unlabeled metadata rows (contract, schedule, salary, place,
    team, in no fixed order): the row naming places has a comma and no currency symbol."""
    for row in (r.strip() for r in rows):
        if not row or any(c in row for c in "€$£₹¥"):
            continue
        if m := _PAREN.match(row):
            return m[2].strip(), _MODES.get(m[1].strip().lower())
        if "," in row:
            return row, None
    return "", None


def parse_job(html: str, url: str, board: str) -> JobStub | None:
    m = _ID.search(urlsplit(url).path)
    tree = LexborHTMLParser(html)
    h1 = tree.css_first("h1")
    title = " ".join(h1.text().split()) if h1 else ""
    if not m or not title:
        return None
    body = tree.css_first("div.styledText")
    rows = [" ".join(li.text().split()) for li in tree.css("li.border-gray-50")]
    location, mode = location_of(rows)
    return JobStub(
        source="factorial",
        url=url,
        title=title,
        company=name_from_host(board),
        location=location,
        description=strip_html(body.html or "") if body else "",
        ats="factorial",
        apply_url=url,
        remote=mode or remote_from_text(location),
        extra={"board": board, "id": m[1]},
    )


class Factorial(Source):
    """The board is the careers host, whose domain varies by country: `acme.factorial.it`,
    `acme.factorialhr.com.br`."""

    name = "factorial"
    kind = "ats"
    url_patterns = (
        re.compile(
            r"(?<![\w.-])(?!www\.|app\.)([\w-]+\.factorial(?:hr)?\.[a-z]{2,3}(?:\.[a-z]{2})?)\b",
            re.I,
        ),
    )

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        root = f"https://{task.board}/"
        html = (await get_page(http, root)).text
        links: dict[str, None] = {}  # one job can sit under several team sections
        for a in LexborHTMLParser(html).css("a[href]"):
            href = a.attributes.get("href") or ""
            if "/job_posting/" in href:
                links[urljoin(root, href).split("#")[0]] = None
        urls = [u for u in links if _ID.search(urlsplit(u).path)]
        for i in range(start_page * CHUNK, len(urls), CHUNK):
            yield await fetch_all(
                http, urls[i : i + CHUNK], lambda h, u: parse_job(h, u, task.board)
            )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        full = parse_job((await get_page(http, stub.url)).text, stub.url, "")
        return stub.model_copy(update={"description": full.description}) if full else stub
