import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import keyring
import pytest
from fastapi.testclient import TestClient
from test_tailor import make_cv
from test_vault import CHEAP, PASS, SECRET, MemoryKeyring

from linkit_all.api import runner as runner_module
from linkit_all.api.app import create_app
from linkit_all.apply.email_verify import EmailLoginError
from linkit_all.apply.vault import Vault
from linkit_all.core.config import Settings
from linkit_all.core.models import ActionItem, ActionKind, AnswerEntry, Job, JobState, Tier
from linkit_all.core.state import transition

BASE = "http://127.0.0.1:8765"
SAME_ORIGIN = {"origin": BASE}


@pytest.fixture(autouse=True)
def mem_keyring() -> Iterator[MemoryKeyring]:
    """Never touch the real OS keyring."""
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(data_dir=tmp_path / "data"))
    app.state.vault = Vault(app.state.db, "api-test", CHEAP)  # cheap Argon2 for speed
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


def park(
    client: TestClient, kind: ActionKind, questions: list[dict[str, Any]], artifact: str = ""
) -> tuple[int, int]:
    db = client.app.state.db  # type: ignore[attr-defined]
    with db.begin() as s:
        n = s.query(Job).count()
        job = Job(source="lever", url=f"https://x/{kind}/{n}", title="Dev", company="Acme", dedupe_hash=f"{kind}{n}",
                  state=JobState.applying)  # fmt: skip
        s.add(job)
        s.flush()
        transition(s, job, JobState.needs_user)
        item = ActionItem(
            job_id=job.id, kind=kind, questions=questions, artifacts=[artifact] if artifact else []
        )
        s.add(item)
        s.flush()
        return job.id, item.id


def test_action_center_answer_confirm_skip(client: TestClient, tmp_path: Path) -> None:
    q = {"label": "Have you ever been convicted of a felony?", "kind": "yesno", "options": ["Yes", "No"],
         "required": True, "reason": "criminal question: only you can answer", "sensitive": True}  # fmt: skip
    job_id, item_id = park(client, ActionKind.unknown_question, [q])
    assert client.get("/api/status").json()["actions_open"] == 1
    item = client.get("/api/actions").json()[0]
    assert item["job"]["title"] == "Dev" and item["questions"][0]["sensitive"]

    bad = client.post(
        f"/api/actions/{item_id}", json={"decision": "answer", "answers": {}}, headers=SAME_ORIGIN
    )
    assert bad.status_code == 422
    r = client.post(
        f"/api/actions/{item_id}",
        json={"decision": "answer", "answers": {q["label"]: "No"}},
        headers=SAME_ORIGIN,
    )
    assert r.json() == {"job_state": "queued_apply"}
    db = client.app.state.db  # type: ignore[attr-defined]
    with db() as s:
        entry = s.query(AnswerEntry).one()
        assert (entry.answer, entry.source, entry.sensitive) == ("No", "user", True)
    assert client.get("/api/actions").json() == []

    job_id, item_id = park(client, ActionKind.confirm_submit, [])
    client.post(f"/api/actions/{item_id}", json={"decision": "confirm"}, headers=SAME_ORIGIN)
    with db() as s:
        assert s.get_one(Job, job_id).data["submit_confirmed"] is True

    job_id, item_id = park(client, ActionKind.captcha, [])
    assert client.post(
        f"/api/actions/{item_id}", json={"decision": "applied_by_hand"}, headers=SAME_ORIGIN
    ).json() == {"job_state": "applied"}
    job_id, item_id = park(client, ActionKind.validation_error, [])
    assert client.post(
        f"/api/actions/{item_id}", json={"decision": "skip"}, headers=SAME_ORIGIN
    ).json() == {"job_state": "skipped"}
    assert (
        client.post(
            f"/api/actions/{item_id}", json={"decision": "skip"}, headers=SAME_ORIGIN
        ).status_code
        == 404
    )


