"""NEOGOV careers sites for public-sector and education employers
(www.governmentjobs.com/careers/{agency}, www.schooljobs.com/careers/{agency}). The board is
"governmentjobs/{agency}" or "schooljobs/{agency}". The page loads its list from a plain HTML
endpoint, 10 postings a page, newest first; the list has no date and no body.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import XHR, absolute, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import name_from_slug, node_text
from linkit_all.sources.text import html_to_text

LIST = "https://www.{site}.com/careers/home/index"
PAGE = 10
MAX_PAGES = 200
_JOB = re.compile(r"/careers/[^/]+/(?:[^/]+/)?jobs/(\d+)")


class Neogov(Source):
    name = "neogov"
    kind = "ats"
    url_patterns = (
        re.compile(
            r"(?:www\.)?(schooljobs|governmentjobs)\.com/careers/(?!home\b)([a-z0-9][a-z0-9_-]*)",
            re.I,
        ),
    )
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        site, _, agency = task.board.lower().partition("/")
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            params = {
                "agency": agency,
                "sort": "PostingDate",
                "isDescendingSort": "true",
                "page": page,
            }
            resp = await http.get(LIST.format(site=site), params=params, headers=XHR)
            resp.raise_for_status()
            if resp.url.path.rstrip("/") in (
                "",
                "/careers",
            ):  # a wrong agency lands on the home page
                raise ValueError(f"neogov: no agency named {agency}")
            stubs = [s for s in self.rows(resp.text, task.board) if s.url not in seen]
            seen.update(s.url for s in stubs)
            if not stubs:
                return
            yield stubs
            if len(stubs) < PAGE:
                return

    @staticmethod
    def rows(html: str, board: str) -> list[JobStub]:
        site, _, agency = board.lower().partition("/")
        origin = f"https://www.{site}.com"
        stubs = []
        for item in LexborHTMLParser(html).css("li.list-item"):
            link = item.css_first("a.item-details-link")
            url = absolute(link.attributes.get("href") if link else "", origin).split("#")[0]
            m = _JOB.search(url)
            title = node_text(link)
            if not (m and title and url.startswith(origin)):
                continue
            where = node_text(item.css_first("ul.list-meta li"))
            stubs.append(
                JobStub(
                    source="neogov",
                    url=url,
                    title=title,
                    company=name_from_slug(agency),
                    location=where,
                    ats="neogov",
                    apply_url=url,
                    remote=remote_from_text(where),
                    extra={"board": board, "id": m[1]},
                )
            )
        return stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        body = html_to_text(str(found[0].get("description") or "")) if found else ""
        return stub.model_copy(update={"description": body}) if body else stub
