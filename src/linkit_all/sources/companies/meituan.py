"""Meituan careers (zhaopin.meituan.com): the site's own JSON search, restricted to its technology
job family, one pass per hire type. A single-company plugin, not an ATS. Logic adapted from
freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import distinct
from linkit_all.sources.tasks import careers_task

SEARCH = "https://zhaopin.meituan.com/api/official/job/getJobList"
JOB = "https://zhaopin.meituan.com/web/position/detail?jobUnionId="
TECH_FAMILY = "11001"
TECH_FAMILY_NAME = "技术类"
PAGE = 500
MAX_PAGES = 20
# (jobType code, label): 社招 experienced hires, 校招 campus graduates, 实习 interns. One page of
# stubs per hire type, so `start_page` resumes at the next type.
HIRE_TYPES = (("3", "experienced"), ("1", "campus"), ("2", "intern"))


class Meituan(Source):
    name = "meituan"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for code, label in HIRE_TYPES[start_page:]:
            posts = await self._walk(http, code, task.query)
            yield [s for p in posts if (s := self.stub(p, label))]

    @staticmethod
    async def _walk(http: Http, job_type: str, keywords: str) -> list[dict[str, Any]]:
        posts: dict[str, dict[str, Any]] = {}
        for page in range(1, MAX_PAGES + 1):
            body = {
                "page": {"pageNo": page, "pageSize": PAGE},
                "keywords": keywords,
                "jobShareType": "1",
                "jobType": [{"code": job_type, "subCode": []}],
                "cityList": [],
                "department": [],
                "jfJgList": [{"code": TECH_FAMILY, "subCode": []}],
                "typeCode": [],
                "specialCode": [],
            }
            r = await http.post_json(SEARCH, body)
            data = r.get("data") or {}
            total = (data.get("page") or {}).get("totalCount") if r.get("status") == 1 else None
            if total is None:
                raise ValueError(f"meituan: bad answer for page {page}: {r.get('message')!r}")
            batch = data.get("list") or []
            for p in batch:
                if p.get("jobUnionId") and p.get("jobFamily") == TECH_FAMILY_NAME:
                    posts[p["jobUnionId"]] = p
            if not batch or len(posts) >= total:
                break
        return list(posts.values())

    def stub(self, p: dict[str, Any], hire_type: str) -> JobStub | None:
        title = " ".join(str(p.get("name") or "").split())
        if not title:
            return None
        parts = (p.get("jobDuty"), p.get("jobRequirement"), p.get("highLight"))
        url = JOB + p["jobUnionId"]
        return JobStub(
            source=self.name,
            url=url,
            apply_url=url,
            title=title,
            company="Meituan",
            location=distinct([c.get("name") for c in p.get("cityList") or []], ", "),
            description="\n\n".join(x.strip() for x in parts if x and x.strip()),
            posted_at=from_epoch_ms(p.get("refreshTime")),
            ats=self.name,
            extra={"meituan_id": p["jobUnionId"], "hire_type": hire_type},
        )
