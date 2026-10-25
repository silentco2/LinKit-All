"""Comeet career sites: the careers page embeds a public read token for the careers API.
Logic adapted from freehire (MIT)."""

import html
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import mode, name_from_slug
from linkit_all.sources.text import html_to_text

PAGE = "https://www.comeet.com/jobs/{board}"
API = "https://www.comeet.co/careers-api/2.0/company/{uid}/positions"
_TOKEN = re.compile(r'"token"\s*:\s*"([A-Za-z0-9]{20,})"')  # long: skips analytics tokens


class Comeet(Source):
    """The board is `<slug>/<companyUID>`, as in `comeet.com/jobs/<slug>/<companyUID>`."""

    name = "comeet"
    kind = "ats"
    url_patterns = (re.compile(r"comeet\.(?:com|co)/jobs/([\w-]+)/([\w.]+\w)", re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        slug, _, uid = task.board.rpartition("/")
        if not slug:
            raise ValueError(f"comeet board {task.board!r} must be '<slug>/<companyUID>'")
        token = _TOKEN.search((await get_page(http, PAGE.format(board=task.board))).text)
        if not token:
            raise ValueError(f"comeet: no API token on the careers page of {task.board}")
        positions = await http.get_json(
            API.format(uid=uid), params={"token": token[1], "details": "true"}
        )
        yield [self.stub(p, task.board, slug) for p in positions if p.get("uid")]

    @staticmethod
    def stub(p: dict[str, Any], board: str, slug: str) -> JobStub:
        loc = p.get("location") or {}
        place = [str(loc.get(k) or "").strip() for k in ("city", "state")]
        location = ", ".join(x for x in place if x) or loc.get("country") or loc.get("name") or ""
        sections = []
        for s in p.get("details") or []:
            if not (s.get("value") or "").strip():
                continue
            if s.get("name") and s["name"].lower() != "description":  # keep the headings
                sections.append(f"<h3>{html.escape(s['name'])}</h3>")
            sections.append(s["value"])
        url = p.get("url_active_page") or f"https://www.comeet.com/jobs/{board}/{p['uid']}"
        return JobStub(
            source="comeet",
            url=url,
            title=p.get("name") or "",
            company=p.get("company_name") or name_from_slug(slug),
            location=str(location).strip(),
            description=html_to_text("".join(sections)),
            posted_at=from_iso(p.get("time_updated")),
            ats="comeet",
            apply_url=url,
            remote=mode(p.get("workplace_type")),
            extra={"board": board, "id": p["uid"]},
        )
