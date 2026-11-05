# ruff: noqa: RUF001, F811
"""Apply by email: mailto jobs get a tailored CV + short cover email (dry run, confirm, caps)."""

import asyncio
import json
import smtplib
from collections.abc import Iterator
from email import message_from_bytes, policy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_api import SAME_ORIGIN, client, mem_keyring  # noqa: F401  (fixtures)
from test_email_send import FakeSMTP
from test_matching import fake_embed
from test_vault import CHEAP, PASS

from linkit_all.apply import runner
from linkit_all.apply.email_apply import ApplicationEmail, greeting, mailto_address, subject_for
from linkit_all.apply.vault import Vault
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import (
    ActionItem,
    ActionKind,
    ActionStatus,
    Job,
    JobEvent,
    JobState,
    Profile,
    VaultMeta,
)
from linkit_all.core.search import SearchConfig
from linkit_all.core.state import transition
from linkit_all.providers.base import LLMProvider, UsageLimitError

SECRETS = ("99999", "needs_sponsorship", "eeo_", "female")  # must never reach the model


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self) -> None:
        super().__init__("fake")
        self.prompts: list[str] = []
        self.queue: list[str] = []  # answers served first, then `answer`
        self.answer: str | Exception = json.dumps(
            {"subject_suffix": None, "body": "I would be a good fit for this role. CV attached."}
        )

    async def _call(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.queue:
            return self.queue.pop(0)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    FakeSMTP.fail_login = FakeSMTP.fail_send = None
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


class Env:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cfg: dict[str, Any]):
        self.settings = Settings(data_dir=tmp_path / "data")
        self.db = init_db(self.settings.db_path)
        self.pdf = tmp_path / "tailored.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 tailored")
        with self.db.begin() as s:
            s.add(
                Profile(
                    id=1,
                    full_name="Jane Doe",
                    email="jane@example.com",
                    phone="+20 100 000 0000",
                    cv_path="cv.docx",
                    answers={
                        "linkedin": "https://linkedin.com/in/jane",
                        "salary_expectation": "99999",
                        "needs_sponsorship": True,
                        "eeo_gender": "female",
                    },
                )
            )
        self.provider = FakeProvider()
        self.tailor_calls = 0

        async def tailor(db: Any, job_id: int, *a: Any, **k: Any) -> Any:
            self.tailor_calls += 1
            with db.begin() as s:
                job = s.get_one(Job, job_id)
                if job.state == JobState.queued_apply:
                    transition(s, job, JobState.tailored)
            return SimpleNamespace(pdf_path=str(self.pdf))

        monkeypatch.setattr(runner, "tailor_job", tailor)
        monkeypatch.setattr(runner, "cv_text", lambda _p: "Jane Doe, engineer at Initech")
        self.cfg = SearchConfig.model_validate({"apply": cfg})
        self.applier = runner.Applier(self.db, self.settings, self.cfg, self.provider, fake_embed)
        self.vault = Vault(self.db, "t", CHEAP)
        self.vault.create(PASS)
        self.vault.unlock(PASS, remember=False)
        self.vault.put("imap", "imap.gmail.com", "jane@example.com", "app-pw")
        self.applier._vault = self.vault

    def job(
        self, url: str = "mailto:hr@acme.com", author: str = "Sara Ahmed", n: int = 0, **data: Any
    ) -> int:
        with self.db.begin() as s:
            job = Job(source="linkedin_posts", url=f"https://linkedin.com/posts/{n}", title="Python Dev",
                      company="Acme", location="Cairo", description="We hire a Python dev. Pay 5000.",
                      dedupe_hash=f"h{n}", score=9, state=JobState.queued_apply,
                      data={"apply_url": url, "extra": {"author": author}, **data})  # fmt: skip
            s.add(job)
            s.flush()
            return job.id

    def apply(self, job_id: int) -> runner.Outcome:
        return asyncio.run(self.applier.apply(job_id))

    def row(self, job_id: int) -> Job:
        with self.db() as s:
            job = s.get_one(Job, job_id)
            s.expunge(job)
            return job

    def events(self, job_id: int) -> list[JobEvent]:
        with self.db() as s:
            return list(s.query(JobEvent).filter_by(job_id=job_id).order_by(JobEvent.id))

    def item(self) -> ActionItem | None:
        with self.db() as s:
            return s.query(ActionItem).first()


@pytest.fixture
def make(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, smtp: type[FakeSMTP]) -> Iterator[Any]:
    def build(**cfg: Any) -> Env:
        return Env(tmp_path, monkeypatch, cfg)

    yield build


def test_helpers() -> None:
    assert mailto_address("mailto:hr@acme.com") == "hr@acme.com"
    assert mailto_address("MAILTO:hr@acme.com?subject=Hi") == "hr@acme.com"
    assert mailto_address("mailto:a@b.com,c@d.com") is None
    assert mailto_address("mailto:") is None and mailto_address("https://x.com") is None
    assert greeting("Sara Ahmed") == "Hello Sara,"
    assert greeting("Acme Recruitment Team") == "Hello,"
    assert greeting("Acme") == "Hello," and greeting(None) == "Hello,"
    assert subject_for("Dev", "Jane Doe") == "Application: Dev – Jane Doe"
    assert subject_for("", "Jane Doe") == "Application – Jane Doe"
    with pytest.raises(ValueError):
        ApplicationEmail(body="word " * 181)
    with pytest.raises(ValueError):
        ApplicationEmail(body="  ")


def test_dry_run_writes_eml_and_never_sends(make: Any, smtp: type[FakeSMTP]) -> None:
    env: Env = make()
    job_id = env.job()
    out = env.apply(job_id)
    assert out.status == "dry_run" and smtp.instances == []
    eml = Path(out.artifacts[0])
    assert eml.name == "application.eml"
    msg = message_from_bytes(eml.read_bytes(), policy=policy.default)
    assert msg["To"] == "hr@acme.com" and msg["Subject"] == "Application: Python Dev – Jane Doe"
    body = msg.get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert body.startswith("Hello Sara,") and "Best regards,\nJane Doe\n+20 100 000 0000" in body
    assert "https://linkedin.com/in/jane" in body and "CV attached" in body
    att = next(p for p in msg.walk() if p.get_filename())
    assert (
        att.get_filename() == "Jane Doe - CV.pdf"
        and att.get_payload(decode=True) == b"%PDF-1.4 tailored"
    )
    ev = env.events(job_id)[-1]
    assert (ev.code, ev.artifacts, ev.params) == (
        "email_preview",
        [str(eml)],
        {"to": "hr@acme.com"},
    )
    assert env.row(job_id).data["dry_run_at"] and "email_sent" not in env.row(job_id).data
    assert env.item() is None


def test_prompt_is_the_template_and_has_no_sensitive_fields(make: Any) -> None:
    env: Env = make()
    env.apply(env.job())
    (prompt,) = env.provider.prompts
    assert "application email" in prompt and "Python Dev at Acme" in prompt
    assert "Jane Doe, engineer at Initech" in prompt and "We hire a Python dev" in prompt
    assert not any(s in prompt for s in SECRETS)
    assert "salary" in prompt.lower()  # only as a "never mention" rule
    assert "Hello Sara" not in prompt  # greeting and signature are added by our code


def test_invalid_model_output_is_retried_and_validated(make: Any) -> None:
    env: Env = make()
    long = json.dumps({"body": "word " * 200})
    answers = iter([long, json.dumps({"body": "Short and good.", "subject_suffix": "Ref 42"})])

    async def call(prompt: str) -> str:
        return next(answers)

    env.provider._call = call  # type: ignore[method-assign]
    out = env.apply(env.job())
    assert out.status == "dry_run"
    msg = message_from_bytes(Path(out.artifacts[0]).read_bytes(), policy=policy.default)
    assert msg["Subject"] == "Application: Python Dev – Jane Doe (Ref 42)"


def test_ai_usage_limit_blocks_the_run(make: Any) -> None:
    env: Env = make()
    env.provider.answer = UsageLimitError("usage limit reached")
    job_id = env.job()
    with pytest.raises(runner.ApplyBlocked):
        env.apply(job_id)
    assert env.row(job_id).state == JobState.tailored  # waits for the next run


def test_live_parks_confirm_email_with_editable_draft(make: Any, smtp: type[FakeSMTP]) -> None:
    env: Env = make(live=True)
    job_id = env.job()
    out = env.apply(job_id)
    assert out.status == "needs_user" and smtp.instances == []
    job, item = env.row(job_id), env.item()
    assert job.state == JobState.needs_user
    assert item is not None and item.kind == ActionKind.confirm_email
    assert (item.code, item.params) == (
        "confirm_email",
        {"to": "hr@acme.com", "subject": "Application: Python Dev – Jane Doe"},
    )
    draft = job.data["email_draft"]
    assert draft["to"] == "hr@acme.com" and draft["body"].startswith("Hello Sara,")
    assert Path(draft["attachment"]).read_bytes() == b"%PDF-1.4 tailored"


