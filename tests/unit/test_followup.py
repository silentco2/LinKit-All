"""One follow-up email per email application left without a reply (apply/followup.py, C3)."""

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_tailor import make_cv

from linkit_all.apply import followup
from linkit_all.apply.followup import due, send_followups
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobState, Outcome
from linkit_all.core.profile import ProfileIn, import_profile
from linkit_all.core.search import SearchConfig
from linkit_all.providers.base import LLMProvider

SENT = datetime(2026, 11, 1, 9, tzinfo=UTC)


class FakeAI(LLMProvider):
    name = "fake"

    def __init__(self) -> None:
        super().__init__("fake")
        self.calls = 0

    async def _call(self, prompt: str) -> str:
        self.calls += 1
        return json.dumps({"body": "I applied on 01 November 2026 and am still very interested."})


class FakeVault:
    def unlocked(self) -> bool:
        return True


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    import_profile(db, ProfileIn(full_name="Jane Doe", email="jane@example.com", phone="+20 100",
                                 location="Cairo", cv_path=make_cv(tmp_path / "cv.docx")),
                   settings.data_dir)  # fmt: skip
    with db.begin() as s:
        s.add(Job(id=1, source="t", url="mailto:hr@acme.io", title="Analyst", company="Acme",
                  dedupe_hash="h", state=JobState.applied,
                  data={"email_sent": {"to": "hr@acme.io", "message_id": "<a@x>",
                                       "sent_at": SENT.isoformat()},
                        "email_draft": {"subject": "Analyst"}}))  # fmt: skip
    sent: list[Any] = []
    monkeypatch.setattr(
        followup, "send", lambda cfg, vault, email, msg: sent.append(msg) or "<f@x>"
    )
    return {"db": db, "settings": settings, "sent": sent}


def cfg(**apply: Any) -> SearchConfig:
    return SearchConfig.model_validate({"apply": apply})


def run(env: dict[str, Any], c: SearchConfig, sent_today: int = 0) -> dict[str, int]:
    return asyncio.run(
        send_followups(env["db"], env["settings"], c, FakeAI(), FakeVault(), sent_today)  # type: ignore[arg-type]
    )


def test_due_only_after_the_waiting_days(env: dict[str, Any]) -> None:
    with env["db"]() as s:
        assert due(s, 7, SENT + timedelta(days=6)) == []
        assert [j.id for j in due(s, 7, SENT + timedelta(days=7))] == [1]


@pytest.mark.parametrize("outcome", [Outcome.rejected, Outcome.interview, Outcome.offer])
def test_no_follow_up_after_a_reply(env: dict[str, Any], outcome: Outcome) -> None:
    with env["db"].begin() as s:
        s.get_one(Job, 1).outcome = outcome
    with env["db"]() as s:
        assert due(s, 7, SENT + timedelta(days=30)) == []


def test_live_sends_once_threaded_and_never_twice(env: dict[str, Any]) -> None:
    c = cfg(live=True, submit_without_asking=True)
    assert run(env, c) == {"sent": 1, "previewed": 0, "due": 0}
    (msg,) = env["sent"]
    assert (msg["To"], msg["Subject"], msg["In-Reply-To"]) == ("hr@acme.io", "Re: Analyst", "<a@x>")
    assert msg.get_content().startswith("Hello,\n\nI applied on")
    assert not msg.is_multipart()  # no attachment on a follow-up
    with env["db"]() as s:
        job = s.get_one(Job, 1)
        assert job.data["followup_sent"]["message_id"] == "<f@x>"
        assert [e.code for e in job.events] == ["followup_sent"]
    assert run(env, c)["sent"] == 0  # never twice
    assert len(env["sent"]) == 1


def test_the_daily_email_cap_holds(env: dict[str, Any]) -> None:
    c = cfg(live=True, submit_without_asking=True, email_daily_cap=15)
    assert run(env, c, sent_today=15)["sent"] == 0
    assert env["sent"] == []


def test_dry_run_writes_an_eml_once_and_sends_nothing(env: dict[str, Any]) -> None:
    assert run(env, cfg(live=False))["previewed"] == 1
    assert run(env, cfg(live=False))["previewed"] == 0  # not again every run
    assert env["sent"] == []
    eml = env["settings"].data_dir / "applications" / "job_1" / "followup.eml"
    assert eml.exists()


def test_live_without_auto_submit_only_notes_it(env: dict[str, Any]) -> None:
    assert run(env, cfg(live=True, submit_without_asking=False))["due"] == 1
    assert env["sent"] == []
    with env["db"]() as s:
        job = s.get_one(Job, 1)
        assert (job.state, [e.code for e in job.events]) == (JobState.applied, ["followup_due"])
    assert run(env, cfg(live=True, submit_without_asking=False))["due"] == 0  # noted once
