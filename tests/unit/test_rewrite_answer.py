"""Needs you "Rewrite with AI" (POST /api/actions/{id}/rewrite): the user's own answer rewritten
for the job, or drafted from the CV when empty; never for sensitive or choice questions."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_api import SAME_ORIGIN, client  # noqa: F401
from test_tailor import make_cv

import linkit_all.providers as providers
from linkit_all.apply.assist import NotEnglish, rewrite_answer
from linkit_all.core.models import ActionItem, ActionKind, ActionStatus, Job, Profile
from linkit_all.core.profile import ProfileIn, import_profile
from linkit_all.providers.base import LLMProvider, UsageLimitError

JOB = {"title": "Backend Engineer", "company": "Acme", "description": "Python APIs for payments"}


class Fake(LLMProvider):
    """Replays `replies` in order (the last one repeats); keeps every prompt."""

    name = "fake"

    def __init__(self, *replies: dict[str, Any] | Exception) -> None:
        super().__init__("fake")
        self.replies, self.prompts = list(replies), []  # type: ignore[var-annotated]

    async def _call(self, prompt: str) -> str:
        self.prompts.append(prompt)
        r = self.replies[min(len(self.prompts), len(self.replies)) - 1]
        if isinstance(r, Exception):
            raise r
        return json.dumps(r)


def test_rewrite_retries_once_then_cleans() -> None:
    ai = Fake(
        {"text": "I'm thrilled to leverage Django — daily."}, {"text": "I use Django — daily."}
    )
    got = asyncio.run(
        rewrite_answer(ai, "Why us?", "i like django", "shorter", "CV", "profile", JOB)
    )
    assert got == "I use Django, daily." and len(ai.prompts) == 2
    assert "The candidate's wish: shorter" in ai.prompts[0] and "i like django" in ai.prompts[0]
    arabic = Fake({"text": "أحب العمل"})
    with pytest.raises(NotEnglish):
        asyncio.run(rewrite_answer(arabic, "Why us?", "x", "", "CV", "p", JOB))


@pytest.fixture
def setup(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:  # noqa: F811
    db = client.app.state.db  # type: ignore[attr-defined]
    import_profile(db, ProfileIn(full_name="Jane", email="j@x.io", cv_path=make_cv(tmp_path / "cv.docx"),
                                 skills=["Python"]), tmp_path / "data")  # fmt: skip
    with db.begin() as s:
        s.get_one(Profile, 1).answers = {"salary_expectation": "95000"}
        job = Job(source="t", url="https://x/1", title="Backend Engineer", company="Acme",
                  description="Python APIs", dedupe_hash="h", data={"email_draft": {"body": "old"}})  # fmt: skip
        s.add(job)
        s.flush()
        q = [{"label": "Why do you want to join Acme?", "kind": "textarea", "options": [], "required": True,
              "reason": "", "sensitive": False, "category": None},
             {"label": "Expected salary", "kind": "text", "options": [], "required": True,
              "reason": "", "sensitive": True, "category": "salary"},
             {"label": "Notice period", "kind": "select", "options": ["1 month"], "required": True,
              "reason": "", "sensitive": False, "category": None}]  # fmt: skip
        ask = ActionItem(job_id=job.id, kind=ActionKind.unknown_question, questions=q)
        mail = ActionItem(job_id=job.id, kind=ActionKind.confirm_email)
        done = ActionItem(job_id=job.id, kind=ActionKind.unknown_question, questions=q,
                          status=ActionStatus.resolved)  # fmt: skip
        s.add_all([ask, mail, done])
        s.flush()
        ids = {"ask": ask.id, "mail": mail.id, "done": done.id}
    ai = Fake({"text": "I build Python APIs and want payments work at Acme."})
    monkeypatch.setattr(providers, "get_provider", lambda *a, **k: ai)
    return {"ids": ids, "ai": ai}


def post(c: TestClient, item: int, **body: Any) -> Any:
    return c.post(f"/api/actions/{item}/rewrite", json=body, headers=SAME_ORIGIN)


def test_rewrite_endpoint(client: TestClient, setup: dict[str, Any]) -> None:  # noqa: F811
    ids, ai = setup["ids"], setup["ai"]
    q = "Why do you want to join Acme?"
    r = post(client, ids["ask"], label=q, text="i like payments, i want 95000", wish="formal")
    assert r.status_code == 200 and r.json()["text"].startswith("I build Python APIs")
    sent = ai.prompts[-1]
    assert "95000" not in sent and "[hidden]" in sent  # a sensitive answer never reaches the AI
    assert "Backend Engineer at Acme" in sent and "The candidate's wish: formal" in sent
    assert post(client, ids["mail"], label=None, text="Dear team, I apply.").status_code == 200
    assert "The body of a short email applying for this job" in ai.prompts[-1]


def test_empty_box_drafts_from_the_cv(client: TestClient, setup: dict[str, Any]) -> None:  # noqa: F811
    setup["ai"].replies = [
        {"answers": [{"key": "q", "known": True, "answer": "I am excited to build APIs."}]}
    ]
    r = post(client, setup["ids"]["ask"], label="Why do you want to join Acme?", text="")
    assert r.status_code == 200 and r.json()["text"] == "I would like to build APIs."  # cleaned too
    setup["ai"].replies = [{"answers": [{"key": "q", "known": False, "answer": None}]}]
    assert (
        post(
            client, setup["ids"]["ask"], label="Why do you want to join Acme?", text=""
        ).status_code
        == 422
    )


def test_refusals(client: TestClient, setup: dict[str, Any]) -> None:  # noqa: F811
    ids = setup["ids"]
    assert (
        post(client, ids["ask"], label="Expected salary", text="95000").status_code == 422
    )  # sensitive
    assert (
        post(client, ids["ask"], label="Notice period", text="1 month").status_code == 422
    )  # a choice
    assert post(client, ids["ask"], label="Not on this card", text="x").status_code == 404
    assert post(client, ids["ask"], label=None, text="x").status_code == 422  # no email here
    assert post(client, ids["mail"], label=None, text=" ").status_code == 422
    assert (
        post(client, ids["done"], label="Why do you want to join Acme?", text="x").status_code
        == 404
    )
    assert not setup["ai"].prompts  # none of these asked the AI
    setup["ai"].replies = [UsageLimitError("usage limit reached")]
    r = post(client, ids["ask"], label="Why do you want to join Acme?", text="x")
    assert r.status_code == 409
