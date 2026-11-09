"""The trash: applied, reported and off-title jobs never reach a list, but stay in the database."""

from pathlib import Path
from typing import Any

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.api.app import create_app
from linkit_all.core.config import Settings
from linkit_all.core.models import (
    ActionItem,
    ActionKind,
    ActionStatus,
    Job,
    JobState,
    SearchConfigRow,
    Tier,
)
from linkit_all.core.search import SearchConfig
from linkit_all.matching.trash import off_titles, sweep


def _embed(texts: list[str]) -> np.ndarray[Any, Any]:
    """Titles with "near" sit by the wanted title; every other title is far from it."""
    return np.array([[1.0, 0.0] if ("near" in t or t == "Wanted") else [0.0, 1.0] for t in texts])


def _no_model(texts: list[str]) -> Any:
    raise AssertionError(f"the model was not needed for {texts}")


def _app(tmp_path: Path) -> tuple[Any, sessionmaker[Session]]:
    app = create_app(Settings(data_dir=tmp_path / "d"))
    return app, app.state.db


def _job(s: Session, title: str, state: JobState = JobState.below_threshold, **kw: Any) -> Job:
    job = Job(source="board", url=f"https://x.test/{title}", title=title, company=kw.pop("company", title),
              location="", description="", dedupe_hash=title, state=state, tier=Tier.low, data={}, **kw)  # fmt: skip
    s.add(job)
    s.flush()
    return job


def _cfg(*titles: str) -> SearchConfig:
    cfg = SearchConfig()
    cfg.search.queries = list(titles)
    return cfg


def test_a_shared_skill_word_keeps_a_title_without_the_model() -> None:
    titles = ["Full-Stack Engineer", "Senior Front End Lead", "Next.js Wizard"]
    assert (
        off_titles(titles, ["Fullstack Developer", "Frontend Dev", "Next.JS Dev"], _no_model)
        == set()
    )


def test_no_wanted_titles_means_nothing_is_off_topic() -> None:
    assert off_titles(["Welder"], [], _no_model) == set()


def test_off_title_needs_a_low_fit_and_a_shared_role_word_lowers_the_bar() -> None:
    def fits(texts: list[str]) -> np.ndarray[Any, Any]:
        table = {
            "Sales Lady": 0.5,
            "Sales Engineer": 0.5,
            "Wanted Developer": 1.0,
            "Welder": 0.1,
            "Builder": 0.6,
        }
        return np.array([[table[t], (1 - table[t] ** 2) ** 0.5] for t in texts])

    titles = ["Sales Lady", "Sales Engineer", "Welder", "Builder"]
    assert off_titles(titles, ["Wanted Developer"], fits) == {"Sales Lady", "Welder"}


def test_lists_never_show_applied_or_off_title_jobs_and_the_rows_stay(tmp_path: Path) -> None:
    app, db = _app(tmp_path)
    with db.begin() as s:
        _job(s, "near fit")
        _job(s, "Welder")
        _job(s, "near applied", JobState.applied)
    sweep(db, _cfg("Wanted"), _embed)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        shown = [j["title"] for j in client.get("/api/jobs").json()]
        assert shown == ["near fit"]
        assert client.get("/api/jobs?state=applied").json() == []
        assert client.get("/api/jobs?q=Welder").json() == []
        assert client.get("/api/status").json()["states"] == {"below_threshold": 1, "applied": 1}
    with db() as s:
        assert len(list(s.scalars(select(Job)))) == 3


def test_a_parked_off_title_job_leaves_needs_you(tmp_path: Path) -> None:
    _, db = _app(tmp_path)
    with db.begin() as s:
        job = _job(s, "Welder", JobState.needs_user)
        s.add(ActionItem(job_id=job.id, kind=ActionKind.apply_in_browser, code="apply_in_browser"))
    assert sweep(db, _cfg("Wanted"), _embed) == 1
    with db() as s:
        assert s.scalars(select(Job)).one().state == JobState.skipped
        assert s.scalars(select(ActionItem)).one().status == ActionStatus.dismissed


def test_a_title_comes_back_when_the_user_starts_looking_for_it(tmp_path: Path) -> None:
    app, db = _app(tmp_path)
    with db.begin() as s:
        _job(s, "Welder")
    sweep(db, _cfg("Wanted"), _embed)
    sweep(db, _cfg("Welder"), _embed)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert [j["title"] for j in client.get("/api/jobs").json()] == ["Welder"]


def test_titles_are_embedded_once_per_set_of_wanted_titles(tmp_path: Path) -> None:
    _, db = _app(tmp_path)
    with db.begin() as s:
        _job(s, "Welder")
    sweep(db, _cfg("Wanted"), _embed)
    sweep(db, _cfg("Wanted"), _no_model)  # would raise if it embedded again


def test_a_reported_job_stays_hidden_and_its_company_goes_with_it(tmp_path: Path) -> None:
    app, db = _app(tmp_path)
    with db.begin() as s:
        job = _job(s, "near scam", company="Crooks")
        _job(s, "near other", company="Crooks Ltd.")
        _job(s, "near fine", company="Good")
        job_id = job.id
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert (
            client.post(f"/api/jobs/{job_id}/trust", json={"action": "report"}).status_code == 200
        )
        assert "near scam" not in [j["title"] for j in client.get("/api/jobs").json()]
        with db() as s:
            row = s.get(SearchConfigRow, 1)
            assert row is not None
            cfg = SearchConfig.model_validate(row.data)
        cfg.search.queries = ["Wanted"]
        sweep(db, cfg, _embed)
        assert sorted(j["title"] for j in client.get("/api/jobs").json()) == ["near fine"]


def test_reporting_an_unnamed_company_does_not_blacklist_every_unnamed_post(tmp_path: Path) -> None:
    app, db = _app(tmp_path)
    with db.begin() as s:
        job_id = _job(s, "near post", company="Unknown").id
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.post(f"/api/jobs/{job_id}/trust", json={"action": "report"})
    with db() as s:
        row = s.get(SearchConfigRow, 1)
        assert row is not None
        assert SearchConfig.model_validate(row.data).filters.company_blacklist == []
        assert s.get(Job, job_id).data["trash"] == "reported"  # type: ignore[union-attr]