def test_action_screenshot_only_from_data_dir(client: TestClient, tmp_path: Path) -> None:
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"png")
    _, item_id = park(client, ActionKind.captcha, [], artifact=str(outside))
    assert client.get(f"/api/actions/{item_id}/screenshot/0").status_code == 404
    inside = client.app.state.settings.data_dir / "applications" / "shot.png"  # type: ignore[attr-defined]
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_bytes(b"png")
    _, item_id = park(client, ActionKind.captcha, [], artifact=str(inside))
    assert client.get(f"/api/actions/{item_id}/screenshot/0").status_code == 200


def test_answer_bank_list_edit_delete(client: TestClient) -> None:
    db = client.app.state.db  # type: ignore[attr-defined]
    with db.begin() as s:
        s.add_all([AnswerEntry(question="Years of Python?", answer="5", source="ai"),
                   AnswerEntry(question="Willing to relocate?", answer=True, source="ai",
                               sensitive=True, uses=2)])  # fmt: skip
    rows = client.get("/api/answers").json()
    assert {r["question"] for r in rows} == {"Years of Python?", "Willing to relocate?"}
    assert set(rows[0]) == {"id", "question", "answer", "source", "sensitive", "uses", "updated_at"}
    py = next(r for r in rows if r["question"].startswith("Years"))

    r = client.put(f"/api/answers/{py['id']}", json={"answer": "6"}, headers=SAME_ORIGIN)
    assert (r.json()["answer"], r.json()["source"], r.json()["question"]) == (
        "6",
        "user",
        py["question"],
    )
    assert client.get("/api/answers").json()[0]["id"] == py["id"]  # newest edit first
    r = client.put(
        f"/api/answers/{py['id']}",
        json={"question": "Python years?", "answer": False},
        headers=SAME_ORIGIN,
    )
    assert (r.json()["question"], r.json()["answer"]) == ("Python years?", False)

    assert (
        client.put("/api/answers/999", json={"answer": "x"}, headers=SAME_ORIGIN).status_code == 404
    )
    for bad in ({"answer": ""}, {"answer": "  "}, {"answer": []}, {"answer": "x", "question": " "}):
        assert (
            client.put(f"/api/answers/{py['id']}", json=bad, headers=SAME_ORIGIN).status_code == 422
        )

    assert client.delete(f"/api/answers/{py['id']}", headers=SAME_ORIGIN).status_code == 204
    assert client.delete(f"/api/answers/{py['id']}", headers=SAME_ORIGIN).status_code == 404
    assert len(client.get("/api/answers").json()) == 1


def test_job_detail_filled_and_event_screenshots(client: TestClient, tmp_path: Path) -> None:
    ids = seed_jobs(client)
    job_id = ids["High job"]
    inside = client.app.state.settings.data_dir / "applications" / "dry.png"  # type: ignore[attr-defined]
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_bytes(b"png")
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"png")
    db = client.app.state.db  # type: ignore[attr-defined]
    filled = [{"label": "Email", "value": "j@x.io"}]
    with db.begin() as s:
        job = s.get_one(Job, job_id)
        job.data = {**job.data, "filled": filled}
        transition(s, job, JobState.tailored, "tailored", [str(inside), str(outside)])

    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["filled"] == filled
    assert client.get(f"/api/jobs/{ids['Mid job']}").json()["filled"] is None
    assert [e["screenshots"] for e in detail["events"]][-1] == 2
    event_id = detail["events"][-1]["id"]

    base = f"/api/jobs/{job_id}/events/{event_id}/screenshot"
    assert client.get(f"{base}/0").status_code == 200
    assert client.get(f"{base}/1").status_code == 404  # file outside the data dir
    assert client.get(f"{base}/2").status_code == 404  # no such artifact
    assert (
        client.get(f"/api/jobs/{ids['Mid job']}/events/{event_id}/screenshot/0").status_code == 404
    )


