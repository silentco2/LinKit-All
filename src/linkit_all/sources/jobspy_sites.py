"""Job sites through python-jobspy: LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter, Bayt."""

import asyncio
import json
import logging
import multiprocessing
import pickle
import re
import signal
from collections.abc import AsyncIterator, Callable
from multiprocessing.connection import Connection
from typing import Any

from loguru import logger

from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import (
    PAGE_TIMEOUT,
    JobStub,
    Remote,
    Source,
    Task,
    from_iso,
    remote_from_text,
)
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

# jobspy.scrape_jobs signature; injectable for tests (module-level, it is pickled).
Scraper = Callable[..., Any]

_LOGGERS = {"linkedin": "LinkedIn", "indeed": "Indeed", "glassdoor": "Glassdoor",
            "google": "Google", "zip_recruiter": "ZipRecruiter", "bayt": "Bayt"}  # fmt: skip


def _child(conn: Connection, fn: Scraper, kwargs: dict[str, Any]) -> None:
    """Runs in the child process: send back (True, result) or (False, exception)."""
    # Ctrl-C reaches every process on the Windows console. Only the parent decides when the
    # scrape ends: it terminates this process when its own task is cancelled.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        msg: tuple[bool, Any] = (True, fn(**kwargs))
    except BaseException as e:
        try:
            # our own child's error; it must survive the trip or the parent cannot read it
            pickle.loads(pickle.dumps(e))  # noqa: S301
            msg = (False, e)
        except Exception:
            msg = (False, RuntimeError(f"{type(e).__name__}: {e}"))
    conn.send(msg)


async def _in_child(fn: Scraper, **kwargs: Any) -> Any:
    """Run fn in a child process; return its result or re-raise its error. The child is killed
    and reaped on every way out (done, error, timeout, Ctrl-C), so a hung scrape cannot outlive
    the awaiting task or hold the interpreter at exit. fn and its result must pickle."""
    # ponytail: one process start per task (1-2 s on Windows); a pool only if tasks get tiny.
    ctx = multiprocessing.get_context("spawn")  # the only start method on Windows; same everywhere
    recv, send = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(send, fn, kwargs), daemon=True)
    try:
        proc.start()
    except BaseException:
        recv.close()
        send.close()
        raise
    send.close()  # only the child holds the write end, so its death shows up as EOF
    try:
        try:
            while not recv.poll():  # poll raises once the child is gone with nothing sent
                await asyncio.sleep(0.1)
            ok, value = recv.recv()
        except (EOFError, OSError) as e:
            raise RuntimeError(f"scraper process died (exit code {proc.exitcode})") from e
    finally:
        recv.close()
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join(5)
        if not proc.is_alive():  # close() raises on a live process
            proc.close()
    if not ok:
        if not isinstance(value, Exception):  # SystemExit, KeyboardInterrupt: never re-raise
            raise RuntimeError(f"{type(value).__name__}: {value}")
        raise value
    return value


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
    kind = "jobspy"
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
                 posted_within_hours=s.posted_within_hours,
                 country=cfg.sources.jobspy_country if self.name == "indeed" else "")
            for q in s.queries
            for loc in s.locations
        ]  # fmt: skip

    def page_timeout(self, task: Task) -> float:
        # A task is one page. Worst case per wanted job, every request hitting jobspy's 15 s
        # request timeout (jobspy/util.py request_timeout): one detail fetch (15 s) plus its
        # share of a search page per 10 jobs (one 15 s request and one pause of at most 7 s,
        # LinkedIn/ZipRecruiter 3+4 s, Bayt 2+3 s) = 2.2 s, so ~17 s, rounded up to 20 s.
        # Plus 300 s for setup. 200 jobs -> 4300 s. Generous on purpose: this only stops a true
        # hang, and a resume redoes the whole task, so cutting a slow one off is worse.
        # ponytail: this limit is a safety net against a true hang, so one stalled task can hold
        # the end of discover for over an hour; discover() skips the site's other tasks after
        # its first timeout, so that wait does not multiply by the number of tasks.
        return max(PAGE_TIMEOUT, 300.0 + 20.0 * task.limit)

    def scrape_args(self, task: Task) -> dict[str, Any]:
        return {
            "site_name": [self.name],
            "search_term": task.query,
            "google_search_term": f"{task.query} jobs near {task.location}".strip(),
            "location": task.location or None,
            "results_wanted": task.limit,
            "hours_old": task.posted_within_hours,
            **({"country_indeed": task.country} if task.country else {}),  # else jobspy default
            "description_format": "markdown",
            "fetch_description": True,
            "verbose": 0,
        }

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # jobspy pages internally; a task is one unit
            return
        async with self._lock:  # the child is gone before the lock is released
            logger.info(
                "{}: scraping up to {} jobs with descriptions, this can take several minutes",
                task.key,
                task.limit,
            )
            rows = await _in_child(self._scrape, **self.scrape_args(task))
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


# The public job page names its Apply button: "offsite" links to the employer's own site (the
# address is only shown after signing in), "onsite"/"simple" is LinkedIn Easy Apply.
_APPLY_KIND = re.compile(r"public_jobs_apply-link-(offsite|onsite|simple)")


def linkedin_apply(html: str) -> str | None:
    """How a LinkedIn job is applied to: "offsite" (the employer's site) or "easy_apply"."""
    m = _APPLY_KIND.search(html)
    if m is None:
        return None
    return "offsite" if m.group(1) == "offsite" else "easy_apply"


JOBSPY_SITES = ("linkedin", "indeed", "glassdoor", "google", "zip_recruiter", "bayt")


def jobspy_sources(scrape: Scraper = _scrape_jobs) -> list[JobSpySite]:
    return [JobSpySite(site, scrape) for site in JOBSPY_SITES]


def sources(**_: Any) -> list[Source]:
    """Registry hook: one source per jobspy site."""
    return [*jobspy_sources()]
