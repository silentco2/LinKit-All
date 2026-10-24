"""Eploy (eploy.net), a UK ATS: the site's /live-jobs.xml sitemap lists every live vacancy, and
each vacancy page carries the title, body and often a JobPosting block. Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f13 import fetch_all, get_page, name_from_host, sitemap_locs
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings

CHUNK = 15  # vacancy pages read together per page of stubs
_PATH = re.compile(r"^/vacancies/(\d+)/[^/]+\.html$")


def parse_vacancy(html: str, url: str, board: str) -> JobStub | None:
    tree = LexborHTMLParser(html)
    h1 = tree.css_first('h1[id$="h1JobTitle"]')
    body = tree.css_first("div.vac-details__description")
    title = " ".join(h1.text().split()) if h1 else ""
    description = strip_html(body.html or "") if body else ""
    if not title or not description:  # e.g. the "Vacancy not found" page answered with 200
        return None
    posting = (job_postings(html) or [{}])[0]
    addr = (posting.get("jobLocation") or {}).get("address") or {}
    place = [str(addr.get(k) or "").strip() for k in ("addressLocality", "addressRegion")]
    place.append(str(addr.get("addressCountry") or "").strip())
    org = posting.get("hiringOrganization") or {}
    return JobStub(
        source="eploy",
        url=url,
        title=title,
        company=(org.get("name") or "").strip() or name_from_host(board),
        location=", ".join(p for p in place if p),
        description=description,
        posted_at=from_iso(posting.get("datePosted")) if posting.get("datePosted") else None,
        ats="eploy",
        apply_url=url,
        extra={"board": board, "id": _PATH.match(urlsplit(url).path)[1]},  # type: ignore[index]
    )


class Eploy(Source):
    """The board is the careers host: `acme.eploy.net`, or a branded domain (`jobs.ocs.com`)."""

    name = "eploy"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])(?!www\.)([\w-]+\.eploy\.net)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = task.board.strip().lower()
        if "." not in host or re.search(r"[/:?#@\s]", host):
            raise ValueError(f"eploy: board {task.board!r} is not a careers host")
        xml = (await get_page(http, f"https://{host}/live-jobs.xml")).text
        if "<sitemapindex" in xml:
            raise ValueError(f"eploy: {host}/live-jobs.xml is a sitemap index")
        urls: dict[str, str] = {}  # vacancy id -> url; a branded site may list its eploy.net twin
        for loc in sitemap_locs(xml):
            parts = urlsplit(loc)
            m = _PATH.match(parts.path)
            h = (parts.hostname or "").lower()
            if parts.scheme == "https" and m and (h == host or h.endswith(".eploy.net")):
                urls.setdefault(m[1], loc)
        todo = list(urls.values())
        for i in range(start_page * CHUNK, len(todo), CHUNK):
            yield await fetch_all(http, todo[i : i + CHUNK], lambda h, u: parse_vacancy(h, u, host))

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        host = urlsplit(stub.url).hostname or ""
        full = parse_vacancy((await get_page(http, stub.url)).text, stub.url, host)
        return stub.model_copy(update={"description": full.description}) if full else stub
