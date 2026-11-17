"""Eightfold AI career sites ({tenant}.eightfold.ai/careers). The board is the tenant, or
"tenant/domain" when the careers URL names a `domain` (multi-brand tenants scope by it). The
public jobs API serves 10 rows a page whatever is asked. A tenant moved to the newer "PCSX" API
answers the old one 403; the walk then reads PCSX, which names a few fields differently. The
list has no body: `fetch_details` reads the posting's own record.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.common import absolute, json_or_none, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, distinct, name_from_slug

V2 = "https://{host}/api/apply/v2/jobs"
PCSX = "https://{host}/api/pcsx/search"
PAGE = 10  # server cap
MAX_PAGES = 1000


def _parts(board: str) -> tuple[str, str]:
    tenant, _, domain = board.partition("/")
    return f"{tenant}.eightfold.ai", domain


class Eightfold(Source):
    name = "eightfold"
    kind = "ats"
    url_patterns = (
        re.compile(
            r"(?<![\w-])([a-z0-9-]+)\.eightfold\.ai/careers[^\s\"'<>]*?[?&]domain=([\w.-]+)", re.I
        ),
        re.compile(r"(?<![\w-])(?!www\.)([a-z0-9-]+)\.eightfold\.ai", re.I),
    )
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host, domain = _parts(task.board)
        params: dict[str, Any] = {"domain": domain} if domain else {}
        pcsx = False
        for page in range(start_page, MAX_PAGES):
            query = {**params, "start": page * PAGE, "num": PAGE}
            data: Any = None
            if not pcsx:
                resp = await http.get(V2.format(host=host), params=query)
                if resp.status_code == 403:
                    pcsx = True
                else:
                    resp.raise_for_status()
                    data = resp.json()
            if pcsx:
                body = await http.get_json(PCSX.format(host=host), params=query)
                data = body.get("data") if isinstance(body, dict) else None
            rows = data.get("positions") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError("eightfold: the response carries no positions array")
            if not rows:
                return
            yield [s for r in rows if isinstance(r, dict) and (s := self.stub(r, task.board))]
            total = data.get("count")
            if isinstance(total, int) and (page + 1) * PAGE >= total:
                return

    @staticmethod
    def stub(r: dict[str, Any], board: str) -> JobStub | None:
        host, domain = _parts(board)
        title = clean(r.get("name")) or clean(r.get("posting_name"))
        pid = str(r.get("id") or r.get("position_id") or "").strip()
        url = absolute(r.get("canonicalPositionUrl") or r.get("positionUrl"), f"https://{host}/")
        if not url and pid:
            url = f"https://{host}/careers?pid={quote(pid, safe='')}" + (
                f"&domain={domain}" if domain else ""
            )
        if not title or not url:
            return None
        places = [r.get("location"), *(r.get("locations") or [])]
        where = distinct([p for p in places if isinstance(p, str)])
        posted = next(
            (
                v
                for k in ("t_create", "postedTs", "creationTs", "t_update")
                if isinstance(v := r.get(k), int | float) and v > 0
            ),
            None,
        )
        return JobStub(
            source="eightfold",
            url=url,
            title=title,
            company=name_from_slug(board.split("/")[0]),
            location=where,
            description=strip_html(r.get("job_description") or ""),
            posted_at=from_epoch_ms(posted * 1000) if posted else None,
            ats="eightfold",
            apply_url=url,
            remote=remote_from_text(where),
            extra={
                "board": board,
                "id": pid,
                "req": r.get("ats_job_id") or r.get("atsJobId") or r.get("display_job_id"),
            },
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        parts = urlsplit(stub.url)
        pid = stub.extra.get("id") or (parse_qs(parts.query).get("pid") or [""])[0]
        if stub.description or not pid or not (parts.hostname or "").endswith(".eightfold.ai"):
            return stub
        domain = parse_qs(parts.query).get("domain")
        data = await json_or_none(
            http,
            f"{V2.format(host=parts.hostname)}/{quote(str(pid), safe='')}",
            params={"domain": domain[0]} if domain else {},
        )
        body = (
            strip_html((data or {}).get("job_description") or "") if isinstance(data, dict) else ""
        )
        return stub.model_copy(update={"description": body}) if body else stub
