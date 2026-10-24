"""HiringThing career sites: every open posting is on the site root, and each posting page
inlines the platform's job record as React props. Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f12 import get_page, name_from_host
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

CHUNK = 20  # posting pages fetched per yielded page
_JOB_PATH = re.compile(r"^/job/(\d+)(?:/|$)")
_RECORD = "HiringThing.Components.ApplyButtonGroup"
_PERIOD = {"hourly": "hour", "monthly": "month", "annually": "year"}  # "weekly" has no interval


def _host(board: str) -> str:
    """A bare tenant slug lives under the vendor's own domain; resellers give the full host."""
    board = board.strip().lower()
    return board if "." in board else f"{board}.hiringthing.com"


def _money(value: Any) -> float | None:
    try:
        return float(((value or {}).get("amount")) or "")
    except ValueError:
        return None


class HiringThing(Source):
    """The board is the careers host: `skijapan.hiringthing.com`, or `skijapan`. The platform is
    white-labelled, so resellers (`crown-shredding-llc.prismhr-hire.com`, ...) serve the same
    application under their own domains; give the full host for those."""

    name = "hiringthing"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])(?!www\.)([\w-]+\.hiringthing\.com)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = _host(task.board)
        base = f"https://{host}/"
        links = self.job_links(base, (await get_page(http, base)).text)
        for i in range(start_page * CHUNK, len(links), CHUNK):
            posts = [await self.posting(http, u, host) for u in links[i : i + CHUNK]]
            yield [p for p in posts if p]

    @staticmethod
    def job_links(base: str, html: str) -> list[str]:
        """Posting permalinks on the board's own host, one per id (a card links its posting
        twice, and the slug is not part of the identity)."""
        found: dict[str, str] = {}
        for a in LexborHTMLParser(html).css("a[href]"):
            url = urljoin(base, a.attributes["href"] or "")
            parts = urlsplit(url)
            m = _JOB_PATH.match(parts.path)
            if m and parts.netloc == urlsplit(base).netloc:  # another host's posting is not ours
                found.setdefault(m[1], url.split("#")[0])
        return list(found.values())

    async def posting(self, http: Http, url: str, host: str) -> JobStub | None:
        if not await http.allowed(url):
            return None
        resp = await http.get(url)
        if resp.status_code in (404, 410):
            return None
        resp.raise_for_status()
        rec = self.record(resp.text)
        if not rec or not rec.get("title"):
            return None
        lo, hi = _money(rec.get("min_salary")), _money(rec.get("max_salary"))
        interval = _PERIOD.get((rec.get("pay_frequency") or "").lower())
        paid = (lo is not None or hi is not None) and interval is not None
        currency = (rec.get("min_salary") or {}).get("currency") or (
            rec.get("max_salary") or {}
        ).get("currency")
        m = _JOB_PATH.match(urlsplit(url).path)
        return JobStub(
            source="hiringthing",
            url=url,
            title=" ".join(rec["title"].split()),
            company=name_from_host(host),
            # Already reads "Remote - Windsor Locks, CT" for a remote posting.
            location=rec.get("location") or "",
            description=html_to_text(rec.get("html_description") or ""),
            posted_at=from_iso(rec.get("posted_at")),
            ats="hiringthing",
            apply_url=url,
            remote="remote" if rec.get("remote") else None,
            salary_min=lo if paid else None,
            salary_max=hi if paid else None,
            salary_currency=currency if paid else None,
            salary_interval=interval if paid else None,
            extra={"board": host, "id": m[1] if m else ""},
        )

    @staticmethod
    def record(html: str) -> dict[str, Any] | None:
        """The job record, found by component name: the page mounts several React components
        and their order varies."""
        node = LexborHTMLParser(html).css_first(f'[data-react-class="{_RECORD}"]')
        try:
            props = json.loads(node.attributes["data-react-props"] or "") if node else None
        except ValueError:
            return None
        table = ((props or {}).get("jobObj") or {}).get("table")
        return table if isinstance(table, dict) else None
