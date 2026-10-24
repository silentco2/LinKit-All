"""Tenstreet "Pulse" share pages (US trucking and logistics carriers; board = the numeric company
id): the carrier's profile links every open posting and each posting page embeds it as a JSON array,
one row per hiring location. Logic adapted from freehire (MIT)."""

import html as htmllib
import json
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f15 import fetch_html
from linkit_all.sources.ats._f17 import hydrate, text_of
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

_HOST = "https://pulse.tenstreet.com"
_LINK = re.compile(r"share_app_show_active_jobs\.php\?([^'\"\s]+)")
_ARRAY = "var active_job_array = "
_STATE = re.compile(r"^[A-Z]{2}$")


def posting_url(company: str, posting: str) -> str:
    """portal_user_id=1 is needed: without it the page answers an empty posting."""
    return (
        f"{_HOST}/share_app_show_active_jobs.php"
        f"?active_job_id={posting}&company_id={company}&portal_user_id=1"
    )


def listing(page: str, company: str) -> tuple[str, list[str]]:
    """(carrier name, posting ids) of a Pulse profile. Only links naming this company count: a
    posting page is company-scoped, so another carrier's id is not a posting of this board."""
    tree = LexborHTMLParser(page)
    name = text_of(tree.css_first("#carrier_detail_company_name"))
    ids: dict[str, None] = {}
    for m in _LINK.finditer(page):
        query = parse_qs(htmllib.unescape(m[1]))
        posting = (query.get("active_job_id") or [""])[0]
        if query.get("company_id") == [company] and posting.isdigit():
            ids[posting] = None
    return name, list(ids)


def rows(page: str) -> list[dict[str, Any]]:
    """The posting's rows from the inline script; empty for `null` (closed posting)."""
    start = page.find(_ARRAY)
    if start < 0:
        return []
    try:
        found, _ = json.JSONDecoder().raw_decode(page[start + len(_ARRAY) :])
    except ValueError:
        return []
    return [r for r in found if isinstance(r, dict)] if isinstance(found, list) else []


def _text(markup: Any) -> str:
    return html_to_text(str(markup or ""))


class Tenstreet(Source):
    name = "tenstreet"
    kind = "ats"
    url_patterns = (
        re.compile(r"pulse\.tenstreet\.com/share_app_\w+\.php\?[^\s\"']*?company_id=(\d+)"),
    )
    cdx_hosts = ("pulse.tenstreet.com/*",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.strip()
        if not board.isdigit():
            raise Unsupported(f"tenstreet: board {task.board!r} is not a numeric company id")
        page = await fetch_html(http, f"{_HOST}/share_app_index.php?company_id={board}")
        name, ids = listing(page or "", board)
        if not name:  # an unknown id answers 200 with an empty profile
            raise Unsupported(f"tenstreet: company {board} has no public profile")

        async def build(posting: str) -> JobStub | None:
            url = posting_url(board, posting)
            found = await fetch_html(http, url)
            return self._stub(rows(found or ""), posting, url, board, name)

        async for stubs in hydrate(ids, start_page, build, 4):
            yield stubs

    def _stub(
        self, found: list[dict[str, Any]], posting: str, url: str, board: str, company: str
    ) -> JobStub | None:
        # a closed posting answers an empty array, a mismatch is another posting's page
        if not found or str(found[0].get("active_job_id")) != posting:
            return None
        first = found[0]
        title = " ".join(str(first.get("job_title") or "").split())
        if not title:
            return None
        body = [_text(first.get("job_description"))]
        if req := _text(first.get("job_requirements")):  # often an empty placeholder
            body.append(f"Requirements\n{req}")
        if pay := " ".join(str(first.get("job_pay") or "").split()):
            body.append(f"Pay\n{pay}")
        states: dict[str, None] = {}
        for r in found:
            code = r.get("value") if r.get("location_type") == "select_states" else r.get("state")
            code = str(code or "").strip().upper()
            if _STATE.match(code):
                states[code] = None
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=f"{', '.join(states)}, US" if states else "",
            description="\n\n".join(b for b in body if b),
            ats=self.name,
            apply_url=url,
            extra={"board": board, "id": posting},
        )
