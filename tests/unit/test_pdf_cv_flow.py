# ruff: noqa: F811
"""A CV uploaded as PDF: converted to a DOCX base, unusable until the user approves it.

The PDF is generated here with PyMuPDF and converted by the real pdf2docx (no LibreOffice needed).
Only the preview (`GET /api/profile/cv/pdf`) renders through LibreOffice, so that test skips
without it.
"""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_api import SAME_ORIGIN, client, mem_keyring  # noqa: F401  (fixtures)
from test_cv_formats import make_pdf
from test_matching import fake_embed
from test_park_codes import NoAI
from test_tailor import FakeProvider, fake_render

from linkit_all.apply import runner
from linkit_all.core.config import Settings
from linkit_all.core.models import Job, JobState
from linkit_all.core.search import SearchConfig
from linkit_all.core.tools import soffice_path
from linkit_all.tailor.pipeline import tailor_job

H = SAME_ORIGIN


def queue_job(client: TestClient) -> int:
    with client.app.state.db.begin() as s:  # type: ignore[attr-defined]
        job = Job(source="greenhouse", url="https://boards.greenhouse.io/acme/jobs/1",
                  title="Backend", company="Acme", location="", description="Build APIs",
                  ats="greenhouse", dedupe_hash="h", state=JobState.queued_apply,
                  data={"apply_url": "https://boards.greenhouse.io/acme/jobs/1"})  # fmt: skip
        s.add(job)
        s.flush()
        return job.id


def test_pdf_cv_needs_approval_before_tailoring_and_applying(
    client: TestClient, tmp_path: Path
) -> None:
    fields = {"full_name": "Jane", "email": "j@x.io", "locked_facts": ["Acme"]}
    client.put("/api/profile", json=fields, headers=H)
    r = client.post(
        "/api/profile/cv",
        params={"filename": "cv.pdf"},
        content=make_pdf(tmp_path / "in.pdf"),
        headers=H,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cv_name"] == "cv.docx" and body["cv_source_format"] == "pdf"
    assert body["cv_approved"] is False
    assert any("Built scalable backend" in s["text"] for s in body["segments"])
    assert client.get("/api/profile/cv/segments").json() == body["segments"]
    assert client.get("/api/profile").json()["cv_approved"] is False
    status = client.get("/api/status").json()
    assert status["cv_ready"] is False and status["setup"]["cv"] is False
    assert client.get("/api/golive").json()["checklist"]["cv_approved"] is False

    # tailoring refuses, and so does the applier (before it touches a browser)
    job_id = queue_job(client)
    settings: Settings = client.app.state.settings  # type: ignore[attr-defined]
    db = client.app.state.db  # type: ignore[attr-defined]
    with pytest.raises(runner.TailorError, match="Approve the converted CV"):
        asyncio.run(tailor_job(db, job_id, FakeProvider("{}"), settings, render=fake_render))
    applier = runner.Applier(db, settings, SearchConfig(), NoAI(), fake_embed)
    with pytest.raises(runner.ApplyBlocked, match="Approve the converted CV"):
        asyncio.run(applier.apply(job_id))
    with db() as s:
        assert s.get_one(Job, job_id).state == JobState.queued_apply  # untouched, not failed

    # approving flips every place that looks at it
    approved = client.post("/api/profile/cv/approve", headers=H)
    assert approved.status_code == 200 and approved.json()["cv_approved"] is True
    assert client.get("/api/profile").json()["cv_approved"] is True
    status = client.get("/api/status").json()
    assert status["cv_ready"] is True and status["setup"]["cv"] is True
    assert client.get("/api/golive").json()["checklist"]["cv_approved"] is True
    reply = '{"patches": []}'
    row = asyncio.run(tailor_job(db, job_id, FakeProvider(reply), settings, render=fake_render))
    assert Path(row.pdf_path).exists()

    # uploading a new PDF resets the approval
    client.post(
        "/api/profile/cv",
        params={"filename": "cv.pdf"},
        content=make_pdf(tmp_path / "in2.pdf"),
        headers=H,
    )
    assert client.get("/api/status").json()["cv_ready"] is False


@pytest.mark.skipif(
    soffice_path() is None,
    reason=(
        "LibreOffice not found. The agent's shell cannot see the real bundle: install it into a "
        "scratch data dir (`LINKIT_DATA_DIR=<dir> uv run linkit install-libreoffice <zip>`, see "
        "handoff.md Gotchas) and run this test with the same LINKIT_DATA_DIR"
    ),
)
def test_pdf_cv_preview_renders_with_libreoffice(client: TestClient, tmp_path: Path) -> None:
    client.post(
        "/api/profile/cv",
        params={"filename": "cv.pdf"},
        content=make_pdf(tmp_path / "in.pdf"),
        headers=H,
    )
    r = client.get("/api/profile/cv/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")
