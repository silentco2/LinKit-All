"""HiringRoom ({board}.hiringroom.com), the Latin American ATS: the portal's own pager returns
vacancy cards as an HTML fragment, and the vacancy page holds the description. Logic adapted
from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from selectolax.lexbor import LexborHTMLParser, LexborNode

from linkit_all.sources.ats._f12 import name_from_slug
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

PAGER = "https://{board}.hiringroom.com/jobs/getVacanciesForPortal/{page}"
VACANCY = "https://{board}.hiringroom.com/jobs/get_vacancy/{id}"
MAX_PAGES = 200
_BOARD = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_URL = re.compile(r"//([\w-]+)\.hiringroom\.com/jobs/get_vacancy/([0-9a-f]{24})", re.I)
_PATH = re.compile(r"^/jobs/get_vacancy/([0-9a-f]{24})$")
_TITLE = re.compile(r"^Nuevas oportunidades de empleo: .+ en (.+)$")
_MODALITY: dict[str, Remote] = {"Remoto": "remote", "Híbrido": "hybrid", "Presencial": "onsite"}
# Icon class -> card fact. Each fact is rendered twice (desktop and mobile); the first is read.
_ICONS = {
    "hr-Location-pin": "location",
    "hr-Work-area": "area",
    "hr-Clock": "schedule",
    "hr-Company": "modality",
    "hr-Remote": "modality",
    "hr-Campus": "level",
}


def cards(fragment: str) -> list[dict[str, str]]:
    """The vacancy cards of one pager answer: an <a> to a vacancy wrapping the title and the
    icon-tagged facts."""
    out = []
    for a in LexborHTMLParser(fragment).css("a[href]"):
        m = _PATH.match(a.attributes["href"] or "")
        title = a.css_first(".name__vacancy")
        if not m or title is None or not title.text().strip():
            continue
        card = {"id": m[1], "title": " ".join(title.text().split())}
        for icon in a.css("i"):
            parent = icon.parent
            for cls, fact in _ICONS.items():
                if cls in (icon.attributes.get("class") or "").split() and parent is not None:
                    card.setdefault(fact, " ".join(parent.text().split()))
        out.append(card)
    return out


class HiringRoom(Source):
    """The board is the tenant label: `emblue` for emblue.hiringroom.com."""

    name = "hiringroom"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w-])(?!(?:www|app)\.)([\w-]+)\.hiringroom\.com", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.strip().lower()
        if not _BOARD.match(board):
            raise ValueError(f"hiringroom: {board!r} is not a tenant label")
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            url = PAGER.format(board=board, page=page)
            await http.allowed(url)
            form = {"selectedPage": str(page), "typePortal": "external"}
            resp = await http.post_form(url, form)
            resp.raise_for_status()
            data = resp.json()
            total = (data.get("data") or {}).get("total_vacancies")
            if data.get("result") != "success" or total is None:
                raise ValueError(
                    f"hiringroom: page {page} answered {data.get('result')!r} with no total"
                )
            fresh = [c for c in cards(data["data"].get("htmlContent") or "") if c["id"] not in seen]
            seen.update(c["id"] for c in fresh)
            if page > start_page:
                yield [self.stub(c, board) for c in fresh]
            if len(seen) >= total:
                return
            if not fresh:
                raise ValueError(
                    f"hiringroom: page {page} added no vacancy ({len(seen)} of {total})"
                )

    @staticmethod
    def stub(c: dict[str, str], board: str) -> JobStub:
        url = VACANCY.format(board=board, id=c["id"])
        extra: dict[str, Any] = {
            "board": board,
            "id": c["id"],
            "area": c.get("area"),
            "schedule": c.get("schedule"),
            "level": c.get("level"),
        }
        return JobStub(
            source="hiringroom",
            url=url,
            title=c["title"],
            company=name_from_slug(board),
            location=c.get("location", ""),
            ats="hiringroom",
            apply_url=url,
            remote=_MODALITY.get(c.get("modality", "")),
            extra=extra,
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if not _URL.search(stub.url):
            return stub
        await http.allowed(stub.url)
        resp = await http.get(stub.url)
        if resp.status_code in (404, 410):
            return stub
        resp.raise_for_status()
        tree = LexborHTMLParser(resp.text)
        blocks = []
        for body in tree.css("div.job-description-content"):
            text = html_to_text(body.html or "")
            if not text:
                continue
            prev: LexborNode | None = body.prev
            while prev is not None and prev.tag == "-text":
                prev = prev.prev
            heading = " ".join(prev.text().split()) if prev is not None and prev.tag == "h6" else ""
            blocks.append(f"{heading}\n{text}" if heading else text)
        update: dict[str, Any] = {"description": "\n\n".join(blocks)}
        # "Nuevas oportunidades de empleo: <title> en <company>"
        title = tree.css_first("title")
        if title is not None and (m := _TITLE.match(" ".join(title.text().split()))):
            update["company"] = m[1]
        return stub.model_copy(update=update)
