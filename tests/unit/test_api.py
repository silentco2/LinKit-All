import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_tailor import make_cv

from linkit_all.api import runner as runner_module
from linkit_all.api.app import create_app
from linkit_all.core.config import Settings
from linkit_all.core.models import Job, JobState, Tier
from linkit_all.core.state import transition

BASE = "http://127.0.0.1:8765"
SAME_ORIGIN = {"origin": BASE}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(data_dir=tmp_path / "data"))
    with TestClient(app, base_url=BASE) as c:
        yield c


def test_rejects_foreign_host_and_cross_site_writes(client: TestClient) -> None:
    assert client.get("/api/status", headers={"host": "evil.example"}).status_code == 400
    bad = client.put("/api/search", json={}, headers={"origin": "https://evil.example"})
    assert bad.status_code == 403
    assert client.put("/api/search", json={}, headers=SAME_ORIGIN).status_code == 200
    assert client.put("/api/search", json={}).status_code == 200  # no Origin: not a browser


def test_profile_and_cv_upload(client: TestClient, tmp_path: Path) -> None:
    fields = {
        "full_name": "Jane",
        "email": "j@x.io",
        "skills": ["Python"],
        "locked_facts": ["Acme", " "],
    }
    r = client.put("/api/profile", json=fields, headers=SAME_ORIGIN)
    assert r.json()["locked_facts"] == ["Acme"] and r.json()["cv_name"] is None
    cv = make_cv(tmp_path / "my cv.docx").read_bytes()
    r = client.post(
        "/api/profile/cv", params={"filename": "../my cv.docx"}, content=cv, headers=SAME_ORIGIN
    )
    assert r.status_code == 200, r.text
    assert r.json()["cv_name"] == "my cv.docx"  # path parts stripped
    assert any(s["text"].startswith("Built scalable") for s in r.json()["segments"])
    bad = client.post(
        "/api/profile/cv", params={"filename": "x.docx"}, content=b"not a zip", headers=SAME_ORIGIN
    )
    assert bad.status_code == 422
    status = client.get("/api/status").json()
    assert status["profile_ready"] and status["cv_ready"] and not status["search_ready"]


def test_search_config_validation(client: TestClient) -> None:
    bad = client.put("/api/search", json={"sources": {"jobspy": ["myspace"]}}, headers=SAME_ORIGIN)
    assert bad.status_code == 422
    ok = {"search": {"queries": ["python"]}, "ai": {"provider": "claude_cli"}}
    assert client.put("/api/search", json=ok, headers=SAME_ORIGIN).status_code == 200
    assert client.get("/api/search").json()["search"]["queries"] == ["python"]
    assert client.get("/api/ai").json()["provider"] == "claude_cli"


def seed_jobs(client: TestClient) -> dict[str, int]:
    db = client.app.state.db  # type: ignore[attr-defined]
    ids = {}
    with db.begin() as s:
        for title, state, tier, score in [("Mid job", JobState.awaiting_review, Tier.mid, 6),
                                          ("High job", JobState.queued_apply, Tier.high, 9),
                                          ("Ranked job", JobState.ranked, None, None)]:  # fmt: skip
            job = Job(source="greenhouse", url=f"https://x/{title}", title=title, company=title,
                      dedupe_hash=title, data={"rank": 0.5}, tier=tier, score=score)  # fmt: skip
            s.add(job)
            s.flush()
            job.state = JobState.scored if tier else JobState.enriched
            transition(s, job, state)
            ids[title] = job.id
    return ids


def test_jobs_list_detail_and_review_actions(client: TestClient) -> None:
    ids = seed_jobs(client)
    rows = client.get("/api/jobs").json()
    assert [r["title"] for r in rows] == ["High job", "Mid job", "Ranked job"]
    assert [r["title"] for r in client.get("/api/jobs", params={"tier": "mid"}).json()] == [
        "Mid job"
    ]
    assert client.get("/api/jobs", params={"q": "high"}).json()[0]["id"] == ids["High job"]
    detail = client.get(f"/api/jobs/{ids['Mid job']}").json()
    assert detail["events"][-1]["to"] == "awaiting_review"

    body = {"ids": [ids["Mid job"], ids["Ranked job"], 999], "action": "approve"}
    r = client.post("/api/jobs/actions", json=body, headers=SAME_ORIGIN).json()
    assert r["done"] == 1 and set(r["errors"]) == {str(ids["Ranked job"]), "999"}
    assert client.get(f"/api/jobs/{ids['Mid job']}").json()["state"] == "queued_apply"
    r = client.post(
        "/api/jobs/actions",
        json={"ids": [ids["Ranked job"]], "action": "reject"},
        headers=SAME_ORIGIN,
    )
    assert r.json()["done"] == 1

    funnel = {f["step"]: f["count"] for f in client.get("/api/report").json()["funnel"]}
    assert funnel["Found"] == 3 and funnel["AI scored"] == 2 and funnel["Queued to apply"] == 2


def test_run_streams_stage_events(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_stage(stage: str, *args: Any) -> dict[str, Any]:
        calls.append(stage)
        if stage == "rank":
            from linkit_all.pipeline import PipelineError

            raise PipelineError("no profile")
        return {"stage": stage}

    monkeypatch.setattr(runner_module, "run_stage", fake_stage)
    with client.websocket_connect("ws://127.0.0.1:8765/api/events", headers=SAME_ORIGIN) as ws:
        r = client.post(
            "/api/runs", json={"stages": ["rank", "discover", "enrich"]}, headers=SAME_ORIGIN
        )
        assert r.status_code == 202 and r.json()["stages"] == ["discover", "enrich", "rank"]
        assert client.post("/api/runs", json={}, headers=SAME_ORIGIN).status_code in (202, 409)
        events = []
        while not (
            events and events[-1].get("type") == "run" and events[-1]["status"] != "started"
        ):
            events.append(ws.receive_json())
    assert calls[:3] == ["discover", "enrich", "rank"]
    assert {"type": "stage", "stage": "rank", "status": "failed"}.items() <= next(
        e for e in events if e.get("stage") == "rank" and e["status"] == "failed"
    ).items()
    assert events[-1]["status"] == "failed" and events[-1]["error"] == "no profile"
    for _ in range(50):
        if not client.get("/api/runs").json()["current"]["running"]:
            break
        time.sleep(0.05)
    assert (
        client.post("/api/runs", json={"stages": ["nope"]}, headers=SAME_ORIGIN).status_code == 422
    )


def test_websocket_from_other_site_is_refused(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            "ws://127.0.0.1:8765/api/events", headers={"origin": "https://evil.example"}
        ) as ws,
    ):
        ws.receive_json()
