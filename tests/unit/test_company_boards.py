"""Group F: the bundled company boards, the name -> board resolver, the dead-board rule and
the repost guard. No live calls: HTTP is an httpx.MockTransport."""

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from test_api import SAME_ORIGIN, client  # noqa: F401
from typer.testing import CliRunner

from linkit_all import cli
from linkit_all.core.config import get_settings
from linkit_all.core.db import init_db
from linkit_all.core.models import Board, Job, JobSighting, Run
from linkit_all.core.search import SearchConfig, load_search
from linkit_all.core.sightings import repost_listings, sighting_stats
from linkit_all.matching.trust.ghost import REPOST_URLS, ghost_histories
from linkit_all.sources import registry, resolve
from linkit_all.sources.discovery import (
    MAX_FAILURES,
    board_tasks,
    note_crawl,
    seed_boards,
    seed_list,
    upsert_boards,
)

runner = CliRunner()


@pytest.fixture
def db(tmp_path: Path) -> sessionmaker[Session]:
    return init_db(tmp_path / "t.db")


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the CLI at a temp data dir, never the user's own."""
    monkeypatch.setenv("LINKIT_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    yield tmp_path / "data"  # type: ignore[misc]
    get_settings.cache_clear()


# ---- F1 seed boards ---------------------------------------------------------------------------


def test_seed_list_is_deduped_and_only_names_our_plugins() -> None:
    rows = seed_list()
    assert len(rows) >= 130
    assert all(set(r) == {"ats", "slug", "name"} and all(r.values()) for r in rows)
    keys = [(r["ats"], r["slug"].lower()) for r in rows]
    assert len(keys) == len(set(keys))
    known = {n for n, s in registry().items() if s.kind == "ats"}
    assert {r["ats"] for r in rows} <= known


def test_seed_boards_twice_adds_nothing_the_second_time(db: sessionmaker[Session]) -> None:
    assert seed_boards(db) == len(seed_list())
    assert seed_boards(db) == 0
    with db() as s:
        assert set(s.scalars(select(Board.source))) == {"career-ops"}
    # stored, but not crawled until the user asks for discovered boards
    assert board_tasks(db, SearchConfig(), registry(), set()) == []


@pytest.mark.usefixtures("data_dir")
def test_seed_boards_command_uses_the_app_database() -> None:
    first = runner.invoke(cli.app, ["seed-boards"])
    second = runner.invoke(cli.app, ["seed-boards"])
    assert first.exit_code == 0 and first.output.startswith(f"{len(seed_list())} new boards")
    assert second.exit_code == 0 and second.output.startswith("0 new boards")


def test_suggested_companies_api(client: TestClient) -> None:  # noqa: F811
    rows = client.get("/api/suggest/companies").json()
    assert len(rows) == len(seed_list())
    row = next(r for r in rows if r["value"] == "greenhouse:anthropic")
    assert row == {"value": "greenhouse:anthropic", "name": "Anthropic", "ats": "greenhouse",
                   "label": "Anthropic · Greenhouse"}  # fmt: skip
    # a suggestion is not a company of the user's until it is ticked
    assert client.get("/api/search").json()["sources"]["companies"] == []


# ---- F2 resolver ------------------------------------------------------------------------------

GH_JOB = {"id": 1, "title": "Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
          "company_name": "Acme", "location": {"name": "Remote"}}  # fmt: skip


def fake_ats(req: httpx.Request) -> httpx.Response:
    """Only Greenhouse knows "acme"; every other board on every ATS is a 404."""
    if req.url.host == "boards-api.greenhouse.io" and req.url.path == "/v1/boards/acme/jobs":
        return httpx.Response(200, json={"jobs": [GH_JOB]})
    return httpx.Response(404)


@pytest.fixture
def ats(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolve, "_TRANSPORT", httpx.MockTransport(fake_ats))


def test_slug_guesses() -> None:
    assert resolve.slug_guesses("Scale AI, Inc.") == ["scale-ai", "scaleai"]
    assert resolve.slug_guesses("Stripe") == ["stripe"]
    assert resolve.slug_guesses("  ") == []


@pytest.mark.usefixtures("ats")
def test_resolver_finds_greenhouse_and_lists_the_rest_for_follow_up() -> None:
    found, missing = asyncio.run(resolve.resolve(registry(), ["Acme", "Nowhere Corp"]))
    assert [(b.value, b.label, b.jobs) for b in found["Acme"]] == [
        ("greenhouse:acme", "Acme · Greenhouse", 1)
    ]
    assert missing == ["Nowhere Corp"]


@pytest.mark.usefixtures("ats")
def test_find_route_previews_and_saves_nothing(client: TestClient) -> None:  # noqa: F811
    r = client.post("/api/sources/find", json={"value": "Acme"}, headers=SAME_ORIGIN)
    assert r.status_code == 200
    assert r.json()["boards"] == [{"value": "greenhouse:acme", "label": "Acme · Greenhouse",
                                   "ats": "greenhouse", "name": "Acme", "jobs": 1}]  # fmt: skip
    r = client.post("/api/sources/find", json={"value": "Nowhere Corp"}, headers=SAME_ORIGIN)
    assert r.json() == {"boards": []}
    assert client.get("/api/search").json()["sources"]["companies"] == []


@pytest.mark.usefixtures("ats", "data_dir")
def test_find_board_command_previews_then_adds() -> None:
    preview = runner.invoke(cli.app, ["find-board", "Acme", "Nowhere Corp"])
    saved = load_search(init_db(get_settings().db_path))
    assert saved is None or saved.sources.companies == []
    added = runner.invoke(cli.app, ["find-board", "Acme", "--add"])
    cfg = load_search(init_db(get_settings().db_path))
    assert "Acme · Greenhouse, 1 jobs (greenhouse:acme)" in preview.output
    assert "Nowhere Corp: no board found" in preview.output and "Nothing saved" in preview.output
    assert "added" in added.output and cfg is not None
    assert cfg.sources.companies == ["greenhouse:acme"]
    assert cfg.sources.company_labels == {"greenhouse:acme": "Acme · Greenhouse"}


# ---- F3 dead-board rule -----------------------------------------------------------------------


def board(db: sessionmaker[Session], slug: str) -> Board:
    with db() as s:
        return s.scalars(select(Board).filter_by(slug=slug)).one()


def test_only_gone_answers_switch_a_board_off(db: sessionmaker[Session]) -> None:
    upsert_boards(db, "greenhouse", ["throttled", "flaky", "gone", "back"], "commoncrawl")
    for _ in range(MAX_FAILURES):
        note_crawl(db, "greenhouse", "throttled", 0, False, 429)
        note_crawl(db, "greenhouse", "flaky", 0, False)  # timeout, DNS: no status at all
        note_crawl(db, "greenhouse", "gone", 0, False, 404)
    assert (board(db, "throttled").active, board(db, "throttled").failures) == (True, 0)
    assert (board(db, "flaky").active, board(db, "flaky").failures) == (True, 0)
    assert (board(db, "gone").active, board(db, "gone").failures) == (False, MAX_FAILURES)
    assert board(db, "throttled").last_crawled_at is not None  # still takes its turn in rotation

    for status in (410, 404, 503, 404):  # a 5xx in between neither counts nor resets
        note_crawl(db, "greenhouse", "back", 0, False, status)
    assert board(db, "back").failures == 3
    note_crawl(db, "greenhouse", "back", 7, True)
    assert (board(db, "back").failures, board(db, "back").last_jobs) == (0, 7)


# ---- F4 repost guard --------------------------------------------------------------------------

DAY = date(2026, 6, 1)


def test_repost_listings() -> None:
    assert repost_listings([]) == 0
    assert repost_listings([DAY]) == 1
    assert repost_listings([DAY, DAY]) == 1  # two URLs in one sweep: sibling requisitions
    assert repost_listings([DAY, DAY + timedelta(days=20)]) == 2  # came back under a new URL
    assert repost_listings([DAY, DAY + timedelta(days=91)]) == 1  # too far apart to be one job
    assert repost_listings([DAY, DAY + timedelta(days=91), DAY + timedelta(days=120)]) == 2


def test_sibling_requisitions_are_not_a_repost(db: sessionmaker[Session]) -> None:
    morning = datetime(2026, 6, 1, 8)
    with db.begin() as s:
        runs = [Run() for _ in range(3)]
        siblings, repost = (
            Job(source="t", url=f"https://x.io/{n}", title="T", company="Acme", dedupe_hash=n)
            for n in ("sib", "rep")
        )
        s.add_all([*runs, siblings, repost])
        s.flush()

        def seen(job: Job, run: Run, at: datetime, url: str) -> None:
            s.add(JobSighting(job_id=job.id, run_id=run.id, seen_at=at, url=url, source="t"))

        # two ATS ids of one title, both seen on the same day (morning and evening run)
        seen(siblings, runs[0], morning, "https://ats.io/jobs/101")
        seen(siblings, runs[1], morning + timedelta(hours=9), "https://ats.io/jobs/102")
        # the same job back under a new id three weeks later
        seen(repost, runs[0], morning, "https://ats.io/jobs/201")
        seen(repost, runs[2], morning + timedelta(days=21), "https://ats.io/jobs/202")
        ids = (siblings.id, repost.id)
    with db() as s:
        assert s.scalar(select(func.count(JobSighting.url.distinct()))) == 4
        stats = sighting_stats(s, ids)
        assert (stats[ids[0]].urls, stats[ids[1]].urls) == (1, 2)
        hist = ghost_histories(s, [s.get_one(Job, i) for i in ids])
    assert hist[ids[0]].urls_seen < REPOST_URLS <= hist[ids[1]].urls_seen
