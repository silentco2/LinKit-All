"""Source plugin interface: a source yields pages of job stubs for a task."""

import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from linkit_all.core.search import SearchConfig
from linkit_all.sources.http import Http

Remote = Literal["remote", "hybrid", "onsite"]
SourceKind = Literal[
    "ats", "aggregator", "board", "company", "jobspy", "regional", "careers", "telegram"
]
# Kinds the user switches on by name in `sources.enabled`. The others are driven by something
# else: the company list (ats, careers) or their own lists `sources.jobspy` / `sources.regional`.
OPT_IN_KINDS: frozenset[str] = frozenset({"aggregator", "board", "company", "telegram"})


class JobStub(BaseModel):
    source: str
    url: str
    title: str
    company: str
    location: str = ""
    description: str = ""  # plain text; empty until fetch_details when the list has none
    posted_at: datetime | None = None
    ats: str | None = None  # which ATS hosts the application (drives the apply handler)
    apply_url: str | None = None
    remote: Remote | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_interval: str | None = None  # year, month, hour...
    extra: dict[str, Any] = {}


@dataclass(frozen=True)
class Task:
    source: str
    key: str  # checkpoint key, unique per run
    board: str = ""  # ATS company slug
    query: str = ""
    location: str = ""
    limit: int = 200
    posted_within_days: int = 14
    country: str = ""  # for sites with per-country domains (Indeed, Glassdoor)


class Source(ABC):
    name: str
    priority: int = 0  # lower wins: its copy of a duplicate job is the one kept
    # How many of this source's tasks may run at once. 1 for anything rate-sensitive (scraped
    # sites); public ATS JSON APIs raise it, their per-host limiters in Http pace the requests.
    parallel: int = 1
    kind: SourceKind = "ats"  # always set it in a new plugin; see linkit_all.sources
    default_on: bool = False  # opt-in kinds only: run without being listed in sources.enabled
    # ATS plugins: regexes over a URL or page HTML. Group 1.. is the board slug (joined by "/").
    url_patterns: Sequence[re.Pattern[str]] = ()
    # ATS plugins: Common Crawl CDX url patterns that list the vendor's boards, e.g.
    # "jobs.lever.co/*" or "*.recruitee.com". Empty = not discoverable (see discovery.py).
    cdx_hosts: Sequence[str] = ()

    def is_enabled(self, cfg: SearchConfig) -> bool:
        """Should discovery ask this source for tasks? Opt-in kinds need `sources.enabled`;
        the rest decide in `tasks()` from their own config."""
        return self.kind not in OPT_IN_KINDS or self.default_on or self.name in cfg.sources.enabled

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        """Query-based sources expand the search config into tasks. ATS boards come from
        the company list instead (see runner.company_tasks)."""
        return []

    @abstractmethod
    def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        """Yield one list of stubs per page, starting at `start_page` (for resume)."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook, nothing to do by default
        """Release anything held for a discovery run (a browser, say). Called once at its end."""

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        """Fill in the description when the listing did not include it."""
        return stub

    async def is_live(self, http: Http, stub: JobStub) -> bool | None:
        """Is the posting still open? False only on a clear "gone" answer from the ATS; None =
        unknown (no way to ask, network error, 5xx, 429...). Never raises for a failed request."""
        return None


def status_live(status: int) -> bool | None:
    """Detail-page status -> live? 200 yes, 404/410 gone, anything else unknown."""
    if status == 200:
        return True
    return False if status in (404, 410) else None


def remote_from_text(*texts: str | None) -> Remote | None:
    joined = " ".join(t for t in texts if t).lower()
    if "hybrid" in joined:
        return "hybrid"
    if "remote" in joined:
        return "remote"
    return None


def from_epoch_ms(ms: int | float | None) -> datetime | None:
    """Epoch milliseconds -> naive UTC (the DB convention)."""
    return datetime.fromtimestamp(ms / 1000, UTC).replace(tzinfo=None) if ms else None


def from_iso(value: str | None) -> datetime | None:
    """ISO timestamp -> naive UTC (the DB convention)."""
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt
