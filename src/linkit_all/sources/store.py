"""Dedupe and persist job stubs; a page and its checkpoint commit together."""

from collections import defaultdict

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import Job, SourceCheckpoint
from linkit_all.sources.base import JobStub
from linkit_all.sources.text import job_hash, norm, norm_company, normalize_url


class Deduper:
    """Exact normalized URL, exact title/company/location hash, then fuzzy title per company.

    ponytail: same-title openings at one company and location collapse into one job; fine
    while one_per_company is the default, revisit if that changes.
    """

    def __init__(self, session: Session) -> None:
        rows = session.execute(
            select(Job.url, Job.dedupe_hash, Job.title, Job.company, Job.location)
        ).all()
        self.urls = {r.url for r in rows}
        self.hashes = {r.dedupe_hash for r in rows}
        self.by_company: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
        for r in rows:
            self.by_company[norm_company(r.company)].append((norm(r.title), norm(r.location)))

    def add(self, stub: JobStub) -> tuple[str, str] | None:
        """(normalized url, hash) if the stub is new, else None."""
        url = normalize_url(stub.url)
        h = job_hash(stub.title, stub.company, stub.location)
        if url in self.urls or h in self.hashes:
            return None
        title, loc = norm(stub.title), norm(stub.location)
        same_company = self.by_company[norm_company(stub.company)]
        for t, other_loc in same_company:
            if fuzz.token_sort_ratio(title, t) >= 92 and (
                not loc or not other_loc or fuzz.token_set_ratio(loc, other_loc) >= 85
            ):
                return None
        self.urls.add(url)
        self.hashes.add(h)
        same_company.append((title, loc))
        return url, h


def store_page(
    db: sessionmaker[Session],
    run_id: int,
    key: str,
    page: int,
    stubs: list[JobStub],
    deduper: Deduper,
) -> int:
    """Insert new jobs and advance the checkpoint in one transaction. Returns new count."""
    new = 0
    with db.begin() as s:
        for st in stubs:
            if (found := deduper.add(st)) is None:
                continue
            url, h = found
            extra = st.model_dump(
                mode="json",
                include={"apply_url", "remote", "salary_min", "salary_max", "salary_currency",
                         "salary_interval", "extra"},
            )  # fmt: skip
            s.add(
                Job(
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
                    data=extra,
                )
            )
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
