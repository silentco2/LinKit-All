"""BairesDev (talent.bairesdev.com): the public talent page embeds its whole open-role list in a
base64 widget config; the applicants site serves each role's text from keyless JSON endpoints.
Single-company plugin; links are unattributed (no referrer code). Logic adapted from freehire
(MIT)."""

import base64
import binascii
import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page, strip_html
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.parsing import ats_of, when

TALENT = "https://talent.bairesdev.com/"
POSTING = "https://applicants.bairesdev.com/api/JobPosting?JobPostingId={id}"  # title, date, teaser
JOB = "https://applicants.bairesdev.com/api/Job?JobOfferId={id}"  # the full description
APPLY = "https://applicants.bairesdev.com/job/{career}/{id}/apply"
_WIDGET = re.compile(r'data-widget-config="([A-Za-z0-9+/=]+)"')
_APPLY = re.compile(r"/job/(\d+)/(\d+)/apply")


def parse_listing(page: str) -> list[JobStub]:
    """One stub per distinct job id: the site lists a role once per location under a shared id,
    with "Role | Remote Work | Location" as the row title, so the locations are joined."""
    m = _WIDGET.search(page)
    try:
        rows = json.loads(base64.b64decode(m[1]))["jobList"] if m else None
    except (binascii.Error, ValueError, KeyError, TypeError):
        rows = None
    if not isinstance(rows, list):
        raise ValueError("no job widget on the BairesDev talent page")
    jobs: dict[str, tuple[str, str, list[str]]] = {}  # id -> (career id, title, locations)
    for row in rows:
        a = _APPLY.search(str(row.get("page_item_url") or "")) if isinstance(row, dict) else None
        if not a:
            continue
        parts = [p.strip() for p in str(row.get("jobTitle") or "").split("|")]
        _, _, places = jobs.setdefault(a[2], (a[1], parts[0], []))
        if len(parts) >= 3 and parts[-1].lower() != "remote work" and parts[-1] not in places:
            places.append(parts[-1])
    stubs = []
    for jid, (career, title, places) in jobs.items():
        url = APPLY.format(career=career, id=jid)
        if title:
            stubs.append(
                JobStub(
                    source="bairesdev",
                    url=url,
                    title=title,
                    company="BairesDev",
                    location=", ".join(places),
                    ats=ats_of(url, "bairesdev"),
                    apply_url=url,
                    remote="remote",  # every role on the talent page is "Remote Work"
                    extra={"id": jid, "career": career},
                )
            )
    return stubs


class BairesDev(Source):
    name = "bairesdev"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "bairesdev:talent")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        stubs = parse_listing((await get_page(http, TALENT)).text)
        if start_page == 0 and stubs:
            yield stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _APPLY.search(stub.url)
        if stub.description or not m:
            return stub
        posting: dict[str, Any] = await http.get_json(POSTING.format(id=m[2]))
        description = ""
        try:  # the full text; if this endpoint hiccups the teaser still beats no text
            results = (await http.get_json(JOB.format(id=m[2]))).get("jobResults") or []
            description = strip_html(str(results[0].get("description") or "")) if results else ""
        except (httpx.HTTPError, RetryableStatus, ValueError):
            pass
        return stub.model_copy(
            update={
                "description": description or strip_html(str(posting.get("description") or "")),
                "posted_at": when(posting.get("datePosted")),
            }
        )
