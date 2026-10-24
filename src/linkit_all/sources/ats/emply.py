"""Emply (emply.com), a Danish ATS: one keyless JSON vacancy list per career site carries the full
posting. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.sources.ats._f13 import name_from_host, name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import paged, strip_html
from linkit_all.sources.http import Http

PAGE = 100


def host_of(board: str) -> str:
    """A slug is a `.career.emply.com` subdomain; a board with a dot is already a host."""
    board = board.strip().lower()
    return board if "." in board else f"{board}.career.emply.com"


def _translation(v: dict[str, Any]) -> dict[str, Any]:
    """English when the posting has it, else its first language that has a body."""
    withbody = [t for t in v.get("translations") or [] if (t.get("content") or "").strip()]
    english = [t for t in withbody if (t.get("languageKey") or "").lower().startswith("en")]
    chosen: dict[str, Any] = (english or withbody or v.get("translations") or [{}])[0]
    return chosen


class Emply(Source):
    """The board is the tenant slug (`molslinjen`) or a customer career host (`midtjob.dk`)."""

    name = "emply"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.career\.emply\.com", re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = host_of(task.board)
        url = f"https://{host}/api/integration/vacancy/get-page"

        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            # `filters` must be present or the endpoint answers 500.
            body = {"count": PAGE, "offset": offset, "filters": []}
            data = await http.post_json(url, body)
            if not isinstance(data.get("vacancies"), list):
                raise ValueError(f"emply: {host} answered without a vacancies list")
            return data["vacancies"], data.get("count")

        async for items in paged(fetch, PAGE, start_page):
            stubs = [s for v in items if (s := self.stub(v, host, task.board))]
            yield stubs

    @staticmethod
    def stub(v: dict[str, Any], host: str, board: str) -> JobStub | None:
        if v.get("talentPool") or not v.get("shortId"):  # the standing "unsolicited" entry
            return None
        tr = _translation(v)
        title = " ".join((tr.get("title") or v.get("title") or "").split())
        if not title:
            return None
        url = (v.get("externalCseAdLink") or "").strip()
        if not url:
            slug = quote(v.get("titleAsUrl") or "ad")
            url = f"https://{host}/ad/{slug}/{quote(v['shortId'])}"
            lang = (tr.get("languageKey") or "").split("-")[0].lower()
            url += f"/{lang}" if lang else ""
        location = " ".join((v.get("location") or "").split())
        return JobStub(
            source="emply",
            url=url,
            title=title,
            company=name_from_host(host) if "." in board else name_from_slug(board),
            location=location,
            description=strip_html(tr.get("content") or ""),
            posted_at=from_iso(v.get("published")),
            ats="emply",
            apply_url=url,
            remote=remote_from_text(location),
            extra={"board": board, "id": v["shortId"]},
        )
