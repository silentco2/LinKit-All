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
    ("ats", "data", "url", "generic"),
    [
        ("greenhouse", {"apply_url": "https://careers.acme.com/jobs/1"}, "https://x/1", True),
        ("workday", {}, "https://x/1", False),  # no handler, generic agent off
        ("workday", {}, "", True),  # no handler, nothing to open
        ("workday", {"apply_url": "mailto:jobs@acme.com"}, "", True),  # not a web page
    ],
)
def test_unappliable_job_is_skipped_without_tailoring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ats: str,
    data: dict[str, Any],
    url: str,
    generic: bool,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    with db.begin() as s:
        job = Job(source="x", url=url, title="Dev", company="Acme", location="",
                  description="", ats=ats, dedupe_hash="h", state=JobState.queued_apply, data=data)  # fmt: skip
        s.add(job)
        s.flush()
        job_id = job.id
    calls: list[int] = []

    async def spy(*args: Any, **kwargs: Any) -> None:
        calls.append(args[1])

    monkeypatch.setattr(runner, "tailor_job", spy)
    cfg = SearchConfig.model_validate({"apply": {"generic_agent": generic}})
    applier = runner.Applier(db, settings, cfg, NoAI(), fake_embed)

    out = asyncio.run(applier.apply(job_id))
    assert out.status == "skipped"
    assert calls == []


def test_pick_jobs_includes_handlerless_jobs_only_with_the_generic_agent(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    rows = [  # (ats, url, score)
        ("lever", "https://jobs.lever.co/a/1", 5),
        ("workday", "https://acme.wd1.myworkdayjobs.com/x/1", 9),
        (None, "https://careers.acme.com/1", 8),
        ("workday", "", 10),  # nothing to open
        ("icims", "ftp://acme.com/1", 10),  # not a web page
    ]
    with db.begin() as s:
        for i, (ats, url, score) in enumerate(rows):
            s.add(Job(source="x", url=url, title="Dev", company=f"C{i}", location="", description="",
                      ats=ats, dedupe_hash=str(i), score=score, state=JobState.queued_apply, data={}))  # fmt: skip

    def picked(generic: bool) -> list[str]:
        cfg = SearchConfig.model_validate({"apply": {"generic_agent": generic}})
        applier = runner.Applier(db, settings, cfg, NoAI(), fake_embed)
        with db() as s:
            return [s.get_one(Job, i).company for i in applier.pick_jobs()]

    assert picked(True) == ["C1", "C2", "C0"]  # best score first
    assert picked(False) == ["C0"]
