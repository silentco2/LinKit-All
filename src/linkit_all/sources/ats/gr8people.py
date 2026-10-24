"""gr8people / workgr8 career sites: the page embeds an anonymous session token for the tenant's
own GraphQL search, which returns postings with descriptions. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f13 import get_page, mode, name_from_host
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

PAGE = 50
_TOKEN = re.compile(r'"token"\s*:\s*"(eyJ[^"]+)"')
QUERY = """query searchJobs($query: String, $start: Int, $first: Int, $after: String,
    $filters: JobPostingSearchFiltersInput) {
  searchJobs: searchJobPostings(query: $query, start: $start, first: $first, after: $after,
      filters: $filters) {
    results {
      nodes { key title descriptionHTML workplaceType postedOn positionType { name }
              primaryPlace { name } places { nodes { name } } }
      pageInfo { hasNextPage endCursor }
    }
  }
}"""


class Gr8People(Source):
    """The board is the whole careers host: `etrade.gr8people.com` or `acme.workgr8.com`."""

    name = "gr8people"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+\.(?:gr8people|workgr8)\.com)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = task.board
        token = _TOKEN.search((await get_page(http, f"https://{host}/jobs")).text)
        if not token:
            raise ValueError(f"gr8people: no session token on {host}/jobs")
        headers = {"Authorization": f"Bearer {token[1]}"}
        after = ""
        # ponytail: the API pages by cursor, so a resume walks again from the first page.
        for page in range(1000):
            variables: dict[str, Any] = {"query": "", "start": 0, "first": PAGE, "filters": {}}
            if after:  # the cursor decoder rejects an empty string: omit the key instead
                variables["after"] = after
            body = {"operationName": "searchJobs", "query": QUERY, "variables": variables}
            data = await http.post_json(f"https://{host}/graphql", body, headers=headers)
            results = data["data"]["searchJobs"]["results"]
            nodes = results.get("nodes") or []
            if not nodes:
                return
            if page >= start_page:
                yield [s for p in nodes if (s := self.stub(p, host))]
            info = results.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                return
            after = info["endCursor"]

    @staticmethod
    def stub(p: dict[str, Any], host: str) -> JobStub | None:
        if not p.get("key") or not (p.get("title") or "").strip():
            return None
        places = [n["name"] for n in (p.get("places") or {}).get("nodes") or [] if n.get("name")]
        primary = (p.get("primaryPlace") or {}).get("name") or ""
        location = "; ".join(dict.fromkeys(places)) or primary
        url = f"https://{host}/jobs/{p['key']}"
        workplace = (p.get("workplaceType") or "").replace("_", "-")
        return JobStub(
            source="gr8people",
            url=url,
            title=p["title"].strip(),
            company=name_from_host(host),
            location=location,
            description=strip_html(p.get("descriptionHTML") or ""),
            posted_at=from_iso(p.get("postedOn")),
            ats="gr8people",
            apply_url=url,
            remote=mode(workplace) or remote_from_text(location),
            extra={
                "board": host,
                "id": p["key"],
                "type": (p.get("positionType") or {}).get("name"),
            },
        )
