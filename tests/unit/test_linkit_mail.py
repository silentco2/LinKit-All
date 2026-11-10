# ruff: noqa: RUF001, F811
"""LinkIt mail: the extension's hover button on an email address sends the application now."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_apply_email import FakeProvider, smtp  # noqa: F401  (fixture)
from test_email_send import FakeSMTP
from test_matching import fake_embed
from test_vault import CHEAP, PASS

import linkit_all.pipeline
import linkit_all.providers
from linkit_all.api.app import create_app
from linkit_all.apply import runner
from linkit_all.apply.vault import Vault
from linkit_all.core.config import Settings
from linkit_all.core.models import Job, JobState, Profile
from linkit_all.core.search import SearchConfig, save_search
from linkit_all.sources.posts import heading

BASE = "http://127.0.0.1:8765"
EXT = {"origin": "chrome-extension://abcdefghijklmnop"}
NEAR = "We are hiring!\nPosition: QA Engineer\nSend your CV to hr@acme.com"


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, smtp: type[FakeSMTP]
) -> Iterator[TestClient]:
    app = create_app(Settings(data_dir=tmp_path / "data"))
    db = app.state.db
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4 mine")
    with db.begin() as s:
        s.add(Profile(id=1, full_name="Jane Doe", email="jane@example.com", cv_path=str(cv),
                      cv_source_format="pdf", answers={}))  # fmt: skip
    (tmp_path / "original").mkdir()
    (tmp_path / "original" / "cv.pdf").write_bytes(b"%PDF-1.4 mine")
    save_search(db, SearchConfig.model_validate({"apply": {"live": True}}))
    vault = Vault(db, "t", CHEAP)
    vault.create(PASS)
    vault.unlock(PASS, remember=False)
    vault.put("imap", "imap.gmail.com", "jane@example.com", "app-pw")
    app.state.vault = vault
    monkeypatch.setattr(linkit_all.providers, "get_provider", lambda *a, **k: FakeProvider())

    async def embedder(_s: Any) -> Any:
        return fake_embed

    monkeypatch.setattr(linkit_all.pipeline, "_get_embedder", embedder)
    monkeypatch.setattr(runner, "cv_text", lambda _p: "Jane Doe, QA engineer")
    with TestClient(app, base_url=BASE) as c:
        c.headers.update({**EXT, "x-linkit-token": c.get("/api/assist/token").json()["token"]})
        yield c


def mail(c: TestClient, to: str = "hr@acme.com", near: str = NEAR) -> Any:
    page = {"url": "https://www.linkedin.com/posts/acme-1", "title": "Acme on LinkedIn"}
    return c.post("/api/assist/email", json={"to": to, "page": page, "near": near})


def job(c: TestClient, to: str) -> Job:
    with c.app.state.db() as s:  # type: ignore[attr-defined]
        found: Job = s.query(Job).filter_by(url=f"mailto:{to}").one()
        return found


def test_sends_now_with_the_cv_and_the_job_title(client: TestClient, smtp: type[FakeSMTP]) -> None:
    r = mail(client)
    assert r.status_code == 200 and r.json()["status"] == "applied"
    sent = smtp.instances[0].sent[0]
    assert sent["To"] == "hr@acme.com" and sent["Subject"] == "QA Engineer"
    assert [p.get_filename() for p in sent.iter_attachments()] == ["Jane Doe - CV.pdf"]
    row = job(client, "hr@acme.com")
    assert row.state == JobState.applied and row.company == "Acme"
    assert "mail_sending" not in row.data
    again = mail(client, "HR@acme.com")  # never the same address twice
    assert again.status_code == 409 and "already emailed" in again.json()["detail"]
    assert len(smtp.instances) == 1


def test_no_title_found_and_the_daily_cap(client: TestClient, smtp: type[FakeSMTP]) -> None:
    r = mail(client, "jobs@initech.com", near="Questions? Write to jobs@initech.com")
    assert r.json()["status"] == "applied"
    assert smtp.instances[0].sent[0]["Subject"] == "Application – Jane Doe"
    db = client.app.state.db  # type: ignore[attr-defined]
    save_search(db, SearchConfig.model_validate({"apply": {"live": True, "email_daily_cap": 1}}))
    capped = mail(client, "hr@other.com")
    assert capped.status_code == 429 and len(smtp.instances) == 1


def test_practice_mode_sends_nothing(client: TestClient, smtp: type[FakeSMTP]) -> None:
    save_search(client.app.state.db, SearchConfig())  # type: ignore[attr-defined]
    r = mail(client)
    assert r.status_code == 409 and "Practice mode" in r.json()["detail"]
    assert not smtp.instances
    with client.app.state.db() as s:  # type: ignore[attr-defined]
        assert s.query(Job).count() == 0


def test_a_job_being_mailed_is_not_picked_by_a_run() -> None:
    j = Job(data={"apply_url": "mailto:hr@acme.com", "mail_sending": True})
    assert not runner.is_pickable(j, True, True)
    j.data = {"apply_url": "mailto:hr@acme.com"}
    assert runner.is_pickable(j, True, True)


def test_heading_can_skip_the_any_line_fallback() -> None:
    assert heading("Send CV to a@b.com", ("qa",), any_line=False) == ""
    assert (
        heading("Send CV to a@b.com\nSenior QA Tester", ("qa",), any_line=False)
        == "Senior QA Tester"
    )
