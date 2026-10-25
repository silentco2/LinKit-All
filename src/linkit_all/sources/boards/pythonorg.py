"""The Python.org job board (python.org/jobs), run by the Python Software Foundation: employers
post Python roles directly. The listing pages give the cards, each posting page the description
(`fetch_details`). Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

import httpx
from selectolax.lexbor import LexborHTMLParser, LexborNode

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.ats._f13 import get_page
from linkit_all.sources.ats._f16 import when
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

BASE = "https://www.python.org"
LIST = BASE + "/jobs/"
MAX_PAGES = 40
_POSTING = re.compile(r"^/jobs/(\d+)/$")
_TITLE_LINE = re.compile(
    r"\AJob Title\s*\n[^\n]*\n"
)  # the heading and the line repeating the title


def _words(node: LexborNode | None) -> str:
    return " ".join(node.text(deep=True).split()) if node is not None else ""


def cards(html: str) -> list[JobStub]:
    """The listing page's job cards. A card without a posting link, title or company is skipped."""
    out = []
    for li in LexborHTMLParser(html).css(".list-recent-jobs > li"):
        name = li.css_first(".listing-company-name")
        link = name.css_first("a") if name is not None else None
        m = _POSTING.match((link.attributes.get("href") or "") if link is not None else "")
        if name is None or link is None or not m:
            continue
        company, node = [], link.next  # the employer is the text that follows the title link
        while node is not None:
            if node.tag == "-text":
                company.append(node.text())
            node = node.next
        time = li.css_first("time")
        stub = JobStub(
            source="pythonorg",
            url=BASE + m[0],
            title=_words(link),
            company=" ".join(" ".join(company).split()),
            location=_words(li.css_first(".listing-location")),
            posted_at=when(time.attributes.get("datetime") if time is not None else None),
            ats="pythonorg",
            apply_url=BASE + m[0],
            extra={"id": m[1]},
        )
        if stub.title and stub.company:
            out.append(stub.model_copy(update={"remote": remote_from_text(stub.location)}))
    return out


class PythonOrg(Source):
    name = "pythonorg"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen: set[str] = set()
        count = 0
        for page in range(start_page + 1, MAX_PAGES + 1):
            url = LIST if page == 1 else f"{LIST}?page={page}"
            try:
                text = (await get_page(http, url)).text
            except httpx.HTTPStatusError as e:
                if page > 1 and e.response.status_code == 404:  # past the last page
                    return
                raise
            fresh = [s for s in cards(text) if s.url not in seen]
            if not fresh:
                return
            seen.update(s.url for s in fresh)
            fresh = fresh[: task.limit - count]
            count += len(fresh)
            yield fresh
            if count >= task.limit:
                return

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        node = LexborHTMLParser((await get_page(http, stub.url)).text).css_first(".job-description")
        text = (
            _TITLE_LINE.sub("", strip_html(node.inner_html or "")).strip()
            if node is not None
            else ""
        )
        return stub.model_copy(update={"description": text}) if text.strip() else stub
