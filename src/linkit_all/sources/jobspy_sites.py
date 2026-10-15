"""Job sites through python-jobspy: LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter, Bayt."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

Scraper = Callable[..., Any]  # jobspy.scrape_jobs signature; injectable for tests


_LOGGERS = {"linkedin": "LinkedIn", "indeed": "Indeed", "glassdoor": "Glassdoor",
            "google": "Google", "zip_recruiter": "ZipRecruiter", "bayt": "Bayt"}  # fmt: skip


class _Errors(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _scrape_jobs(**kwargs: Any) -> list[dict[str, Any]]:
    from jobspy import scrape_jobs  # pandas import is slow; only pay it when used

    # jobspy logs failures (e.g. LinkedIn 429) and returns no rows; surface them so the
    # task is not marked done and a resumed run retries it.
    site_log = logging.getLogger(f"JobSpy:{_LOGGERS[kwargs['site_name'][0]]}")
    errors = _Errors()
    site_log.addHandler(errors)
    try:
        df = scrape_jobs(**kwargs)
    finally:
        site_log.removeHandler(errors)
    rows: list[dict[str, Any]] = json.loads(df.to_json(orient="records", date_format="iso"))
    if not rows and errors.messages:
        raise RuntimeError(errors.messages[0])
    return rows


class JobSpySite(Source):
    priority = 1  # after company ATS APIs

    def __init__(self, site: str, scrape: Scraper = _scrape_jobs) -> None:
        self.name = site
        self._scrape = scrape
        # ponytail: one request stream per site; big sites ban parallel scraping fast.
        self._lock = asyncio.Lock()

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        if self.name not in cfg.sources.jobspy and self.name not in cfg.sources.regional:
            return []
        s = cfg.search
        return [
            Task(self.name, f"{self.name}:{q}@{loc}", query=q, location=loc,
                 limit=s.max_results_per_query, posted_within_days=s.posted_within_days,
                 country=cfg.sources.jobspy_country)
            for q in s.queries
            for loc in s.locations
        ]  # fmt: skip

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # jobspy pages internally; a task is one unit
            return
        async with self._lock:
            rows = await asyncio.to_thread(
                self._scrape,
                site_name=[self.name],
                search_term=task.query,
                google_search_term=f"{task.query} jobs near {task.location}".strip(),
                location=task.location or None,
                results_wanted=task.limit,
                hours_old=task.posted_within_days * 24,
                country_indeed=task.country or "usa",
                description_format="markdown",
                fetch_description=True,
                verbose=0,
            )
        yield [self.stub(r) for r in rows if r.get("job_url") and r.get("title")]

    def stub(self, r: dict[str, Any]) -> JobStub:
        direct = r.get("job_url_direct") or None
        found = detect(direct) if direct else None
        remote: Remote | None = "remote" if r.get("is_remote") else None
        return JobStub(
            source=self.name,
            url=r["job_url"],
            title=r["title"],
            company=r.get("company") or "Unknown",
            location=r.get("location") or "",
            description=r.get("description") or "",
            posted_at=from_iso(r.get("date_posted")),
            # Company ATS when the posting links one, else apply on the site itself.
            ats=found[0] if found else self.name,
            apply_url=direct or r["job_url"],
            remote=remote or remote_from_text(r.get("work_from_home_type")),
            salary_min=r.get("min_amount"),
            salary_max=r.get("max_amount"),
            salary_currency=r.get("currency"),
            salary_interval=r.get("interval"),
            extra={k: r.get(k) for k in ("id", "job_type", "job_level", "company_url") if r.get(k)},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if self.name != "linkedin":
            return stub
        resp = await http.get(stub.url)
        resp.raise_for_status()
        from selectolax.lexbor import LexborHTMLParser

        node = LexborHTMLParser(resp.text).css_first("div.show-more-less-html__markup")
        if node is not None:
            stub.description = html_to_text(node.html or "")
        return stub


JOBSPY_SITES = ("linkedin", "indeed", "glassdoor", "google", "zip_recruiter", "bayt")


def jobspy_sources(scrape: Scraper = _scrape_jobs) -> list[JobSpySite]:
    return [JobSpySite(site, scrape) for site in JOBSPY_SITES]
