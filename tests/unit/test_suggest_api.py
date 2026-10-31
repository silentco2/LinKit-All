"""GET /api/countries, /api/suggest/{places,titles,skills} and /api/fx."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_infer_api import upload

from linkit_all.api.app import create_app
from linkit_all.core.config import Settings
from linkit_all.core.models import Job
from linkit_all.core.profile import ProfileFields, save_fields

BASE = "http://127.0.0.1:8765"
H = {"origin": BASE}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(data_dir=tmp_path / "data")), base_url=BASE) as c:
        yield c


def add_jobs(client: TestClient, *jobs: dict[str, Any]) -> None:
    with client.app.state.db.begin() as s:  # type: ignore[attr-defined]
        for n, kw in enumerate(jobs):
            s.add(Job(**{"source": "t", "url": f"https://x/{n}", "title": "Job", "company": f"C{n}",
                         "dedupe_hash": f"h{n}", **kw}))  # fmt: skip


def test_countries(client: TestClient) -> None:
    rows = client.get("/api/countries", headers=H).json()
    egypt = next(r for r in rows if r["iso2"] == "EG")
    assert egypt == {"iso2": "EG", "name": "Egypt", "name_ar": "مصر", "phone": "20",
                     "currency": "EGP", "jobspy": "egypt"}  # fmt: skip
    assert len(rows) > 200


def test_places(client: TestClient) -> None:
    got = client.get("/api/suggest/places", params={"q": "القاهرة", "lang": "ar"}, headers=H).json()
    assert got[0] == {"label": "Cairo, Egypt", "label_ar": "القاهرة، مصر", "city": "Cairo",
                      "country": "Egypt", "iso2": "EG", "kind": "city"}  # fmt: skip
    assert client.get("/api/suggest/places", headers=H).json() == []
    assert len(client.get("/api/suggest/places", params={"q": "a"}, headers=H).json()) == 10


def test_titles_put_cv_and_job_titles_first(client: TestClient, tmp_path: Path) -> None:
    plain = client.get("/api/suggest/titles", params={"q": "software"}, headers=H).json()
    assert plain[0].lower().startswith("software")  # the bundled list alone, no CV or jobs yet
    upload(client, tmp_path)
    add_jobs(client, {"title": "Backend Wizard"}, {"title": "Backend Wizard"}, {"title": "Cook"})
    got = client.get("/api/suggest/titles", params={"q": "backend"}, headers=H).json()
    assert got[:2] == ["Backend Engineer", "Backend Wizard"]  # CV title, then the stored job
    assert "Cook" not in got
    assert len(got) <= 10


def test_titles_survive_a_missing_cv_file(client: TestClient, tmp_path: Path) -> None:
    upload(client, tmp_path)
    for f in (tmp_path / "data").rglob("*.docx"):
        f.write_bytes(b"not a docx")
    assert client.get("/api/suggest/titles", params={"q": "engineer"}, headers=H).status_code == 200


def test_skills_exclude_the_ones_you_have(client: TestClient) -> None:
    save_fields(client.app.state.db, ProfileFields(skills=["docker", "Python"]))  # type: ignore[attr-defined]
    ai = {"ai": {"missing_skills": ["Kubernetes", "Docker", "Rust", " "]}}
    add_jobs(
        client,
        {"score": 9, "data": ai, "description": "We use Terraform and Python."},
        {
            "score": 8,
            "data": {"ai": {"missing_skills": ["kubernetes"]}},
            "description": "Terraform, Docker, Figma",
        },
        {"score": None, "data": ai, "description": "Python. Figma"},  # unscored: no AI skills
    )
    got = client.get("/api/suggest/skills", headers=H).json()
    assert got[:2] == ["Kubernetes", "Rust"]  # AI-found first, most frequent first
    assert "Terraform" in got and "Figma" in got  # lexicon skills seen in 2+ descriptions
    assert not {s.casefold() for s in got} & {"docker", "python"}
    assert len(got) == len({s.casefold() for s in got})
    # nothing was added to the profile
    assert client.get("/api/profile", headers=H).json()["skills"] == ["docker", "Python"]


def test_skills_capped_and_empty_without_jobs(client: TestClient) -> None:
    assert client.get("/api/suggest/skills", headers=H).json() == []
    many = {"ai": {"missing_skills": [f"Skill{i}" for i in range(40)]}}
    add_jobs(client, {"score": 7, "data": many})
    assert len(client.get("/api/suggest/skills", headers=H).json()) == 15


def test_fx(client: TestClient) -> None:
    got = client.get("/api/fx", headers=H).json()
    assert got["base"] == "USD" and got["date"][:2] == "20"
    assert {"USD", "EGP", "EUR"} <= set(got["currencies"])
    assert got["currencies"] == sorted(got["currencies"])
