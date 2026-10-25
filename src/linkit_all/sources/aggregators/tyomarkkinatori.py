"""Job Market Finland (tyomarkkinatori.fi), the Finnish national job portal. The search API caps
deep paging, so it is read one region at a time, newest first; each posting's body comes from its
detail endpoint (`fetch_details`). Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import all_older, feed_task

SEARCH = "https://tyomarkkinatori.fi/api/jobpostingfulltext/search/v2/search"
DETAIL = "https://tyomarkkinatori.fi/api/jobposting-new/v1/public/jobpostings/{}"
JOB_URL = "https://tyomarkkinatori.fi/henkiloasiakkaat/avoimet-tyopaikat/{}/{}"
PAGE = 90
MAX_PAGE = 100
# Mainland regions (maakunta codes) plus Aland (21); each is far below the paging window.
REGIONS = (
    "01", "02", "04", "05", "06", "07", "08", "09", "10",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "21",
)  # fmt: skip
_LANGS = ("en", "fi", "sv")  # preferred text languages
_URL_ID = re.compile(r"/avoimet-tyopaikat/([^/?#]+)")


def pick(value: Any) -> str:
    """Best text of a `{lang: text}` value: English, Finnish, Swedish, then any."""
    if not isinstance(value, dict):
        return ""
    for lang in (*_LANGS, *value):
        if isinstance(value.get(lang), str) and value[lang].strip():
            return str(value[lang]).strip()
    return ""


def lang_of(value: Any) -> str:
    """The language `pick` draws from (Finnish when there is none)."""
    if isinstance(value, dict):
        for lang in (*_LANGS, *value):
            if isinstance(value.get(lang), str) and value[lang].strip():
                return str(lang)
    return "fi"


class Tyomarkkinatori(Source):
    name = "tyomarkkinatori"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen: set[str] = set()  # a posting in several regions turns up in each
        index = count = 0  # index: one yielded page per (region, page); count: stubs yielded
        for region in REGIONS:
            for page in range(MAX_PAGE + 1):
                body = {
                    "query": "",
                    "filters": {"regions": [region]},
                    "paging": {"pageNumber": page, "pageSize": PAGE},
                    "sorting": "LATEST",
                }
                data = await http.post_json(SEARCH, body)
                rows = data.get("content") or []
                if not rows:
                    break
                stubs = []
                for r in rows:
                    if r.get("id") not in seen and (s := self.stub(r)):
                        seen.add(r["id"])
                        stubs.append(s)
                if stubs and index >= start_page:  # on resume the skipped pages are re-read
                    yield stubs[: task.limit - count]
                    count += len(stubs)
                    if count >= task.limit:
                        return
                index += bool(stubs)
                if page >= data.get("lastPage", 0) or all_older(stubs, task):
                    break

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        employer = r.get("employer") or {}
        title = pick(r.get("title"))
        company = pick(employer.get("ownerName")) or (employer.get("ownerOfficeName") or "").strip()
        if not (r.get("id") and title and company):
            return None
        loc = r.get("location") or {}
        parts = [pick(m.get("label")) for m in loc.get("municipalities") or []]
        if not loc.get("foreignCountry"):
            parts.append("Finland")
        location = ", ".join(p for p in parts if p)
        url = JOB_URL.format(r["id"], lang_of(r.get("title")))
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=location,
            posted_at=from_iso(r.get("publishDate")),
            apply_url=url,
            remote=remote_from_text(location, title),
            extra={"id": r["id"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL_ID.search(stub.url)
        if not m:
            return stub
        resp = await http.get(DETAIL.format(m[1]))
        if resp.status_code != 200:  # incl. the 403 the portal answers when it rate-limits us
            return stub
        d = resp.json()
        pos = d.get("position") or {}
        update: dict[str, Any] = {"description": pick(pos.get("jobDescription"))}
        if title := pick(pos.get("title")):
            update["title"] = title
        if company := pick((d.get("owner") or {}).get("company")):
            update["company"] = company
        if posted := from_iso((d.get("application") or {}).get("published")):
            update["posted_at"] = posted
        return stub.model_copy(update=update)
