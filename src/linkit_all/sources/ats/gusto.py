"""Gusto Hiring (jobs.gusto.com), the hosted job board of Gusto payroll customers: a paged,
server-rendered listing and a posting page with the body. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser, LexborNode

from linkit_all.sources.ats._f12 import get_page, name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

BASE = "https://jobs.gusto.com"
MAX_PAGES = 40  # 25 postings a page and the largest board has 35: a loop guard only
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_POSTING = re.compile(rf"/postings/[^/?#]+-({_UUID})$", re.I)
_BOARD_UUID = re.compile(rf"-{_UUID}(?:\.\w+)?$", re.I)
_PAY = re.compile(r"^\$([\d,]+(?:\.\d+)?) - \$([\d,]+(?:\.\d+)?) per ([a-z]+)$")
_PERIODS = {"hour", "day", "month", "year"}  # "per week" has no interval to state it in


def _text(node: LexborNode) -> str:
    return " ".join(node.text().split())


class Gusto(Source):
    """The board is the whole board path segment, `<company-slug>-<company-uuid>`, as in
    jobs.gusto.com/boards/grupo-ei-el-paso-7feb4b68-5288-41cc-b169-f56b3ec26120: neither
    half alone resolves. A renamed employer keeps its old slug resolving against the same
    uuid, so list each company once."""

    name = "gusto"
    kind = "ats"
    url_patterns = (re.compile(r"jobs\.gusto\.com/boards/([\w-]+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            html = (await get_page(http, f"{BASE}/boards/{board}?page={page}")).text
            tree = LexborHTMLParser(html)
            heading = tree.css_first("h1")  # the employer's name leads the first page
            company = (_text(heading) if heading else "") or name_from_slug(
                _BOARD_UUID.sub("", board)
            )
            stubs = [s for a in tree.css("a[href]") if (s := self.stub(a, board, company))]
            fresh = [s for s in stubs if s.extra["id"] not in seen]
            if not stubs:  # an empty page ("no open positions currently"): the end
                return
            seen.update(s.extra["id"] for s in fresh)
            yield fresh

    @staticmethod
    def stub(a: LexborNode, board: str, company: str) -> JobStub | None:
        href = a.attributes.get("href") or ""
        m = _POSTING.search(href.split("?")[0].split("#")[0])
        title = a.css_first("h3")
        if not m or title is None:
            return None
        paras = [_text(p) for p in a.css("p")]
        # The second line is "<pay> · <employment type>", the pay half missing when none is stated.
        parts = [p.strip() for p in (paras[1] if len(paras) > 1 else "").split("·")]
        pay = _PAY.match(parts[-2]) if len(parts) > 1 else None
        interval = pay[3] if pay and pay[3] in _PERIODS else None
        url = urljoin(BASE, href.split("?")[0].split("#")[0])
        location = paras[0] if paras else ""
        return JobStub(
            source="gusto",
            url=url,
            title=_text(title),
            company=company,
            location=location,
            ats="gusto",
            apply_url=url,
            remote=remote_from_text(location),
            salary_min=float(pay[1].replace(",", "")) if interval and pay else None,
            salary_max=float(pay[2].replace(",", "")) if interval and pay else None,
            salary_currency="USD" if interval else None,  # Gusto Payroll serves US employers only
            salary_interval=interval,
            extra={"board": board, "id": m[1], "employment": parts[-1] or None},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if not _POSTING.search(stub.url) or not await http.allowed(stub.url):
            return stub
        resp = await http.get(stub.url)
        if resp.status_code in (404, 410):
            return stub
        resp.raise_for_status()
        tree = LexborHTMLParser(resp.text)
        blocks = []
        # The unheaded pitch right after the <h1>, then the "Description" section. The
        # "About <employer>" section between them is about the company, not the role.
        h1 = tree.css_first("h1")
        pitch = h1.next if h1 else None
        while pitch is not None and pitch.tag == "-text":
            pitch = pitch.next
        if pitch is not None and not pitch.css_first("h3, h4"):
            blocks.append(html_to_text(pitch.html or ""))
        for head in tree.css("h3, h4"):
            rich = head.parent.css_first(".rich-text-container") if head.parent else None
            if _text(head) == "Description" and rich is not None:
                blocks.append(html_to_text(rich.html or ""))
                break
        text = "\n\n".join(b for b in blocks if b)
        return stub.model_copy(update={"description": text}) if text else stub
