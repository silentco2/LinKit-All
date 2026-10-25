"""Japan Dev (japan-dev.com), a curated tech job board for Japan: the sitemap lists the postings and
each page embeds the posting in its Nuxt payload (a devalue reference table).
Logic adapted from freehire (MIT)."""

import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.ats._f16 import CHUNK, page_text, when
from linkit_all.sources.ats._f17 import hydrate
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.boards._f31 import ats_of, sitemap_urls
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

INDEX = "https://japan-dev.com/sitemap.xml"
_REMOTE: dict[str, Remote] = {
    "remote_level_partial": "hybrid",
    "remote_level_full_japan": "remote",
    "remote_level_full_worldwide": "remote",
    "remote_level_around_office": "remote",
    "remote_level_none": "onsite",
}
_LEVELS = {
    "not_required": "Not required",
    "conversational": "Conversational",
    "business_level": "Business level",
    "fluent": "Fluent",
}
_FACTS = {
    "candidate_location": {
        "candidate_location_anywhere": "Applications: candidates may apply from outside Japan",
        "candidate_location_japan_only": "Applications: candidates must already be in Japan",
    },
    "sponsors_visas": {
        "sponsors_visas_yes": "Visa sponsorship: available",
        "sponsors_visas_no": "Visa sponsorship: not available",
    },
}
_TEXT_FIELDS = (
    "title", "slug", "location", "raw_content", "application_url", "published_at", "updated_at",
    "remote_level", "candidate_location", "sponsors_visas", "japanese_level_enum",
    "english_level_enum",
)  # fmt: skip


def posting_slug(url: str) -> str:
    """The slug of /jobs/<company>/<slug> on japan-dev.com; "" for any other address."""
    u = urlsplit(url.strip())
    parts = u.path.strip("/").split("/")
    ok = u.scheme == "https" and (u.hostname or "").lower() == "japan-dev.com"
    return parts[2] if ok and len(parts) == 3 and parts[0] == "jobs" and all(parts) else ""


def _deref(table: list[Any], v: Any) -> Any:
    """Nuxt's payload stores every field as the index of its value in the table."""
    if isinstance(v, int) and not isinstance(v, bool):
        return table[v] if 0 <= v < len(table) else None
    return v


def _str(table: list[Any], v: Any) -> str:
    s = _deref(table, v)
    return s.strip() if isinstance(s, str) else ""


def _int(table: list[Any], v: Any) -> int | None:
    n = _deref(table, v)
    if isinstance(n, str) and n.strip().isdigit():
        n = int(n)
    return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else None


def nuxt_job(page: str) -> dict[str, Any] | None:
    """The posting object of the page's payload, resolved to plain values; None when absent."""
    node = LexborHTMLParser(page).css_first("script#__NUXT_DATA__")
    try:
        table = json.loads(node.text(deep=True)) if node else None
    except ValueError:
        return None
    if not isinstance(table, list):
        return None
    for cell in table:
        job = _deref(table, cell["job"]) if isinstance(cell, dict) and "job" in cell else None
        if isinstance(job, dict) and "title" in job and "slug" in job:
            break
    else:
        return None
    company = _deref(table, job.get("company"))
    skills = []
    for ref in _deref(table, job.get("skills")) or []:
        skill = _deref(table, ref)
        if isinstance(skill, dict) and (name := _str(table, skill.get("name"))):
            skills.append(name)
    out: dict[str, Any] = {k: _str(table, job.get(k)) for k in _TEXT_FIELDS}
    out["company"] = _str(table, company.get("name")) if isinstance(company, dict) else ""
    out["salary_min"] = _int(table, job.get("salary_min"))
    out["salary_max"] = _int(table, job.get("salary_max"))
    out["skills"] = list(dict.fromkeys(skills))
    return out


def facts(job: dict[str, Any]) -> str:
    """What the page shows as tags (language, visa, who may apply), as plain lines."""
    lines = [_FACTS[k].get(job[k], "") for k in _FACTS]
    for label, key in (("Japanese", "japanese_level_enum"), ("English", "english_level_enum")):
        level = _LEVELS.get(job[key].split("_level_", 1)[-1], "")
        lines.append(f"{label}: {level}" if level else "")
    if job["skills"]:
        lines.append("Japan Dev tags: " + ", ".join(job["skills"]))
    return "\n".join(x for x in lines if x)


class JapanDev(Source):
    name = "japandev"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        # ponytail: sitemap order, capped at task.limit; the sitemap carries no dates
        urls = await sitemap_urls(http, INDEX, "/sitemaps/", lambda u: bool(posting_slug(u)))

        async def build(url: str) -> JobStub | None:
            page = await page_text(http, url)
            return self.stub(page, url) if page else None

        async for stubs in hydrate(urls[: task.limit], start_page, build, CHUNK):
            yield stubs

    def stub(self, page: str, url: str) -> JobStub | None:
        job = nuxt_job(page)
        slug = posting_slug(url)
        if not job or not (job["title"] and job["company"]) or job["slug"] not in ("", slug):
            return None
        body = strip_html(job["raw_content"])
        if not body:
            node = LexborHTMLParser(page).css_first(".job-detail-main-content")
            body = strip_html(node.html or "") if node else ""
        if not body:
            return None
        apply = job["application_url"]
        parts = urlsplit(apply)
        apply = apply if parts.scheme in ("http", "https") and parts.netloc else url
        pay = bool(job["salary_min"] or job["salary_max"])
        return JobStub(
            source=self.name,
            url=url,
            title=job["title"],
            company=job["company"],
            location=job["location"],
            description="\n\n".join(x for x in (facts(job), body) if x),
            posted_at=when(job["published_at"] or job["updated_at"]),
            ats=ats_of(apply, self.name),
            apply_url=apply,
            remote=_REMOTE.get(job["remote_level"]),
            salary_min=job["salary_min"],
            salary_max=job["salary_max"],
            salary_currency="JPY" if pay else None,
            salary_interval="year" if pay else None,
            extra={"id": slug},
        )
