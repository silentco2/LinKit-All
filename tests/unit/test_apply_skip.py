"""Jobs the applier can't handle are skipped before any tailoring (CLAUDE.md §4)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from test_matching import fake_embed

from linkit_all.apply import runner
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobState
from linkit_all.core.search import SearchConfig
from linkit_all.providers.base import LLMProvider


class NoAI(LLMProvider):
    name = "none"

    def __init__(self) -> None:
        super().__init__("none")

    async def _call(self, prompt: str) -> str:
        raise AssertionError("no AI call expected")


@pytest.mark.parametrize(
    ("ats", "data"),
    [
        ("greenhouse", {"apply_url": "https://careers.acme.com/jobs/1"}),  # info is None
        ("workday", {}),  # no handler
    ],
)
def test_unappliable_job_is_skipped_without_tailoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ats: str, data: dict[str, Any]
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    with db.begin() as s:
        job = Job(source="x", url="https://x/1", title="Dev", company="Acme", location="",
                  description="", ats=ats, dedupe_hash="h", state=JobState.queued_apply, data=data)  # fmt: skip
        s.add(job)
        s.flush()
        job_id = job.id
    calls: list[int] = []

    async def spy(*args: Any, **kwargs: Any) -> None:
        calls.append(args[1])

    monkeypatch.setattr(runner, "tailor_job", spy)
    applier = runner.Applier(db, settings, SearchConfig(), NoAI(), fake_embed)

    out = asyncio.run(applier.apply(job_id))
    assert out.status == "skipped"
    assert calls == []