def test_application_answers_roundtrip(client: TestClient) -> None:
    assert (
        client.put("/api/profile/answers", json={}, headers=SAME_ORIGIN).status_code == 409
    )  # no profile yet
    client.put("/api/profile", json={"full_name": "J", "email": "j@x.io"}, headers=SAME_ORIGIN)
    body = {"authorized_countries": ["Egypt"], "eeo_gender": "decline", "acknowledge_privacy": True}
    assert client.put("/api/profile/answers", json=body, headers=SAME_ORIGIN).status_code == 200
    got = client.get("/api/profile/answers").json()
    assert got["authorized_countries"] == ["Egypt"] and got["eeo_race"] is None


def test_vault_lifecycle_and_errors(client: TestClient, mem_keyring: MemoryKeyring) -> None:
    def post(path: str, body: object = None) -> Any:
        return client.post(f"/api/vault/{path}", json=body or {}, headers=SAME_ORIGIN)

    fresh = {"initialized": False, "unlocked": False}
    assert client.get("/api/status").json()["vault"] == fresh
    assert client.get("/api/vault").json() == {**fresh, "entries": []}
    assert post("unlock", {"passphrase": PASS}).status_code == 409  # nothing to unlock
    assert post("create", {"passphrase": "short"}).status_code == 422
    assert post("create", {}).status_code == 422  # missing field
    assert post("create", {"passphrase": PASS}).status_code == 201
    assert post("create", {"passphrase": PASS}).status_code == 409
    assert client.get("/api/status").json()["vault"] == {"initialized": True, "unlocked": False}

    wrong = post("unlock", {"passphrase": "not the passphrase"})
    assert wrong.status_code == 401 and "not the passphrase" not in wrong.text
    assert not mem_keyring.store
    assert post("unlock", {"passphrase": PASS, "remember": False}).status_code == 200
    assert not mem_keyring.store  # remember=false stays out of the keyring
    assert client.get("/api/status").json()["vault"] == {"initialized": True, "unlocked": True}

    vault: Vault = client.app.state.vault  # type: ignore[attr-defined]
    eid = vault.put("account", "boards.greenhouse.io", "me@x.com", SECRET, {"note": "n"})
    listed = client.get("/api/vault").json()
    assert listed["unlocked"] and SECRET not in str(listed)
    assert listed["entries"][0] == {
        "id": eid,
        "kind": "account",
        "site": "boards.greenhouse.io",
        "username": "me@x.com",
        "meta": {"note": "n"},
        "created_at": listed["entries"][0]["created_at"],
        "updated_at": listed["entries"][0]["updated_at"],
    }

    reveal = f"entries/{eid}/reveal"
    assert post(reveal, {"passphrase": "nope nope nope"}).status_code == 401
    ok = post(reveal, {"passphrase": PASS})
    assert ok.status_code == 200 and ok.json() == {"secret": SECRET}
    assert post("entries/999/reveal", {"passphrase": PASS}).status_code == 404

    bad = post("export", {"passphrase": "nope nope nope"})
    assert bad.status_code == 401 and SECRET not in bad.text
    out = post("export", {"passphrase": PASS})
    assert out.status_code == 200
    assert out.headers["content-disposition"] == "attachment; filename=linkit-vault-export.json"
    assert out.json()[0]["secret"] == SECRET

    assert post("lock").json() == {"initialized": True, "unlocked": False}
    assert client.get("/api/vault").json()["entries"] == []
    assert post(reveal, {"passphrase": PASS}).status_code == 423
    assert client.delete(f"/api/vault/entries/{eid}", headers=SAME_ORIGIN).status_code == 423
    post("unlock", {"passphrase": PASS})  # remember defaults to true
    assert mem_keyring.store
    assert client.delete(f"/api/vault/entries/{eid}", headers=SAME_ORIGIN).status_code == 204
    assert client.get("/api/vault").json()["entries"] == []
    post("lock")
    assert not mem_keyring.store  # lock forgets the remembered key


