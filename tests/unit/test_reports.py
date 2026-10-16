import csv
import io
from datetime import timedelta
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.api.app import create_app
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobEvent, JobState, Run, Tier, utcnow
from linkit_all.reports import CSV_COLUMNS, build_report, export_csv, export_pdf

S = JobState
BASE = "http://127.0.0.1:8765"


def seed(s: Session) -> None:
    now = utcnow()
    s.add_all([Run(id=1, started_at=now - timedelta(days=3)), Run(id=2, started_at=now)])
    s.flush()
    rows = [  # run, source, ats, company, state, score, tier
        (1, "greenhouse", "greenhouse", "Acme", S.applied, 9, Tier.high),
        (1, "greenhouse", "greenhouse", "Acme", S.failed, 8, Tier.high),
        (1, "jobspy", None, "Globex", S.skipped, 8, Tier.high),
        (2, "lever", "lever", "Initech", S.needs_user, 9, Tier.high),
        (2, "lever", "lever", "Initech", S.applied, 8, Tier.high),
        (2, "lever", "lever", "Hooli", S.awaiting_review, 6, Tier.mid),
        (2, "jobspy", None, "=Evil", S.filtered_out, None, None),
        (2, "jobspy", None, "Globex", S.discovered, None, None),
    ]
    for i, (run, source, ats, company, state, score, tier) in enumerate(rows):
        job = Job(run_id=run, source=source, ats=ats, company=company, state=state, score=score,
                  tier=tier, url=f"https://x/{i}", title=f"=Dev {i}" if i == 0 else f"Dev {i}",
                  dedupe_hash=str(i), description="SECRET CV-like text", data={"answers": "secret"})  # fmt: skip
        s.add(job)
        s.flush()
        if state in (S.applied, S.failed, S.skipped, S.needs_user):
            s.add(JobEvent(job_id=job.id, at=now - timedelta(days=run), from_state=S.applying,
                           to_state=state))  # fmt: skip
    s.commit()


@pytest.fixture
def db(tmp_path: Path) -> sessionmaker[Session]:
    factory = init_db(tmp_path / "t.db")
    with factory() as s:
        seed(s)
    return factory


def by_name(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(r["name"]): r for r in rows}


def test_funnel_and_platform(db: sessionmaker[Session]) -> None:
    with db() as s:
        rep = build_report(s)
    funnel = {f["step"]: f["count"] for f in rep["funnel"]}
    assert funnel == {"Found": 8, "Passed filters": 6, "AI scored": 6, "Queued to apply": 4,
                      "Applied": 2}  # fmt: skip
    src = by_name(rep["per_platform"]["source"])
    assert (src["lever"]["found"], src["lever"]["applied"], src["lever"]["needs_user"]) == (3, 1, 1)
    assert (src["greenhouse"]["applied"], src["greenhouse"]["failed"]) == (1, 1)
    assert src["jobspy"]["skipped"] == 1
    ats = by_name(rep["per_platform"]["ats"])
    assert ats["unknown"]["found"] == 3 and ats["greenhouse"]["found"] == 2


def test_boards_only_with_outcomes(db: sessionmaker[Session]) -> None:
    with db() as s:
        boards = by_name(build_report(s)["per_board"])
    assert set(boards) == {"Acme", "Globex", "Initech"}  # Hooli/Evil never reached apply
    assert boards["Acme"]["applied"] == 1 and boards["Acme"]["failed"] == 1
    assert boards["Globex"]["found"] == 2 and boards["Globex"]["skipped"] == 1


def test_per_run_and_run_filter(db: sessionmaker[Session]) -> None:
    with db() as s:
        rep = build_report(s, run_id=2)
        runs = {r["run_id"]: r for r in rep["per_run"]}
    assert runs[1]["found"] == 3 and runs[1]["applied"] == 1 and runs[1]["failed"] == 1
    assert runs[2]["found"] == 5 and runs[2]["needs_user"] == 1
    assert rep["funnel"][0]["count"] == 5  # filter applies to the funnel, not to per_run
    assert rep["filter"]["run_id"] == 2
    assert sum(d["applied"] for d in rep["over_time"]) == 1


def test_over_time_buckets(db: sessionmaker[Session]) -> None:
    today = utcnow().date()
    with db() as s:
        rep = build_report(s)
        since = build_report(s, since=today)
    days = {d["date"]: d for d in rep["over_time"]}
    assert len(days) == 90
    one, two = (
        days[(today - timedelta(days=1)).isoformat()],
        days[(today - timedelta(days=2)).isoformat()],
    )
    assert (one["applied"], one["failed"], one["skipped"]) == (1, 1, 1)  # run 1
    assert (two["needs_user"], two["applied"]) == (1, 1)  # run 2
    assert since["funnel"][0]["count"] == 8 and len(since["over_time"]) == 1


def test_csv_columns_and_no_private_data(db: sessionmaker[Session]) -> None:
    with db() as s:
        text = export_csv(s)
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == CSV_COLUMNS
    assert len(rows) == 1 + 5  # applied x2, failed, skipped, needs_user
    first = dict(zip(rows[0], rows[1], strict=True))
    assert first["title"] == "'=Dev 0" and first["state"] == "applied" and first["applied_at"]
    assert "SECRET" not in text and "secret" not in text
    with db() as s:
        assert len(list(csv.reader(io.StringIO(export_csv(s, run_id=2))))) == 1 + 2


def test_pdf_has_funnel_numbers(db: sessionmaker[Session]) -> None:
    with db() as s:
        data = export_pdf(s)
    assert data.startswith(b"%PDF")
    with pymupdf.open(stream=data) as doc:
        text = "".join(str(p.get_text()) for p in doc)
    assert "Passed filters" in text and "Queued to apply" in text
    assert "lever" in text and "SECRET" not in text
    line = next(ln for ln in text.splitlines() if ln.startswith("Found"))
    assert line.split()[-1] == "8"


def test_routes_are_attachments(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data"))
    with TestClient(app, base_url=BASE) as client:
        with app.state.db() as s:
            seed(s)
        csv_r = client.get("/api/report/export.csv?run_id=1")
        pdf_r = client.get("/api/report/export.pdf")
        rep = client.get("/api/report?since=2000-01-01").json()
    assert csv_r.headers["content-disposition"].startswith("attachment")
    assert csv_r.text.count("\n") == 1 + 3
    assert pdf_r.headers["content-disposition"].startswith("attachment")
    assert pdf_r.content.startswith(b"%PDF")
    assert rep["funnel"][0]["count"] == 8
