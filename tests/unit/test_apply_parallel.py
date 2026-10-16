"""apply_jobs: different sites run side by side; the pause is only between jobs of one site."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker
from test_apply_skip import NoAI
from test_matching import fake_embed

from linkit_all.apply import browser as browser_module
from linkit_all.apply import runner
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobState
from linkit_all.core.search import SearchConfig

# (ats, apply_url): two lever jobs on different boards, two greenhouse, two on one host, one other
ROWS = [
    ("lever", "https://jobs.lever.co/a/1"),
    ("greenhouse", "https://boards.greenhouse.io/x/jobs/1"),
    ("lever", "https://jobs.lever.co/b/2"),
    ("workday", "https://acme.wd1.myworkdayjobs.com/x/1"),
    ("greenhouse", "https://boards.greenhouse.io/y/jobs/2"),
    ("workday", "https://Acme.wd1.myworkdayjobs.com/x/2"),
]


class Fake:
    def __init__(self, db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
        self.running: set[int] = set()
        self.peak = 0
        self.order: list[int] = []
        self.overlap_same_site = False
        self.pauses: list[tuple[float, float]] = []
        self.block_on: int | None = None
        self.cancelled: list[int] = []
        self.sites: dict[int, str] = {}
        with db() as s:
            for j in s.query(Job):
                self.sites[j.id] = runner.site_key(j)

        class PW:
            async def stop(self) -> None: ...

        class Starter:
            async def start(self) -> PW:
                return PW()

        monkeypatch.setattr(runner, "async_playwright", Starter)
        monkeypatch.setattr(runner.Applier, "pick_jobs", lambda _self: sorted(self.sites))
        monkeypatch.setattr(runner.Applier, "apply", self.apply)

        def uniform(lo: float, hi: float) -> float:
            self.pauses.append((lo, hi))
            return 0.0

        monkeypatch.setattr(runner.random, "uniform", uniform)

    async def apply(self, job_id: int) -> runner.Outcome:
        site = self.sites[job_id]
        if any(self.sites[r] == site for r in self.running):
            self.overlap_same_site = True
        self.running.add(job_id)
        self.peak = max(self.peak, len(self.running))
        self.order.append(job_id)
        try:
            await asyncio.sleep(0.02)
            if job_id == self.block_on:
                raise runner.ApplyBlocked("usage limit")
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            self.cancelled.append(job_id)
            raise
        finally:
            self.running.discard(job_id)
        return runner.Outcome("dry_run" if job_id % 2 else "skipped", "")


def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Settings, Any, Fake]:
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    with db.begin() as s:
        for i, (ats, url) in enumerate(ROWS):
            s.add(Job(source="x", url=url, title="Dev", company=f"C{i}", location="", description="",
                      ats=ats, dedupe_hash=str(i), score=9 - i, state=JobState.queued_apply,
                      data={"apply_url": url}))  # fmt: skip
    return settings, db, Fake(db, monkeypatch)


def run(settings: Settings, db: Any, **apply: Any) -> dict[str, int]:
    cfg = SearchConfig.model_validate({"apply": {"min_pause_s": 7, "max_pause_s": 9, **apply}})
    return asyncio.run(runner.apply_jobs(db, settings, cfg, NoAI(), fake_embed))


def test_site_key_is_the_ats_or_the_host() -> None:
    def key(ats: str | None, url: str) -> str:
        job = Job(source="x", url=url, title="", company="", location="", description="",
                  ats=ats, dedupe_hash="h", data={})  # fmt: skip
        return runner.site_key(job)

    assert key("lever", "https://jobs.lever.co/a/1") == key("lever", "https://jobs.lever.co/b/2")
    assert key("workday", "https://Acme.wd1.myworkdayjobs.com/x") == "acme.wd1.myworkdayjobs.com"
    assert key(None, "https://careers.acme.com/1") == "careers.acme.com"
    assert key(None, "") == "unknown"


def test_sites_run_side_by_side_but_one_site_never_overlaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, db, fake = setup(tmp_path, monkeypatch)
    counts = run(settings, db, parallel_sites=3, live=True)
    assert fake.peak == 3 and not fake.overlap_same_site
    assert sorted(fake.order) == [1, 2, 3, 4, 5, 6]
    assert len(fake.pauses) == 3  # six jobs on three sites: one pause per site
    assert set(fake.pauses) == {(7, 9)}
    assert counts == {"dry_run": 3, "applied": 0, "needs_user": 0, "failed": 0, "skipped": 3}


def test_parallel_sites_limits_how_many_sites_run_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, db, fake = setup(tmp_path, monkeypatch)
    run(settings, db, parallel_sites=2)
    assert fake.peak == 2 and not fake.overlap_same_site and len(fake.pauses) == 3


def test_one_parallel_site_is_sequential_with_pauses_inside_each_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, db, fake = setup(tmp_path, monkeypatch)
    run(settings, db, parallel_sites=1)
    assert fake.peak == 1
    # one site after the other, best-scored site first, each site's jobs in score order
    assert fake.order == [1, 3, 2, 5, 4, 6]
    assert len(fake.pauses) == 3


def test_dry_run_uses_the_short_pause(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, db, fake = setup(tmp_path, monkeypatch)
    run(settings, db, live=False)
    assert set(fake.pauses) == {(2, 5)}


def test_apply_blocked_in_one_worker_stops_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, db, fake = setup(tmp_path, monkeypatch)
    fake.block_on = 2  # the greenhouse job: the other two sites are mid-application
    with pytest.raises(runner.ApplyBlocked, match="usage limit"):
        run(settings, db, parallel_sites=3)
    assert sorted(fake.cancelled) == [1, 4]
    assert sorted(fake.order) == [1, 2, 4]  # nothing new started after the block


def test_live_frame_file_stays_until_the_last_page_stops(tmp_path: Path) -> None:
    out = tmp_path / "live" / "current.jpg"

    class Page:
        async def screenshot(self, **_: Any) -> bytes:
            return b"jpeg"

    async def go() -> None:
        a = asyncio.create_task(browser_module.live_frames(Page(), out, every=0.01))  # type: ignore[arg-type]
        b = asyncio.create_task(browser_module.live_frames(Page(), out, every=0.01))  # type: ignore[arg-type]
        for _ in range(100):
            if out.exists():
                break
            await asyncio.sleep(0.01)
        a.cancel()
        await asyncio.gather(a, return_exceptions=True)
        await asyncio.sleep(0.05)
        assert out.exists()  # b is still working
        b.cancel()
        await asyncio.gather(b, return_exceptions=True)

    asyncio.run(go())
    assert not out.exists() and not list(out.parent.glob("*.tmp"))
