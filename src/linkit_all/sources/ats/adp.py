"""ADP Workforce Now public career boards (a tenant is a cid + ccId pair). Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import paged
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = (
    "https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/"
    "job-requisitions"
)
PAGE_URL = (
    "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html"
    "?cid={cid}&ccId={cc}&jobId={id}&lang=en_US"
)
PAGE_SIZE = 50


def split_board(board: str) -> tuple[str, str]:
    """ "cid:ccId" (shorthand) or "cid/ccId" (what the URL detector produces)."""
    parts = re.split(r"[:/]", board, maxsplit=1)
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"adp board {board!r} must be cid:ccId")
    return parts[0], parts[1]


class Adp(Source):
    name = "adp"
    kind = "ats"
    url_patterns = (
        re.compile(
            r"workforcenow\.adp\.com/[^\s\"'<>]*?[?&]cid=([\w-]+)&(?:amp;)?ccId=([\w-]+)", re.I
        ),
    )
    parallel = 2  # public JSON API; Http paces per host

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        cid, cc = split_board(task.board)

        async def fetch(skip: int) -> tuple[list[dict[str, Any]], int | None]:
            data = await http.get_json(
                API,
                params={"cid": cid, "ccId": cc, "lang": "en_US", "locale": "en_US",
                        "$top": PAGE_SIZE, "$skip": skip},
            )  # fmt: skip
            return data.get("jobRequisitions") or [], (data.get("meta") or {}).get("totalNumber")

        async for items in paged(fetch, PAGE_SIZE, start_page):
            yield [self.stub(r, cid, cc) for r in items if r.get("itemID")]

    @staticmethod
    def stub(r: dict[str, Any], cid: str, cc: str) -> JobStub:
        url = PAGE_URL.format(cid=cid, cc=cc, id=r["itemID"])
        locations = r.get("requisitionLocations") or []
        location = (
            ((locations[0].get("nameCode") or {}).get("shortName") or "").strip()
            if locations
            else ""
        )
        return JobStub(
            source="adp",
            url=url,
            title=(r.get("requisitionTitle") or "").strip(),
            company=f"ADP {cid}",  # the API names no employer
            location=location,
            description=html_to_text(r.get("requisitionDescription") or "", escaped=True),
            posted_at=from_iso(r.get("postDate")),
            ats="adp",
            apply_url=url,
            remote=remote_from_text(location),
            extra={"board": f"{cid}:{cc}", "id": r["itemID"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        q = parse_qs(urlsplit(stub.url).query)
        try:
            cid, cc, job = q["cid"][0], q["ccId"][0], q["jobId"][0]
        except (KeyError, IndexError):
            return stub
        r = await http.get_json(
            f"{API}/{job}", params={"cid": cid, "ccId": cc, "lang": "en_US", "locale": "en_US"}
        )
        return self.stub({**r, "itemID": job}, cid, cc)
