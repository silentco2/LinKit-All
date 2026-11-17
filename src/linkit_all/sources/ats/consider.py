"""Consider (consider.com) VC portfolio job boards, served from each fund's own host
(jobs.<fund>.com). Add one as "consider:jobs.acme-ventures.com"; no address pattern finds a
fund's own host. The board page's server state carries the board id and a CSRF token (with the
session cookie the client keeps); the page's own search POST then lists jobs 500 at a time,
with a cursor for the next page. `url` is the employer's own ATS link when given.
Logic adapted from career-ops (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import ats_of, clean, safe_date

SIZE = 500
MAX_PAGES = 100
_STATE = re.compile(r"window\.serverInitialData\s*=\s*(\{.*?\})\s*;?\s*(?:</script>|$)", re.M)


def server_state(html: str) -> dict[str, Any]:
    m = _STATE.search(html)
    try:
        data = json.loads(m[1]) if m else None
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _stamp(value: Any) -> Any:
    if isinstance(value, int | float):  # epoch ms on some boards, ISO on others
        return from_epoch_ms(value) if value > 0 else None
    return safe_date(value)


class Consider(Source):
    name = "consider"
    kind = "ats"
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = task.board.removeprefix("https://").removeprefix("http://").split("/")[0].lower()
        origin = f"https://{host}"
        state = server_state((await get_page(http, f"{origin}/jobs")).text)
        board: dict[str, Any] = state["board"] if isinstance(state.get("board"), dict) else {}
        board_id = str(board.get("id") or "").strip()
        if not board_id:
            raise ValueError(f"consider: no board id on {origin}/jobs")
        token = state.get("csrfToken")
        headers = {"Referer": f"{origin}/jobs", "Accept": "application/json"}
        if isinstance(token, str) and len(token) >= 8:
            headers["X-CSRF-Token"] = token
        parent = board.get("isParent") if isinstance(board.get("isParent"), bool) else True
        sequence: Any = None
        for page in range(MAX_PAGES):
            meta: dict[str, Any] = {"size": SIZE, **({"sequence": sequence} if sequence else {})}
            body = {
                "meta": meta,
                "board": {"id": board_id, "isParent": parent},
                "query": {"promoteFeatured": True},
            }
            data = await http.post_json(f"{origin}/api-boards/search-jobs", body, headers=headers)
            rows = data.get("jobs") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError("consider: the response carries no jobs array")
            if page >= start_page:  # the cursor makes a resumed run re-walk the earlier pages
                yield [s for r in rows if isinstance(r, dict) and (s := self.stub(r, host))]
            sequence = (data.get("meta") or {}).get("sequence")
            if len(rows) < SIZE or not sequence:
                return

    @staticmethod
    def stub(r: dict[str, Any], host: str) -> JobStub | None:
        title, company = clean(r.get("title")), clean(r.get("companyName"))
        url = str(r.get("url") or r.get("applyUrl") or "").strip()
        if not (title and company and url.startswith("http")):
            return None
        places = [p for p in r.get("locations") or [] if isinstance(p, str)] or [
            str(p.get("label") or p.get("value") or "")
            for p in r.get("normalizedLocations") or []
            if isinstance(p, dict)
        ]
        where = ", ".join(p for p in places if p) or ("Remote" if r.get("remote") else "")
        return JobStub(
            source="consider",
            url=url,
            title=title,
            company=company,
            location=where,
            posted_at=_stamp(r.get("timeStamp")),
            ats=ats_of(url, "consider"),
            apply_url=str(r.get("applyUrl") or url),
            remote="remote" if r.get("remote") is True else remote_from_text(where),
            extra={"board": host, "id": url},
        )
