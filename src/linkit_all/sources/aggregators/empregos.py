"""Empregos.com.br, a general Brazilian job board. Its search API (the one the site's pages call)
answers whole postings, body included, so no posting page is requested.
Logic adapted from freehire (MIT)."""

import html
from collections.abc import AsyncIterator
from math import ceil
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import query_tasks
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

SEARCH = "https://gatewayb2c.empregos.com.br/searchjob/v2/elastic/search"
POSTING = "https://www.empregos.com.br/vaga/"
PAGE = 100
HIDDEN = {"confidencial", "empresa confidencial"}  # the board's label for a hidden employer
MODES: dict[str, Remote] = {"Presencial": "onsite", "Remoto": "remote", "Híbrido": "hybrid"}
SECTIONS = (  # (field, heading) appended after the description
    ("requiredQualification", "Requisitos"),
    ("academicFormation", "Formação"),
    ("workTime", "Horário"),
)


def _text(value: str | None) -> str:
    """HTML on most postings; newline text with HTML entities on the rest."""
    value = value or ""
    return strip_html(value) if "<" in value else html.unescape(value).replace("\xa0", " ").strip()


class Empregos(Source):
    name = "empregos"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg, locations=False)  # Brazil only; no place filter

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page, ceil(task.limit / PAGE)):
            body = {"keyword": task.query, "filters": [], "page": page, "size": PAGE,
                    "order": 0, "distance": 100}  # fmt: skip
            data = await http.post_json(SEARCH, body)
            rows = data.get("jobPostingCollection") or []
            stubs = [s for r in rows if (s := self.stub(r))]
            if stubs:
                yield stubs
            if len(rows) < PAGE or (page + 1) * PAGE >= data.get("total", 0):
                return

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        company = ((p.get("company") or {}).get("name") or "").strip()
        ref = p.get("referenceId")
        if not ref or not p.get("title") or not company or company.lower() in HIDDEN:
            return None
        places = dict.fromkeys(
            ", ".join(x for x in (loc.get("city"), loc.get("stateAbbreviation")) if x and x.strip())
            for loc in p.get("location") or []
        )
        parts = [_text(p.get("description"))]
        for field, heading in SECTIONS:
            if text := _text(p.get(field)):
                parts.append(f"{heading}:\n{text}")
        created = p.get("createdAt") or ""
        return JobStub(
            source=self.name,
            url=f"{POSTING}{ref}",
            title=p["title"].strip(),
            company=company,
            location="; ".join(x for x in places if x),
            description="\n\n".join(x for x in parts if x),
            posted_at=from_iso(f"{created}-03:00") if created else None,  # Brasilia time, no offset
            apply_url=f"{POSTING}{ref}",
            remote=MODES.get(p.get("workplaceTypes") or ""),
            extra={"id": ref},
        )
