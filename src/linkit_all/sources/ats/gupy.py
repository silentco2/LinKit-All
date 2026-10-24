"""Gupy career pages ({board}.gupy.io), the Brazilian ATS: a public listing plus one JSON
detail per posting. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f12 import mode, name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

LIST = "https://private-api.gupy.io/job-publication/public/jobs?subdomain={board}"
DETAIL = "https://private-api.gupy.io/job-publication/public/jobs/{id}"
_URL = re.compile(r"//([\w-]+)\.gupy\.io/jobs/(\d+)", re.I)
# Gupy's own hosts are not career pages.
_HOST = r"(?<![\w-])(?!(?:private-api|employability-portal|portal|www)\.)([\w-]+)\.gupy\.io"
_SECTIONS = ("description", "responsibilities", "prerequisites", "relevantExperiences")


class Gupy(Source):
    """The board is the career-page subdomain: `caju` for caju.gupy.io."""

    name = "gupy"
    kind = "ats"
    url_patterns = (re.compile(_HOST, re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one unpaginated answer
            return
        data = await http.get_json(LIST.format(board=task.board.lower()))
        yield [self.stub(p, task.board.lower()) for p in data.get("data") or [] if p.get("id")]

    @staticmethod
    def stub(p: dict[str, Any], board: str) -> JobStub:
        place = (p.get("addressCity"), p.get("addressStateShortName"), p.get("addressCountry"))
        url = f"https://{board}.gupy.io/jobs/{p['id']}"
        return JobStub(
            source="gupy",
            url=url,
            title=" ".join((p.get("name") or "").split()),
            company=name_from_slug(board),
            location=", ".join(x.strip() for x in place if x and x.strip()),
            ats="gupy",
            apply_url=url,
            remote=mode(p.get("workplaceType")) or ("remote" if p.get("remoteWorking") else None),
            extra={"board": board, "id": str(p["id"]), "department": p.get("departmentName")},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m:
            return stub
        resp = await http.get(DETAIL.format(id=m[2]))
        if resp.status_code in (404, 410):  # Gupy's own "vaga inexistente"
            return stub
        resp.raise_for_status()
        d = resp.json()
        # A section holding only "<p>.</p>" or "&nbsp;" is a placeholder, not text.
        parts = [t for k in _SECTIONS if re.search(r"\w", t := html_to_text(d.get(k) or ""))]
        update: dict[str, Any] = {"description": "\n\n".join(parts)}
        if posted := from_iso(d.get("publishedAt")):
            update["posted_at"] = posted
        return stub.model_copy(update=update)
