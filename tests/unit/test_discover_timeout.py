"""A source that stops answering must not freeze discover; its task stays undone. jobspy runs in a
child process that is killed on timeout or cancel."""

import asyncio
import multiprocessing
import os
import signal
import time
from collections.abc import AsyncIterator, Iterator
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from linkit_all.core.db import init_db
from linkit_all.core.models import Job, SourceCheckpoint
from linkit_all.core.runs import current_run
from linkit_all.core.search import SearchConfig
from linkit_all.sources import base, jobspy_sites
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http, make_client
from linkit_all.sources.jobspy_sites import JobSpySite, _in_child
from linkit_all.sources.runner import discover
from linkit_all.sources.wuzzuf import Wuzzuf


# Scrapers run in a spawned child, so they must be module-level (picklable).
def blocked_scrape(marker: str = "", **_: Any) -> list[dict[str, Any]]:
    if marker:
        Path(marker).write_text("started")
    time.sleep(120)  # a library that never returns
    return []


def good_scrape(n: int = 2, **_: Any) -> list[dict[str, Any]]:
    return [{"job_url": f"https://x.io/{i}", "title": "Dev"} for i in range(n)]


def raising_scrape(**_: Any) -> list[dict[str, Any]]:
    raise RuntimeError("LinkedIn response status code 429")


class Unpicklable(Exception):
    def __init__(self) -> None:
        super().__init__("boom")
        self.fn = lambda: None  # a lambda cannot be pickled


class NoRoundTrip(Exception):
    def __init__(self, a: str, b: str) -> None:
        super().__init__(a)  # pickles, but unpickling calls __init__(a) and fails


def raising_unpicklable(**_: Any) -> list[dict[str, Any]]:
    raise Unpicklable


def raising_no_round_trip(**_: Any) -> list[dict[str, Any]]:
    raise NoRoundTrip("first", "second")


def dies_hard(**_: Any) -> list[dict[str, Any]]:
    os._exit(3)


def exits(**_: Any) -> list[dict[str, Any]]:
    raise SystemExit("library said stop")


def interrupted(**_: Any) -> list[dict[str, Any]]:
    raise KeyboardInterrupt("ctrl-c in the child")


def sigint_ignored(**_: Any) -> bool:
    return signal.getsignal(signal.SIGINT) == signal.SIG_IGN


class Multi(Source):
    """Three tasks of one source, run one at a time like JobSpySite. The first call hangs or
    fails; any later call would store a job, so a wrongly started task shows up in the db."""

    kind = "ats"
    parallel = 1

    def __init__(self, name: str, first: str = "") -> None:
        self.name, self.first, self.calls = name, first, 0

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, f"{self.name}:q{i}") for i in range(3)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        self.calls += 1
        if self.calls == 1 and self.first == "hang":
            await asyncio.Event().wait()
        if self.calls == 1 and self.first == "error":
            raise ValueError("bad page")
        url = f"https://{self.name}.io/{task.key}"
        yield [JobStub(source=self.name, url=url, title="Dev", company=task.key)]


class Fake(Source):
    kind = "ats"

    def __init__(self, name: str, hang: bool = False, own_timeout: bool = False) -> None:
        self.name, self.hang, self.own_timeout = name, hang, own_timeout

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, f"{self.name}:q")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if self.hang:
            await asyncio.Event().wait()
        if self.own_timeout:
            raise TimeoutError("the server said slow down")
        yield [JobStub(source=self.name, url="https://ok.io/1", title="Dev", company="Acme")]


@pytest.fixture
def procs(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[BaseProcess]]:
    """Every child process _in_child starts, so a test can ask whether it is still alive."""
    made: list[BaseProcess] = []
    real = multiprocessing.get_context("spawn")

    class Ctx:
        Pipe = staticmethod(real.Pipe)

        def Process(self, *a: Any, **k: Any) -> BaseProcess:
            p = real.Process(*a, **k)
            made.append(p)
            return p

    monkeypatch.setattr(jobspy_sites.multiprocessing, "get_context", lambda _method: Ctx())
    yield made
    for p in made:  # never leave a child behind, even when an assertion failed
        if not dead(p):
            p.kill()


def dead(p: BaseProcess) -> bool:
    """_in_child closes the process object once the child is gone, and a closed one raises."""
    try:
        return not p.is_alive()
    except ValueError:
        return True


def run_discover(tmp_path: Path, registry: dict[str, Source], cfg: SearchConfig) -> Any:
    db = init_db(tmp_path / "t.db")

    async def go() -> Any:
        async with make_client() as client:
            run_id = current_run(db)
            stats = await asyncio.wait_for(
                discover(db, cfg, run_id, Http(client), registry), timeout=15
            )
            return db, run_id, stats

    return asyncio.run(go())


def undone_and_stored(db: Any, run_id: int, key: str) -> tuple[bool, int]:
    with db() as s:
        cp = s.scalars(select(SourceCheckpoint).filter_by(run_id=run_id, key=key)).first()
        return cp is not None and cp.done, len(s.scalars(select(Job)).all())


def jobspy_cfg() -> SearchConfig:
    return SearchConfig.model_validate(
        {"search": {"queries": ["x"], "locations": [""]}, "sources": {"regional": ["bayt"]}}
    )