def test_confirm_sends_the_edited_draft(
    client: TestClient, make: Any, smtp: type[FakeSMTP]
) -> None:
    env: Env = make(live=True)
    job_id = env.job()
    env.apply(job_id)
    item = env.item()
    assert item is not None
    # the API works on the same database
    client.app.state.db = env.db  # type: ignore[attr-defined]
    listed = client.get("/api/actions").json()[0]
    assert listed["email_draft"]["to"] == "hr@acme.com"
    url = f"/api/actions/{item.id}/email-draft"
    for bad in (
        {"subject": "Hi\nBcc: x@y.com", "body": "b"},
        {"subject": "", "body": "b"},
        {"subject": "s", "body": "  "},
        {"subject": "s" * 201, "body": "b"},
    ):
        assert client.put(url, json=bad, headers=SAME_ORIGIN).status_code == 422
    assert (
        client.put(
            "/api/actions/999/email-draft", json={"subject": "s", "body": "b"}, headers=SAME_ORIGIN
        ).status_code
        == 404
    )
    edited = {"subject": "Python Dev application", "body": "Hello,\n\nMy edited text."}
    assert client.put(url, json=edited, headers=SAME_ORIGIN).status_code == 200
    r = client.post(f"/api/actions/{item.id}", json={"decision": "confirm"}, headers=SAME_ORIGIN)
    assert r.json() == {"job_state": "queued_apply"}

    env.provider.prompts.clear()
    out = env.apply(job_id)  # the next apply run
    assert out.status == "applied" and env.provider.prompts == []  # no second AI call
    (conn,) = smtp.instances
    assert conn.logged_in == ("jane@example.com", "app-pw")
    (sent,) = conn.sent
    assert sent["Subject"] == "Python Dev application" and sent["To"] == "hr@acme.com"
    assert "My edited text." in sent.get_body(("plain",)).get_content()  # type: ignore[union-attr]
    job = env.row(job_id)
    assert job.state == JobState.applied
    assert job.data["email_sent"]["to"] == "hr@acme.com"
    assert job.data["email_sent"]["message_id"] == sent["Message-ID"]
    assert job.data["email_sent"]["sent_at"]
    last = env.events(job_id)[-1]
    assert last.code == "applied_by_email" and last.to_state == JobState.applied
    assert last.params["message_id"] == sent["Message-ID"]
    assert Path(last.artifacts[0]).name == "sent.eml" and Path(last.artifacts[0]).exists()
    with env.db() as s:
        assert s.get_one(ActionItem, item.id).status == ActionStatus.resolved


def test_submit_without_asking_sends_directly(make: Any, smtp: type[FakeSMTP]) -> None:
    env: Env = make(live=True, submit_without_asking=True)
    job_id = env.job()
    out = env.apply(job_id)
    assert out.status == "applied" and env.item() is None
    assert len(smtp.instances[0].sent) == 1
    assert env.row(job_id).state == JobState.applied


def test_duplicate_address_is_skipped(make: Any, smtp: type[FakeSMTP]) -> None:
    env: Env = make(live=True, submit_without_asking=True)
    assert env.apply(env.job()).status == "applied"
    second = env.job(url="mailto:HR@Acme.com", n=1)
    out = env.apply(second)
    assert out.status == "skipped"
    job = env.row(second)
    assert job.state == JobState.skipped
    assert env.events(second)[-1].code == "email_already_sent"
    assert len(smtp.instances) == 1  # nothing more was sent
    assert env.tailor_calls == 1  # and the second job was never tailored


def test_smtp_auth_error_fails_without_the_password(make: Any, smtp: type[FakeSMTP]) -> None:
    env: Env = make(live=True, submit_without_asking=True)
    smtp.fail_login = smtplib.SMTPAuthenticationError(535, b"app-pw rejected")
    job_id = env.job()
    out = env.apply(job_id)
    assert out.status == "failed"
    job, last = env.row(job_id), env.events(job_id)[-1]
    assert job.state == JobState.failed
    assert last.code == "email_failed" and last.params["error"] == "SmtpAuthError"
    assert "app-pw" not in json.dumps([last.message, last.params])
    assert "email_sent" not in job.data


def test_other_smtp_error_fails(make: Any, smtp: type[FakeSMTP]) -> None:
    env: Env = make(live=True, submit_without_asking=True)
    smtp.fail_send = smtplib.SMTPRecipientsRefused({})
    job_id = env.job()
    assert env.apply(job_id).status == "failed"
    assert env.events(job_id)[-1].params["error"] == "SmtpError"


