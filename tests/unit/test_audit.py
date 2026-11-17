"""Read-only tuning tools (matching/audit.py, C5) and their CLI commands."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from linkit_all.cli import app
from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobEvent, JobState
from linkit_all.core.search import SearchConfig, save_search
from linkit_all.matching.audit import filter_audit, why_missed

CFG = SearchConfig.model_validate(
    {"filters": {"title_include": ["engineer", "analyst"], "title_exclude": ["intern"]},
     "sources": {"companies": ["greenhouse:acme"]}}
)  # fmt: skip


@pytest.fixture
def db(tmp_path: Path):  # type: ignore[no-untyped-def]
    d = init_db(tmp_path / "t.db")
    with d.begin() as s:
        rows = [
            ("Backend Engineer", 9, JobState.scored),
            ("Data Engineer", 5, JobState.scored),
            ("Engineering Intern", None, JobState.filtered_out),
            ("Analyst", None, JobState.ranked),
        ]
        for i, (title, score, state) in enumerate(rows, 1):
            s.add(Job(id=i, source="t", url=f"https://jobs.test/{i}", title=title, company="Acme",
                      dedupe_hash=str(i), score=score, state=state))  # fmt: skip
        s.add(JobEvent(job_id=3, from_state=JobState.discovered, to_state=JobState.filtered_out,
                       message="title contains excluded word 'intern'"))  # fmt: skip
    return d


def test_filter_audit(db) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        rows = {(r.kind, r.word): (r.jobs, r.avg_score) for r in filter_audit(s, CFG)}
    assert rows == {("include", "engineer"): (3, 7.0), ("include", "analyst"): (1, None),
                    ("exclude", "intern"): (1, None)}  # fmt: skip


def test_why_missed(db) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        assert "left out" in why_missed(s, CFG, "https://jobs.test/3")
        assert "intern" in why_missed(s, CFG, "https://jobs.test/3")
        assert why_missed(s, CFG, "https://www.jobs.test/1#apply").startswith("Found already")
        other = why_missed(s, CFG, "https://boards.greenhouse.io/globex/jobs/77")
        assert "greenhouse" in other and "'greenhouse:globex'" in other
        mine = why_missed(s, CFG, "https://boards.greenhouse.io/acme/jobs/77")
        assert "is in your companies" in mine
        assert why_missed(s, CFG, "https://unknown.example/jobs/1").startswith("No source")


def test_cli_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINKIT_DATA_DIR", str(tmp_path / "data"))
    from linkit_all.core.config import get_settings

    get_settings.cache_clear()
    try:
        save_search(init_db(get_settings().db_path), CFG)
        runner = CliRunner()
        out = runner.invoke(app, ["filter-audit"])
        assert out.exit_code == 0, out.output
        assert "engineer" in out.output and "intern" in out.output
        out = runner.invoke(app, ["why-missed", "https://unknown.example/jobs/1"])
        assert out.exit_code == 0 and out.output.startswith("No source")
    finally:
        get_settings.cache_clear()
