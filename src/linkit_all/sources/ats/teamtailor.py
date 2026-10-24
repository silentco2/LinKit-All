"""Teamtailor career sites (board = the careers host, e.g. "jobs.acme.com"): the /jobs listing
links every posting, each page carries a schema.org JobPosting and jobs.rss states the workplace
type. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from lxml import etree

from linkit_all.sources.ats._f13 import name_from_host
from linkit_all.sources.ats._f15 import fetch_html, paged_postings, posting_stub
from linkit_all.sources.ats._f16 import GONE, links
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.http import Http

_ID = re.compile(r"/jobs/(\d+)")
_MAX_PAGES = 1000
_FEED_SIZE = 500
_FEED_PAGES = 20
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
# The feed's <remoteStatus> enum; "none" (nobody set it) and "temporary" state no arrangement.
_STATUS: dict[str, Remote] = {"fully": "remote", "hybrid": "hybrid", "onsite": "onsite"}


class Teamtailor(Source):
    name = "teamtailor"
    kind = "ats"
    url_patterns = (
        re.compile(r"([\w-]+\.teamtailor\.com)", re.I),
        re.compile(r"([\w.-]+)/jobs/\d{5,}-[\w%-]+", re.I),  # a custom careers domain
    )
    cdx_hosts = ("*.teamtailor.com",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = task.board.lower()
        urls = await self._urls(http, host)
        modes = await self._modes(http, host, urls)

        async def build(url: str) -> JobStub | None:
            html, m = await fetch_html(http, url), _ID.search(url)
            if html is None or m is None:
                return None
            stub = posting_stub(
                html, source=self.name, url=url, board=host, id=m[1], company=name_from_host(host)
            )
            mode = modes.get(m[1])
            return stub.model_copy(update={"remote": mode}) if stub and mode else stub

        async for stubs in paged_postings(urls, start_page, build):
            yield stubs

    async def _urls(self, http: Http, host: str) -> list[str]:
        """Every posting URL: /jobs?page=N until a page links nothing new. A few sites disable
        /jobs and list on the site root, so a missing first page falls back to that."""
        path, found = "jobs", dict[str, None]()
        for page in range(1, _MAX_PAGES + 1):
            url = f"https://{host}/{path}?page={page}"
            html = await fetch_html(http, url)
            if html is None and page == 1 and path:
                path, url = "", f"https://{host}/?page=1"
                html = await fetch_html(http, url)
            if html is None:
                break
            fresh = [u for u in links(html, url, lambda h: bool(_ID.search(h))) if u not in found]
            # ponytail: a page of only known links ends the walk (a site that ignores ?page)
            if not fresh:
                break
            found.update(dict.fromkeys(fresh))
        return list(found)

    async def _modes(self, http: Http, host: str, urls: list[str]) -> dict[str, Remote]:
        """Workplace type by posting id from jobs.rss. The page states it only in the site's own
        language; best effort: a feed that fails leaves the postings to their pages."""
        want = {m[1] for u in urls if (m := _ID.search(u))}
        out: dict[str, Remote] = {}
        for page in range(_FEED_PAGES):
            if not want:
                break
            try:
                resp = await http.get(
                    f"https://{host}/jobs.rss?offset={page * _FEED_SIZE}&per_page={_FEED_SIZE}"
                )
                resp.raise_for_status()
                items = etree.fromstring(resp.content, _PARSER).findall("channel/item")
            except (*GONE, etree.XMLSyntaxError):
                break
            for item in items:
                m = _ID.search(item.findtext("link") or "")
                status = next(
                    (
                        (c.text or "").strip()
                        for c in item
                        if isinstance(c.tag, str) and etree.QName(c).localname == "remoteStatus"
                    ),
                    "",
                )
                if m and m[1] in want and status:
                    want.discard(m[1])
                    if status in _STATUS:
                        out[m[1]] = _STATUS[status]
            if len(items) < _FEED_SIZE:
                break
        return out
