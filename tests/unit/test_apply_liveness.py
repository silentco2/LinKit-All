"""A posting that vanished from its ATS is skipped before any tailoring (G6)."""

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from test_matching import fake_embed

from linkit_all.apply import runner
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobEvent, JobState
from linkit_all.core.search import SearchConfig
from linkit_all.providers.base import LLMProvider
from linkit_all.sources.http import Http


class NoAI(LLMProvider):
    name = "none"

    def __init__(self) -> None:
        super().__init__("none")

    async def _call(self, prompt: str) -> str:
        raise AssertionError("no AI call expected")


class Stop(Exception):
    """Raised by the tailor spy: the job got past the liveness check."""


ASHBY_BOARD = {"jobs": [{"id": "abc", "isListed": True}, {"id": "hidden", "isListed": False}]}

CASES: dict[str, dict[str, Any]] = {
    "greenhouse": {"board": "acme", "id": 42},
    "lever": {"board": "acme", "id": "abc"},
    "ashby": {"board": "acme", "id": "abc"},
}


def answering(status: int | None) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        if status is None:
            raise httpx.ConnectError("down")
        if "ashbyhq" in request.url.host:
            return httpx.Response(status, json=ASHBY_BOARD)
        return httpx.Response(status, json={})

    return httpx.MockTransport(respond)


def run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ats: str,
    extra: dict[str, Any],
    transport: httpx.MockTransport,
) -> tuple[str, int, list[JobEvent], JobState]:
    """-> (outcome status or 'tailoring', tailor calls, job events, final state)"""
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    with db.begin() as s:
        job = Job(source=ats, url="https://x/1", title="Dev", company="Acme", location="",
                  description="", ats=ats, dedupe_hash="h", state=JobState.queued_apply,
                  data={"extra": extra})  # fmt: skip
        s.add(job)
        s.flush()
        job_id = job.id
    calls: list[int] = []

    async def spy(*args: Any, **kwargs: Any) -> None:
        calls.append(args[1])
        raise Stop

    monkeypatch.setattr(runner, "tailor_job", spy)

    async def go() -> str:
        async with httpx.AsyncClient(transport=transport) as client:
            http = Http(client, attempts=1)
            applier = runner.Applier(db, settings, SearchConfig(), NoAI(), fake_embed, http=http)
            try:
                return (await applier.apply(job_id)).status
            except Stop:
                return "tailoring"

    status = asyncio.run(go())
    with db() as s:
        events = list(s.scalars(select(JobEvent).where(JobEvent.job_id == job_id)))
        state = s.get_one(Job, job_id).state
    return status, len(calls), events, state


@pytest.mark.parametrize("ats", CASES)
def test_live_posting_continues_to_tailoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ats: str
) -> None:
    status, calls, _, state = run(tmp_path, monkeypatch, ats, CASES[ats], answering(200))
    assert (status, calls, state) == ("tailoring", 1, JobState.queued_apply)


@pytest.mark.parametrize("ats", ["greenhouse", "lever"])
@pytest.mark.parametrize("gone", [404, 410])
def test_vanished_posting_is_skipped_without_tailoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ats: str, gone: int
) -> None:
    status, calls, events, state = run(tmp_path, monkeypatch, ats, CASES[ats], answering(gone))
    assert (status, calls, state) == ("skipped", 0, JobState.skipped)
    assert events[-1].code == "job_closed"
    assert events[-1].message == f"The posting is no longer open on {ats}"


@pytest.mark.parametrize("job_id", ["gone", "hidden"])
def test_ashby_posting_missing_from_the_board_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, job_id: str
) -> None:
    extra = {"board": "acme", "id": job_id}
    status, calls, events, state = run(tmp_path, monkeypatch, "ashby", extra, answering(200))
    assert (status, calls, state) == ("skipped", 0, JobState.skipped)
    assert events[-1].code == "job_closed"


@pytest.mark.parametrize("ats", CASES)
@pytest.mark.parametrize("answer", [None, 429, 500, 503, 403])
def test_unknown_answer_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ats: str, answer: int | None
) -> None:
    status, calls, _, state = run(tmp_path, monkeypatch, ats, CASES[ats], answering(answer))
    assert (status, calls, state) == ("tailoring", 1, JobState.queued_apply)


def test_lever_posting_on_the_eu_instance_is_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if request.url.host == "api.lever.co" else 200, json={})

    transport = httpx.MockTransport(respond)
    status, calls, _, _ = run(tmp_path, monkeypatch, "lever", CASES["lever"], transport)
    assert (status, calls) == ("tailoring", 1)


def test_ats_without_a_liveness_check_continues_without_a_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    transport = httpx.MockTransport(respond)
    # workday: has a plugin, but no is_live (default None)
    status, calls, _, state = run(tmp_path, monkeypatch, "workday", {}, transport)
    assert (status, calls, state) == ("tailoring", 1, JobState.queued_apply)