def test_vault_unlocks_from_keyring_on_startup(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    first = create_app(settings)
    first.state.vault = Vault(first.state.db, "api-test", CHEAP)
    first.state.vault.create(PASS)
    first.state.vault.unlock(PASS)  # remembers the key
    second = create_app(settings)
    second.state.vault = Vault(second.state.db, "api-test", CHEAP)
    with TestClient(second, base_url=BASE) as c:
        assert c.get("/api/status").json()["vault"] == {"initialized": True, "unlocked": True}


def test_email_connect_test_disconnect(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []
    reject = {"on": False}

    def fake_login(host: str, user: str, password: str) -> None:
        calls.append((host, user, password))
        if reject["on"] or password == "wrongpassword":  # noqa: S105
            raise EmailLoginError("Gmail rejected the app password")

    monkeypatch.setattr("linkit_all.api.routes.check_login", fake_login)
    vault: Vault = client.app.state.vault  # type: ignore[attr-defined]

    def post(path: str, body: object = None) -> Any:
        return client.post(path, json=body or {}, headers=SAME_ORIGIN)

    assert client.get("/api/email").json() == {
        "imap_host": "imap.gmail.com",
        "imap_user": "",
        "connected": False,
        "vault": {"initialized": False, "unlocked": False},
    }
    for path, body in (("/api/email", {"app_password": "x"}), ("/api/email/test", None)):
        locked = post(path, body)
        assert locked.status_code == 423 and locked.json()["detail"] == "Unlock the vault first"
    assert client.delete("/api/email", headers=SAME_ORIGIN).status_code == 423

    post("/api/vault/create", {"passphrase": PASS})
    post("/api/vault/unlock", {"passphrase": PASS, "remember": False})
    assert post("/api/email", {"app_password": "abcd"}).status_code == 400  # no address anywhere
    assert post("/api/email/test").status_code == 404  # nothing saved
    assert not calls

    client.put("/api/profile", json={"full_name": "Me", "email": " Me@X.com "}, headers=SAME_ORIGIN)
    assert client.get("/api/email").json()["imap_user"] == "me@x.com"  # from the profile
    bad = post("/api/email", {"app_password": "wrongpassword"})
    assert bad.status_code == 400 and bad.json()["detail"] == "Gmail rejected the app password"
    assert "wrongpassword" not in bad.text
    assert vault.entries() == [] and client.get("/api/search").json()["email"]["imap_user"] == ""

    ok = post("/api/email", {"app_password": "abcd efgh ijkl mnop"})
    assert ok.status_code == 200 and ok.json()["connected"] is True
    assert "abcdefghijklmnop" not in ok.text
    assert calls[-1] == ("imap.gmail.com", "me@x.com", "abcdefghijklmnop")  # spaces stripped
    (entry,) = vault.entries()
    assert (entry.kind, entry.site, entry.username) == ("imap", "imap.gmail.com", "me@x.com")
    assert vault.get(entry.id) == "abcdefghijklmnop"
    saved = client.get("/api/search").json()["email"]
    assert saved["imap_host"] == "imap.gmail.com" and saved["imap_user"] == "me@x.com"
    assert "abcdefghijklmnop" not in client.get("/api/search").text
    assert client.get("/api/email").json()["connected"] is True

    assert post("/api/email/test").json() == {"ok": True}
    assert calls[-1] == ("imap.gmail.com", "me@x.com", "abcdefghijklmnop")
    reject["on"] = True
    failed = post("/api/email/test")
    assert (
        failed.status_code == 400 and failed.json()["detail"] == "Gmail rejected the app password"
    )
    reject["on"] = False

    post("/api/vault/lock")
    assert post("/api/email/test").status_code == 423
    assert client.delete("/api/email", headers=SAME_ORIGIN).status_code == 423
    got = client.get("/api/email").json()
    assert got["connected"] is False and got["vault"]["unlocked"] is False

    post("/api/vault/unlock", {"passphrase": PASS, "remember": False})
    assert client.get("/api/email").json()["connected"] is True
    assert client.delete("/api/email", headers=SAME_ORIGIN).status_code == 204
    assert vault.entries() == [] and client.get("/api/email").json()["connected"] is False
    assert post("/api/email/test").status_code == 404
