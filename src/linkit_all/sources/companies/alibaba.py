"""Alibaba Group's experienced-hire portal (talent.alibaba.com): one search lists every Alibaba
business; read here through its Technology category. The search POST uses the site's own
double-submit XSRF check (a made-up token sent as cookie and header, as the page's script does),
which is not a bot challenge. Chinese-language postings, body inline. Single-company plugin.
Logic adapted from freehire (MIT)."""

import secrets
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.common import paged
from linkit_all.sources.companies._f41 import ats_of, fresh
from linkit_all.sources.http import Http

SEARCH = "https://talent.alibaba.com/position/search"
# talent.alibaba.com sends every deep link to its home page; the holding site renders any id.
JOB = "https://talent-holding.alibaba.com/off-campus/position-detail?lang=zh&positionId="
PAGE = 500  # the search's own ceiling: a larger pageSize still serves 500 rows
# Sub-category codes under 技术类 (Technology); the parent code alone matches almost nothing.
TECH = "133,135,136,137,407,408,409,410,411,511,702,703,704,747,764,769,798,811"


class Alibaba(Source):
    name = "alibaba"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        # Titles are Chinese, so a search query would match little: list the category, let our
        # matching filter it.
        return [Task(self.name, "alibaba:tech")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        token = secrets.token_hex(16)
        headers = {"Cookie": f"XSRF-TOKEN={token}", "X-XSRF-TOKEN": token}
        seen: set[str] = set()

        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            body = {
                "channel": "group_official_site",
                "language": "zh",
                "batchId": "",
                "categories": "",
                "deptCodes": [],
                "key": "",
                "pageIndex": offset // PAGE + 1,
                "pageSize": PAGE,
                "regions": "",
                "subCategories": TECH,
            }
            data = await http.post_json(SEARCH, body, headers=headers)
            if not data.get("success") or not isinstance(data.get("content"), dict):
                raise RuntimeError(f"alibaba search failed: {data.get('errorMsg')}")
            return data["content"].get("datas") or [], data["content"].get("totalCount")

        async for rows in paged(fetch, PAGE, start_page):
            page = fresh((self.stub(r) for r in rows), seen)
            yield page

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        title = " ".join(str(p.get("name") or "").split())
        body = "\n\n".join(str(p.get(k) or "").strip() for k in ("description", "requirement"))
        if not p.get("id") or not title or not body.strip():
            return None
        url = JOB + str(p["id"])
        location = "; ".join(str(x) for x in p.get("workLocations") or [])
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="Alibaba Group",
            location=location,
            description=body.strip(),
            posted_at=from_epoch_ms(p.get("publishTime")),
            ats=ats_of(url, self.name),
            apply_url=url,
            remote=remote_from_text(title, location),
            extra={"id": str(p["id"])},
        )
