"""CareerPlug career sites ({board}.careerplug.com): a paged /jobs listing and a schema.org
JobPosting on each posting page. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub
from linkit_all.sources.text import html_to_text

MAX_PAGES = 100  # a board that clamps ?page=N to its last page must not loop
_JOB = re.compile(r"/jobs/(\d+)")


def job_links(html: str, base: str) -> list[str]:
    """Absolute, de-duplicated /jobs/<id> links (a card links the same job more than once)."""
    found: dict[str, None] = {}
    for a in LexborHTMLParser(html).css("a[href]"):
        href = a.attributes["href"] or ""
        if _JOB.search(href):
            found[urljoin(base, href).split("#")[0]] = None
    return list(found)


class CareerPlug(Source):
    name = "careerplug"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.careerplug\.com", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = f"{task.board.lower()}.careerplug.com"
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            list_url = f"https://{host}/jobs" + (f"?page={page}" if page > 1 else "")
            await http.allowed(list_url)
            resp = await http.get(list_url)
            resp.raise_for_status()
            fresh = [u for u in job_links(resp.text, f"https://{host}/") if u not in seen]
            if not fresh:  # an empty page, or one clamped to the last page: the end
                return
            seen.update(fresh)
            stubs = [s for u in fresh if (s := await self.posting(http, u, task.board))]
            yield stubs

    async def posting(self, http: Http, url: str, board: str) -> JobStub | None:
        m = _JOB.search(url)
        if m is None:
            return None
        await http.allowed(url)
        resp = await http.get(url)
        if resp.status_code in (404, 410):
            return None
        resp.raise_for_status()
        found = job_postings(resp.text)[:1]
        if not found:
            return None
        p = found[0]
        stub = to_stub(p, "careerplug", url, "careerplug")
        org = p.get("hiringOrganization")
        # Accounts are often franchises whose postings name the individual location's business.
        name = (org.get("name") if isinstance(org, dict) else "") or board.replace("-", " ").title()
        return stub.model_copy(
            update={
                "title": " ".join(str(p.get("title") or "").split()),
                "company": name.strip(),
                "description": html_to_text(p.get("description") or "", escaped=True),
                "remote": remote_from_text(stub.location),
                "extra": {"board": board, "id": m[1]},
            }
        )
