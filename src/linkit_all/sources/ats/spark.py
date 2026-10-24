"""Spark.work career sites ({workspace}.spark.work): the shared career API takes the workspace in
an X-workspace header and lists each opening with its form fields inline. Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.sources.ats._f13 import mode, name_from_slug
from linkit_all.sources.ats._f16 import when
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

_API = "https://hub.spark.work/api/jobOpenings?pageNumber={}&pageSize={}"
_SIZE = 100
_ACTIVE = 20  # vacancyStatusId: 10 upcoming, 20 active, 30 closed, 40 discarded, 50 expired


class Spark(Source):
    name = "spark"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])(?!hub\.)([\w-]+)\.spark\.work", re.I),)
    cdx_hosts = ("*.spark.work",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        headers = {"X-workspace": task.board}
        for page in range(start_page + 1, 101):
            data = await http.get_json(_API.format(page, _SIZE), headers=headers)
            items = data.get("items") or []
            yield [self._stub(i, task.board) for i in items if i.get("vacancyStatusId") == _ACTIVE]
            if page >= (data.get("pageCount") or page + 1) or len(items) < _SIZE:
                return

    def _stub(self, item: dict[str, Any], board: str) -> JobStub:
        # The form fields are keyed by template-specific ids, so read them by content: the
        # description is the longest value with markup, the workplace the one that names it.
        values = [v for v in (item.get("fields") or {}).values() if isinstance(v, str)]
        body = max((v for v in values if "<" in v), key=len, default="")
        title = " ".join(str(item.get("name") or "").split())
        url = f"https://{board}.spark.work/career/job/{item['id']}/{quote('-'.join(title.split()))}"
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=name_from_slug(board),
            description=strip_html(body),
            posted_at=when(item.get("openDate")),
            ats=self.name,
            apply_url=url,
            remote=next((m for v in values if (m := mode(v))), None),
            extra={"board": board, "id": str(item["id"])},
        )
