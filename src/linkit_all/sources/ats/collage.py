"""Collage HR public job-site API (api.collage.co/v1/positions/{board}); the board is the
job-site address of secure.collage.co/jobs/{board}. One response lists every position.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, name_from_slug, safe_date

API = "https://api.collage.co/v1/positions/{board}"


def _date(value: Any) -> Any:
    if isinstance(value, int | float):  # epoch seconds or milliseconds
        return from_epoch_ms(value * 1000 if value < 1e12 else value)
    return safe_date(value)


class Collage(Source):
    name = "collage"
    kind = "ats"
    url_patterns = (
        re.compile(r"secure\.collage\.co/jobs/([^/?#\s\"'<>.]+)", re.I),
        re.compile(r"api\.collage\.co/v1/positions/([^/?#\s\"'<>]+)", re.I),
    )
    parallel = 4

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one response holds every position
            return
        data = await http.get_json(API.format(board=quote(task.board, safe="")))
        rows = data if isinstance(data, list) else (data or {}).get("positions")
        if not isinstance(rows, list):
            raise ValueError("collage: the response carries no positions array")
        company = name_from_slug(task.board)
        stubs = [
            s for r in rows if isinstance(r, dict) and (s := self.stub(r, task.board, company))
        ]
        if stubs:
            yield stubs

    @staticmethod
    def stub(r: dict[str, Any], board: str, company: str) -> JobStub | None:
        title = clean(r.get("title"))
        url = next(
            (u for k in ("hostedUrl", "url", "applyUrl") if (u := str(r.get(k) or "").strip())), ""
        )
        if not title or not url.startswith("https://"):
            return None
        loc = r.get("location")
        where = "; ".join(clean(x) for x in loc if x) if isinstance(loc, list) else clean(loc)
        facts = (
            ("Department", "department"),
            ("Commitment", "commitment"),
            ("Employment type", "employmentType"),
        )
        meta = "\n".join(f"{label}: {clean(r[k])}" for label, k in facts if clean(r.get(k)))
        body = str(r.get("descriptionPlain") or "").strip()
        return JobStub(
            source="collage",
            url=url,
            title=title,
            company=company,
            location=where,
            description="\n\n".join(p for p in (body, meta) if p),
            posted_at=_date(
                next((r[k] for k in ("createdDate", "createdAt", "publishedAt") if r.get(k)), None)
            ),
            ats="collage",
            apply_url=str(r.get("applyUrl") or url),
            remote=remote_from_text(where),
            extra={"board": board, "id": str(r.get("id") or "")},
        )
