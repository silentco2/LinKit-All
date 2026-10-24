"""Dover-hosted career pages (app.dover.com): a public JSON API, description on a detail call.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f12 import mode, name_from_slug
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import paged
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://app.dover.com/api/v1"
LIMIT = 300  # the API accepts large pages
APPLY = "https://app.dover.com/apply/{slug}/{id}"
_URL = re.compile(r"app\.dover\.com/apply/[\w-]+/([\w-]+)", re.I)
_EMPLOYMENT = {
    "FULL_TIME": "full-time",
    "PART_TIME": "part-time",
    "CONTRACT": "contract",
    "TEMPORARY": "contract",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
}


class Dover(Source):
    """The board is the company's Dover slug (`app.dover.com/apply/<slug>/<jobId>`). The list
    has no description, compensation or employment type: `fetch_details` adds them."""

    name = "dover"
    kind = "ats"
    url_patterns = (
        re.compile(r"app\.dover\.com/(?:apply|jobs)/([\w-]+)", re.I),
        re.compile(r"app\.dover\.com/api/v1/careers-page-slug/([\w-]+)", re.I),
    )
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        slug = task.board
        client = await http.get_json(f"{API}/careers-page-slug/{slug}")
        if not client.get("id"):
            raise ValueError(f"dover: slug {slug} resolved to no client id")
        company = client.get("name") or name_from_slug(slug)

        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            data = await http.get_json(
                f"{API}/careers-page/{client['id']}/jobs", params={"limit": LIMIT, "offset": offset}
            )
            return data.get("results") or [], data.get("count")

        async for items in paged(fetch, LIMIT, start_page):
            # Samples and unpublished postings never reach the user.
            live = [j for j in items if j.get("is_published") and not j.get("is_sample")]
            yield [self.stub(j, slug, company) for j in live]

    @staticmethod
    def stub(j: dict[str, Any], slug: str, company: str) -> JobStub:
        url = APPLY.format(slug=slug, id=j["id"])
        places = [
            (loc.get("location_option") or {}).get("display_name")
            for loc in j.get("locations") or []
        ]
        return JobStub(
            source="dover",
            url=url,
            title=(j.get("title") or "").strip(),
            company=company,
            location="; ".join(dict.fromkeys(p for p in places if p)),
            ats="dover",
            apply_url=url,
            remote=mode(j.get("workplace_type")),
            extra={"board": slug, "id": j["id"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m:
            return stub
        d = await http.get_json(f"{API}/inbound/application-portal-job/{m[1]}")
        comp = d.get("compensation") or {}
        notes = []
        if comp.get("offers_equity"):
            notes.append("This role offers equity compensation.")
        if d.get("visa_support"):
            notes.append("The employer sponsors a work visa for this role.")
        description = "\n\n".join(
            x for x in (html_to_text(d.get("user_provided_description") or ""), *notes) if x
        )
        update: dict[str, Any] = {
            "description": description,
            "remote": mode(d.get("workplace_type")) or stub.remote,
            "extra": {
                **stub.extra,
                "employment": _EMPLOYMENT.get(comp.get("employment_type") or ""),
            },
        }
        # Pay is published only when the company agreed to share it.
        if comp.get("open_to_sharing_comp") and (
            comp.get("lower_bound") or comp.get("upper_bound")
        ):
            update |= {
                "salary_min": comp.get("lower_bound"),
                "salary_max": comp.get("upper_bound"),
                "salary_currency": comp.get("currency_code"),
                "salary_interval": "year",
            }
        return stub.model_copy(update=update)
