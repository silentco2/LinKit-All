"""Dedupe and persist job stubs; a page and its checkpoint commit together."""

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from loguru import logger
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import Job, JobState, SourceCheckpoint
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Source
from linkit_all.sources.text import job_hash, norm, norm_company, normalize_url


@dataclass
class Known:
    """A job already stored (or just added) that later stubs are compared against."""

    job_id: int | None  # None only between register() and the flush that assigns it
    priority: int  # of its source; lower wins


class Deduper:
    """Exact normalized URL, exact title/company/location hash, then fuzzy title per company.

    Remembers which stored job each key belongs to, so a duplicate from a higher-priority
    source can upgrade that job (see store_page).

    ponytail: same-title openings at one company and location collapse into one job; fine
    while one_per_company is the default, revisit if that changes.
    """

    def __init__(self, session: Session, priority: Callable[[str], int] = lambda _: 0) -> None:
        self.priority = priority
        rows = session.execute(
            select(Job.id, Job.source, Job.url, Job.dedupe_hash, Job.title, Job.company,
                   Job.location)
        ).all()  # fmt: skip
        self.urls: dict[str, Known] = {}
        self.hashes: dict[str, Known] = {}
        self.by_company: defaultdict[str, list[tuple[str, str, Known]]] = defaultdict(list)
        for r in rows:
            known = Known(r.id, priority(r.source))
            self.urls[r.url] = self.hashes[r.dedupe_hash] = known
            self.by_company[norm_company(r.company)].append(
                (norm(r.title), norm(r.location), known)
            )

    def lookup(self, stub: JobStub) -> Known | None:
        """The stored job this stub duplicates, if any."""
        if known := self.urls.get(normalize_url(stub.url)):
            return known
        if known := self.hashes.get(job_hash(stub.title, stub.company, stub.location)):
            return known
        title, loc = norm(stub.title), norm(stub.location)
        for t, other_loc, known in self.by_company[norm_company(stub.company)]:
            if fuzz.token_sort_ratio(title, t) >= 92 and (
                not loc or not other_loc or fuzz.token_set_ratio(loc, other_loc) >= 85
            ):
                return known
        return None

    def register(self, stub: JobStub) -> tuple[str, str, Known]:
        """Record a stub that lookup() did not match. Returns (normalized url, hash, known)."""
        url = normalize_url(stub.url)
        h = job_hash(stub.title, stub.company, stub.location)
        known = Known(None, self.priority(stub.source))
        self.urls[url] = self.hashes[h] = known
        self.by_company[norm_company(stub.company)].append(
            (norm(stub.title), norm(stub.location), known)
        )
        return url, h, known

    def add(self, stub: JobStub) -> tuple[str, str] | None:
        """(normalized url, hash) if the stub is new, else None."""
        if self.lookup(stub) is not None:
            return None
        url, h, _ = self.register(stub)
        return url, h


def route_ats(stubs: list[JobStub], registry: Mapping[str, Source]) -> list[JobStub]:
    """Aggregators, boards, company plugins and Telegram label their jobs with their own name, but
    the application often lives on a known ATS. When a non-ATS source's `apply_url` is on a
    registered ATS, set `ats` to it (`source` stays), so the apply stage picks that handler."""
    out = []
    for st in stubs:
        src = registry.get(st.source)
        found = None
        if src and src.kind != "ats" and st.apply_url:
            found = detect(st.apply_url, registry.values())
        out.append(st.model_copy(update={"ats": found[0]}) if found else st)
    return out


def _apply_data(stub: JobStub) -> dict[str, Any]:
    return stub.model_dump(
        mode="json",
        include={"apply_url", "remote", "salary_min", "salary_max", "salary_currency",
                 "salary_interval", "extra"},
    )  # fmt: skip


def _upgrade(s: Session, deduper: Deduper, known: Known, st: JobStub) -> None:
    """Replace a still-`discovered` job's source and apply details with the better copy's.
    Title, company and location stay, so the stored dedupe hash remains valid."""
    job = s.get(Job, known.job_id) if known.job_id is not None else None
    if job is None or job.state != JobState.discovered:
        return
    url = normalize_url(st.url)
    logger.debug("upgrading job {} from {} to {}: {}", job.id, job.source, st.source, url)
    job.source, job.url, job.ats = st.source, url, st.ats
    if len(st.description) > len(job.description):
        job.description = st.description
    job.data = {**job.data, **{k: v for k, v in _apply_data(st).items() if v not in (None, {})}}
    known.priority = deduper.priority(st.source)
    deduper.urls[url] = known  # the old URL stays registered: it is still a duplicate


def store_page(
    db: sessionmaker[Session],
    run_id: int,
    key: str,
    page: int,
    stubs: list[JobStub],
    deduper: Deduper,
) -> int:
    """Insert new jobs and advance the checkpoint in one transaction. Returns new count.
    A duplicate from a higher-priority source upgrades the stored copy (not counted as new)."""
    new = 0
    with db.begin() as s:
        for st in stubs:
            known = deduper.lookup(st)
            if known is not None:
                if deduper.priority(st.source) < known.priority:
                    _upgrade(s, deduper, known, st)
                continue
            url, h, known = deduper.register(st)
            job = Job(
                run_id=run_id,
                source=st.source,
                url=url,
                title=st.title,
                company=st.company,
                location=st.location,
                description=st.description,
                posted_at=st.posted_at,
                ats=st.ats,
                dedupe_hash=h,
                data=_apply_data(st),
            )
            s.add(job)
            s.flush()  # the id lets a later, better duplicate find this row
            known.job_id = job.id
            new += 1
        cp = s.scalars(select(SourceCheckpoint).filter_by(run_id=run_id, key=key)).first()
        if cp is None:
            cp = SourceCheckpoint(run_id=run_id, key=key)
            s.add(cp)
        cp.next_page = page + 1
    return new


def mark_task(db: sessionmaker[Session], run_id: int, key: str, error: str | None) -> None:
    with db.begin() as s:
        cp = s.scalars(select(SourceCheckpoint).filter_by(run_id=run_id, key=key)).first()
        if cp is None:
            cp = SourceCheckpoint(run_id=run_id, key=key)
            s.add(cp)
        cp.done, cp.error = True, error