def test_stuck_source_times_out_and_others_still_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(base, "PAGE_TIMEOUT", 0.2)
    registry: dict[str, Source] = {"stuck": Fake("stuck", hang=True), "fine": Fake("fine")}
    db, run_id, stats = run_discover(tmp_path, registry, SearchConfig())
    assert "timed out" in stats.errors["stuck:q"]
    assert "fine:q" not in stats.errors and stats.new == 1
    assert undone_and_stored(db, run_id, "stuck:q") == (False, 1)  # a resume retries it
    assert undone_and_stored(db, run_id, "fine:q")[0]


def test_after_a_timeout_the_sources_other_tasks_are_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(base, "PAGE_TIMEOUT", 0.2)
    a = Multi("a", first="hang")
    registry: dict[str, Source] = {"a": a, "b": Fake("b")}
    db, run_id, stats = run_discover(tmp_path, registry, SearchConfig())
    assert "timed out" in stats.errors["a:q0"]
    for key in ("a:q1", "a:q2"):
        assert "timed out earlier in this run" in stats.errors[key] and "a" in stats.errors[key]
        assert undone_and_stored(db, run_id, key)[0] is False
    assert a.calls == 1  # the skipped tasks never reached search()
    assert "b:q" not in stats.errors and undone_and_stored(db, run_id, "b:q") == (True, 1)


def test_an_ordinary_error_does_not_skip_the_sources_other_tasks(tmp_path: Path) -> None:
    a = Multi("a", first="error")
    db, run_id, stats = run_discover(tmp_path, {"a": a}, SearchConfig())
    assert "ValueError" in stats.errors["a:q0"] and set(stats.errors) == {"a:q0"}
    assert a.calls == 3 and stats.tasks_done == 2
    assert undone_and_stored(db, run_id, "a:q2") == (True, 2)


def test_a_source_own_timeout_error_keeps_its_message(tmp_path: Path) -> None:
    registry: dict[str, Source] = {"slow": Fake("slow", own_timeout=True)}
    _, _, stats = run_discover(tmp_path, registry, SearchConfig())
    assert "the server said slow down" in stats.errors["slow:q"]
    assert "timed out" not in stats.errors["slow:q"]


def test_blocked_jobspy_scrape_times_out_and_its_process_is_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, procs: list[BaseProcess]
) -> None:
    monkeypatch.setattr(JobSpySite, "page_timeout", lambda self, task: 1.5)
    site = JobSpySite("bayt", blocked_scrape)
    db, run_id, stats = run_discover(tmp_path, {"bayt": site}, jobspy_cfg())
    assert "timed out" in stats.errors["bayt:x@"]
    assert undone_and_stored(db, run_id, "bayt:x@") == (False, 0)
    assert len(procs) == 1 and dead(procs[0])  # killed, not left blocking
    assert not site._lock.locked()


def test_cancelling_a_blocked_scrape_kills_its_process(
    tmp_path: Path, procs: list[BaseProcess]
) -> None:
    marker = tmp_path / "started"

    async def go() -> None:
        task = asyncio.create_task(_in_child(blocked_scrape, marker=str(marker)))
        for _ in range(300):  # wait until the child is really inside the blocked scraper
            if marker.exists():
                break
            await asyncio.sleep(0.1)
        assert marker.exists()
        task.cancel()  # what Ctrl-C does to the awaiting task
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert len(procs) == 1 and dead(procs[0])


def test_child_result_comes_back_intact() -> None:
    rows = asyncio.run(_in_child(good_scrape, n=3))
    assert [r["job_url"] for r in rows] == [f"https://x.io/{i}" for i in range(3)]


@pytest.mark.parametrize(
    ("fn", "match"),
    [
        (raising_scrape, "429"),  # same type and text as the in-process scraper
        (raising_unpicklable, "Unpicklable: boom"),  # cannot cross: type name and message
        (raising_no_round_trip, "NoRoundTrip: first"),
        (dies_hard, "died"),
    ],
)
def test_child_errors_reach_the_caller(fn: Any, match: str) -> None:
    with pytest.raises(RuntimeError, match=match):
        asyncio.run(_in_child(fn))


@pytest.mark.parametrize(
    ("fn", "name"), [(exits, "SystemExit"), (interrupted, "KeyboardInterrupt")]
)
def test_child_exit_signals_reach_the_caller_as_runtime_error(fn: Any, name: str) -> None:
    with pytest.raises(RuntimeError, match=name):  # a raw KeyboardInterrupt would escape here
        asyncio.run(_in_child(fn))


def test_child_ignores_ctrl_c() -> None:
    assert asyncio.run(_in_child(sigint_ignored)) is True


def test_page_timeout_grows_with_the_task_size() -> None:
    site = JobSpySite("linkedin", good_scrape)
    small, normal, big = (site.page_timeout(Task("linkedin", "k", limit=n)) for n in (5, 200, 1000))
    assert base.PAGE_TIMEOUT <= small < normal < big
    assert normal > 3600 and big > 3 * normal  # 20 s per job: a full 1000-job task is hours
    assert Wuzzuf().page_timeout(Task("wuzzuf", "k")) >= base.PAGE_TIMEOUT
