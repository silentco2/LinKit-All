"""Feishu Jobs (飞书招聘) careers sites: a tenant on the shared domain ({tenant}.jobs.feishu.cn) or
ByteDance's own jobs.bytedance.com. The board is the host. Every tenant's front calls the same
keyless search API, 100 postings a page, body and requirements inline. career-ops sends a
faked macOS Chrome user agent to pass a user-agent rule on jobs.bytedance.com; that is
fingerprint spoofing (CLAUDE.md 5.2), so our own agent is sent and a refusal is reported.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, text_of

PAGE = 100
MAX_PAGES = 200


class FeishuJobs(Source):
    name = "feishu-jobs"
    kind = "ats"
    url_patterns = (
        re.compile(r"(?<![\w.-])((?:[a-z0-9-]+\.)jobs\.feishu\.cn|jobs\.bytedance\.com)", re.I),
    )
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = task.board.lower()
        origin = f"https://{host}"
        headers = {"Referer": f"{origin}/", "Origin": origin}
        for page in range(start_page, MAX_PAGES):
            data = await http.post_json(
                f"{origin}/api/v1/search/job/posts",
                {"limit": PAGE, "offset": page * PAGE},
                headers=headers,
            )
            body = (data or {}).get("data") if isinstance(data, dict) else None
            rows = body.get("job_post_list") if isinstance(body, dict) else None
            if not isinstance(body, dict) or not isinstance(rows, list):
                raise ValueError("feishu-jobs: the response carries no job_post_list")
            stubs = [s for r in rows if isinstance(r, dict) and (s := self.stub(r, host))]
            if stubs:
                yield stubs
            total = int(body.get("count") or 0)
            if len(rows) < PAGE or (page + 1) * PAGE >= total:
                return

    @staticmethod
    def stub(r: dict[str, Any], host: str) -> JobStub | None:
        title, jid = clean(r.get("title")), str(r.get("id") or "").strip()
        if not (title and jid):
            return None
        route = "experienced" if host == "jobs.bytedance.com" else "index"
        url = f"https://{host}/{route}/position/{quote(jid, safe='')}/detail"
        cities = [clean(c.get("name")) for c in r.get("city_list") or [] if isinstance(c, dict)]
        category = clean((r.get("job_category") or {}).get("name"))
        kind = clean((r.get("recruit_type") or {}).get("name"))
        parts = [
            f"Category: {category}" if category else "",
            f"Type: {kind}" if kind else "",
            text_of(r.get("description")),
            text_of(r.get("requirement")),
        ]
        stamp = r.get("publish_time")
        company = "ByteDance" if host == "jobs.bytedance.com" else host.split(".")[0]
        return JobStub(
            source="feishu-jobs",
            url=url,
            title=title,
            company=company,
            location="/".join(c for c in cities if c),
            description="\n".join(p for p in parts if p),
            posted_at=from_epoch_ms(stamp)
            if isinstance(stamp, int | float) and stamp > 0
            else None,
            ats="feishu-jobs",
            apply_url=url,
            extra={"board": host, "id": jid},
        )