def test_email_not_connected_and_locked_vault_park(make: Any, smtp: type[FakeSMTP]) -> None:
    env: Env = make(live=True, submit_without_asking=True)
    for entry in env.vault.entries():
        env.vault.delete(entry.id)
    job_id = env.job()
    assert env.apply(job_id).status == "needs_user"
    item = env.item()
    assert item is not None and item.kind == ActionKind.login_issue
    assert (item.code, item.params) == ("needs_email", {"purpose": "send"})
    assert smtp.instances == []
    assert env.row(job_id).state == JobState.needs_user


def test_locked_vault_parks_vault_locked(make: Any, smtp: type[FakeSMTP]) -> None:
    env: Env = make(live=True, submit_without_asking=True)
    env.vault.lock()
    assert env.apply(env.job()).status == "needs_user"
    item = env.item()
    assert item is not None and item.code == "vault_locked" and smtp.instances == []


def test_missing_vault_parks_needs_vault(make: Any, smtp: type[FakeSMTP]) -> None:
    env: Env = make(live=True, submit_without_asking=True)
    env.vault.lock()
    with env.db.begin() as s:
        s.query(VaultMeta).delete()  # as if it was never created
    assert env.apply(env.job()).status == "needs_user"
    item = env.item()
    assert item is not None and item.code == "needs_vault" and smtp.instances == []


def test_pick_jobs_takes_mailto_and_respects_the_daily_cap(make: Any) -> None:
    env: Env = make(live=True, email_daily_cap=2)
    ids = [env.job(url=f"mailto:hr{i}@acme.com", n=i) for i in range(3)]
    bad = env.job(url="mailto:a@b.com,c@d.com", n=9)
    with env.db.begin() as s:
        s.get_one(Job, ids[0]).score = 5
    picked = env.applier.pick_jobs()
    assert len(picked) == 2 and bad not in picked and ids[0] not in picked  # best two only
    with env.db.begin() as s:  # one email already went out today
        job = s.get_one(Job, ids[1])
        transition(s, job, JobState.tailored)
        transition(s, job, JobState.applying)
        transition(s, job, JobState.applied, code="applied_by_email", params={"to": "x@y.com"})
    assert env.applier.pick_jobs() == [ids[2]]  # one slot left, applied job is gone
    with env.db.begin() as s:
        job = s.get_one(Job, ids[2])
        transition(s, job, JobState.tailored)
        transition(s, job, JobState.applying)
        transition(s, job, JobState.applied, code="applied_by_email", params={"to": "z@y.com"})
    assert env.applier.pick_jobs() == []  # cap reached: the rest stay queued
    assert env.row(ids[0]).state == JobState.queued_apply


def test_old_config_loads_with_default_cap() -> None:
    assert SearchConfig.model_validate({"apply": {"live": True}}).apply.email_daily_cap == 15


ARABIC_MAIL = json.dumps({"subject_suffix": None, "body": "السلام عليكم، أنا مطور برمجيات."})


def test_arabic_email_is_retried_once_then_accepted(make: Any, smtp: type[FakeSMTP]) -> None:
    env: Env = make(live=True, submit_without_asking=True)
    env.provider.queue = [ARABIC_MAIL]  # then the default English answer
    out = env.apply(env.job())
    assert out.status == "applied" and len(env.provider.prompts) == 2
    assert "Write in English only" in env.provider.prompts[1]


def test_arabic_email_twice_is_never_sent_even_without_asking(
    client: TestClient, make: Any, smtp: type[FakeSMTP]
) -> None:
    env: Env = make(live=True, submit_without_asking=True)
    env.provider.answer = ARABIC_MAIL
    job_id = env.job()
    out = env.apply(job_id)
    assert out.status == "needs_user" and smtp.instances == []
    assert len(env.provider.prompts) == 2  # first try plus one retry
    item = env.item()
    assert item is not None and item.kind == ActionKind.confirm_email
    assert item.params["problem"] == "arabic" and "Arabic" in item.message
    draft = env.row(job_id).data["email_draft"]
    assert draft["problem"] == "arabic" and "السلام" not in draft["body"]  # AI text not kept

    # confirming without writing anything parks again; the user's edit clears the problem
    client.app.state.db = env.db  # type: ignore[attr-defined]
    url = f"/api/actions/{item.id}/email-draft"
    edit = {"subject": draft["subject"], "body": "Hello,\n\nMy own words."}
    assert client.put(url, json=edit, headers=SAME_ORIGIN).status_code == 200
    assert "problem" not in env.row(job_id).data["email_draft"]
    client.post(f"/api/actions/{item.id}", json={"decision": "confirm"}, headers=SAME_ORIGIN)
    assert env.apply(job_id).status == "applied"
    (sent,) = smtp.instances[0].sent
    assert "My own words." in sent.get_body(("plain",)).get_content()  # type: ignore[union-attr]
