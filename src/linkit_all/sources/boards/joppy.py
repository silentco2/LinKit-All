"""Joppy (joppy.me), a Spain-only tech hiring platform with no search API: the directory sitemap
lists the companies and each company page embeds its open jobs.
Logic adapted from freehire (MIT)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.ats._f13 import get_page, sitemap_locs
from linkit_all.sources.ats._f16 import chunks, next_data, page_text
from linkit_all.sources.base import JobStub, Remote, Source, Task, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

BASE = "https://www.joppy.me"
SITEMAP = BASE + "/sitemap.directory.xml"
COMPANIES = 8  # company pages fetched together per yielded page
LANG_MAX = 5


def company_slugs(xml: str) -> list[str]:
    """Company slugs of the directory sitemap, sorted (job addresses inside it are ignored)."""
    prefix = BASE + "/companies/"
    slugs = {u[len(prefix) :].split("/", 1)[0] for u in sitemap_locs(xml) if u.startswith(prefix)}
    return sorted(s for s in slugs if s)


def work_mode(place: dict[str, Any]) -> Remote | None:
    remote, hybrid, office = (bool(place.get(k)) for k in ("isRemote", "isHybrid", "isOffice"))
    if hybrid:
        return "hybrid"
    if remote and not office:
        return "remote"
    return "onsite" if office and not remote else None


def extras(job: dict[str, Any]) -> str:
    """The posting's structured facts (skills, languages, visa, relocation) as plain sentences."""
    skills = [s for s in job.get("skills") or [] if (s.get("name") or "").strip()]
    must = [s["name"].strip() for s in skills if s.get("isMandatory")]
    nice = [s["name"].strip() for s in skills if not s.get("isMandatory")]
    langs = [
        f"{x['name'].strip()} (level {x.get('level')}/{LANG_MAX})"
        for x in job.get("languages") or []
        if (x.get("name") or "").strip()
    ]
    lines = [
        f"Must-have skills: {', '.join(must)}." if must else "",
        f"Nice-to-have skills: {', '.join(nice)}." if nice else "",
        f"Required languages: {', '.join(langs)}." if langs else "",
        "The employer sponsors a work visa for this role." if job.get("sponsorVisa") else "",
        "A relocation package is offered." if job.get("relocationPack") else "",
        "Open only to candidates already eligible to work in the EU."
        if job.get("onlyEuCandidates")
        else "",
    ]
    return "\n\n".join(x for x in lines if x)


class Joppy(Source):
    name = "joppy"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        slugs = company_slugs((await get_page(http, SITEMAP)).text)
        count = 0
        for group in chunks(slugs, start_page, COMPANIES):
            pages = await asyncio.gather(*(self.company(http, s) for s in group))
            stubs = [s for found in pages for s in found][: task.limit - count]
            count += len(stubs)
            if stubs:
                yield stubs
            if count >= task.limit:
                return

    async def company(self, http: Http, slug: str) -> list[JobStub]:
        page = await page_text(http, f"{BASE}/companies/{slug}")
        data = next_data(page) if page else None
        company = (((data or {}).get("props") or {}).get("pageProps") or {}).get("company")
        if not isinstance(company, dict):
            return []
        name = (company.get("name") or "").strip()
        jobs = [self.stub(j, name, company.get("slug") or slug) for j in company.get("jobs") or []]
        return [j for j in jobs if j]

    def stub(self, j: dict[str, Any], company: str, slug: str) -> JobStub | None:
        uid, title = (j.get("uid") or "").strip(), (j.get("title") or "").strip()
        if not (uid and title and company):
            return None
        place = j.get("place") or {}
        cities = place.get("cities") or []
        location = "; ".join(cities) if cities else (place.get("located") or "").strip()
        url = f"{BASE}/companies/{slug}/{uid}"
        pay = bool(j.get("isSalaryPublic") and (j.get("salaryMin") or j.get("salaryMax")))
        text = (strip_html(j.get("description") or ""), extras(j))
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=location,
            description="\n\n".join(x for x in text if x),
            apply_url=url,
            ats=self.name,
            remote=work_mode(place) or remote_from_text(location),
            salary_min=j.get("salaryMin") if pay else None,
            salary_max=j.get("salaryMax") if pay else None,
            salary_currency="EUR" if pay else None,
            salary_interval="year" if pay else None,
            extra={"id": uid, "company": slug},
        )
