"""ODT and PDF CV uploads: converted to a DOCX base; a converted PDF needs approval."""

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from test_tailor import FakeProvider, fake_render, make_cv
from test_vault import CHEAP, MemoryKeyring

from linkit_all.api.app import create_app
from linkit_all.apply.vault import Vault
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobState, Profile
from linkit_all.core.profile import ProfileFields, approve_cv, save_cv, save_fields
from linkit_all.core.tools import soffice_path
from linkit_all.tailor.pipeline import TailorError, tailor_job
from linkit_all.tailor.render.libreoffice import convert

BASE = "http://127.0.0.1:8765"
H = {"origin": BASE}
needs_lo = pytest.mark.skipif(soffice_path() is None, reason="LibreOffice not installed")


@pytest.fixture(autouse=True)
def mem_keyring() -> Iterator[None]:
    import keyring

    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    yield
    keyring.set_keyring(previous)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(data_dir=tmp_path / "data"))
    app.state.vault = Vault(app.state.db, "cv-test", CHEAP)
    with TestClient(app, base_url=BASE) as c:
        yield c


def make_pdf(path: Path) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(
        ["Jane Doe", "Software Engineer at Acme, 2019-2023", "Built scalable backend services"]
    ):
        page.insert_text((60, 80 + 22 * i), line, fontsize=12)
    doc.save(str(path))
    return path.read_bytes()


def upload(client: TestClient, name: str, data: bytes) -> dict[str, object]:
    r = client.post("/api/profile/cv", params={"filename": name}, content=data, headers=H)
    assert r.status_code == 200, r.text
    return dict(r.json())


@needs_lo
def test_odt_upload_converts_and_is_approved(client: TestClient, tmp_path: Path) -> None:
    odt = convert(make_cv(tmp_path / "cv.docx"), "odt", tmp_path / "odt")
    r = upload(client, "my cv.odt", odt.read_bytes())
    assert r["cv_name"] == "my cv.docx" and r["cv_source_format"] == "odt" and r["cv_approved"]
    texts = [s["text"] for s in r["segments"]]  # type: ignore[attr-defined]
    assert any(t.startswith("Built scalable") for t in texts)
    assert (tmp_path / "data" / "cvs" / "original" / "my cv.odt").exists()
    assert client.get("/api/profile").json()["cv_source_format"] == "odt"
    assert client.get("/api/status").json()["cv_ready"]


def test_pdf_upload_is_unapproved_until_approved(client: TestClient, tmp_path: Path) -> None:
    r = upload(client, "cv.pdf", make_pdf(tmp_path / "in.pdf"))
    assert r["cv_source_format"] == "pdf" and r["cv_approved"] is False
    assert any("Software Engineer" in s["text"] for s in r["segments"])  # type: ignore[attr-defined]
    assert (tmp_path / "data" / "cvs" / "original" / "cv.pdf").read_bytes().startswith(b"%PDF-")
    assert client.get("/api/status").json()["cv_ready"] is False

    p = client.post("/api/profile/cv/approve", headers=H)
    assert p.status_code == 200 and p.json()["cv_approved"] is True
    assert client.get("/api/status").json()["cv_ready"] is True


def test_approve_without_cv_and_bad_files(client: TestClient) -> None:
    assert client.post("/api/profile/cv/approve", headers=H).status_code == 404
    for name, body in [("x.pdf", b"nope"), ("x.odt", b"nope"), ("x.txt", b"hi")]:
        r = client.post("/api/profile/cv", params={"filename": name}, content=body, headers=H)
        assert r.status_code == 422, name


def test_pdf_without_text_is_rejected(client: TestClient, tmp_path: Path) -> None:
    blank = pymupdf.open()
    blank.new_page()
    blank.save(str(tmp_path / "blank.pdf"))
    r = client.post(
        "/api/profile/cv",
        params={"filename": "blank.pdf"},
        content=(tmp_path / "blank.pdf").read_bytes(),
        headers=H,
    )
    assert r.status_code == 422 and "no text" in r.json()["detail"]
    assert client.get("/api/profile").json()["cv_name"] is None


def test_tailoring_refuses_unapproved_pdf_base(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    save_fields(db, ProfileFields(full_name="Jane", email="j@x.io", locked_facts=["Acme"]))
    save_cv(db, settings.data_dir, "cv.pdf", make_pdf(tmp_path / "in.pdf"))
    with db.begin() as s:
        job = Job(source="t", url="u", title="Backend", company="Initech", dedupe_hash="h")
        job.state = JobState.queued_apply
        s.add(job)

    with pytest.raises(TailorError, match="Approve the converted CV"):
        asyncio.run(tailor_job(db, job.id, FakeProvider("{}"), settings, render=fake_render))

    assert approve_cv(db)
    reply = json.dumps({"patches": []})
    row = asyncio.run(tailor_job(db, job.id, FakeProvider(reply), settings, render=fake_render))
    assert Path(row.pdf_path).exists()
    with db() as s:
        assert s.get_one(Profile, 1).cv_approved


def test_migration_adds_columns(tmp_path: Path) -> None:
    db = init_db(tmp_path / "x.db")  # runs Alembic to head
    save_fields(db, ProfileFields(full_name="Jane", email="j@x.io"))
    with db() as s:
        row = s.get_one(Profile, 1)
        assert row.cv_source_format == "docx" and row.cv_approved is True
