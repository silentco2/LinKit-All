"""Orion Group (orionjobs.com), an engineering and life-sciences recruitment agency: its site's
keyless JSON job feed, descriptions included. A single-company plugin (an agency, not an
aggregator). Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.companies._f43 import careers_task
from linkit_all.sources.http import Http

BASE = "https://www.orionjobs.com"
LIST = BASE + "/api/recruitment/job/data/?folder=uk&hasexpired=false&page={page}"
MAX_PAGES = 500


def _value(field: Any) -> str:
    """Orion wraps every field as {"value": ...}."""
    if isinstance(field, list):  # employment_type is a list of such wrappers
        field = field[0] if field else None
    return str((field or {}).get("value") or "").strip() if isinstance(field, dict) else ""


class Orion(Source):
    name = "orion"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = await http.get_json(LIST.format(page=page))
            items = data.get("items") or []
            if not items:
                return
            yield [s for it in items if (s := self.stub(it))]
            if (data.get("pagination") or {}).get("to", 0) >= (data.get("pagination") or {}).get(
                "total", 0
            ):
                return

    def stub(self, it: dict[str, Any]) -> JobStub | None:
        title = _value(it.get("title"))
        if not it.get("id") or not title or not it.get("url"):
            return None
        location = _value(it.get("locationtext"))
        try:
            posted = datetime.strptime(_value(it.get("postdate")), "%d/%m/%Y")
        except ValueError:
            posted = None
        url = BASE + it["url"]
        return JobStub(
            source=self.name,
            url=url,
            apply_url=url,
            title=title,
            company="Orion Group",
            location=location,
            description=strip_html(_value(it.get("description"))),
            posted_at=posted,
            ats=self.name,
            remote=remote_from_text(location),
            extra={"orion_id": it["id"], "employment_type": _value(it.get("employment_type"))},
        )
