"""Answers read from the app's data, kept as general, per role or per company."""

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from test_matching import fake_embed

import linkit_all.pipeline as pipeline
import linkit_all.providers as providers
from linkit_all.api.app import create_app
from linkit_all.apply.agent import Control, page_questions
from linkit_all.apply.answers import Question
from linkit_all.apply.assist import GENERAL, AnswerBank, Scope, role_key, scope_of
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import ActionItem, ActionKind, AnswerEntry, Job, JobState
from linkit_all.core.profile import ProfileIn, import_profile
from linkit_all.providers.base import LLMProvider, UsageLimitError

BASE = "http://127.0.0.1:8765"
EXT = {"origin": "chrome-extension://abcdefghijklmnop"}


@pytest.mark.parametrize(
    ("question", "kind"),
    [
        ("Why do you want to work here?", "company"),
        ("Why Acme?", "company"),
        ("What do you know about our company?", "company"),
        ("Have you previously worked for us?", "company"),
        ("لماذا ترغب في الانضمام إلى هذه الشركة؟", "company"),
        ("Why are you a good fit for this role?", "role"),
        ("Why do you want to work in this position?", "role"),
        ("Describe your relevant experience", "role"),
        ("لماذا تناسبك هذه الوظيفة؟", "role"),
        ("Do you have a driving licence?", "general"),
        ("Years of experience with Python", "general"),
    ],
)
def test_scope_comes_from_the_wording(question: str, kind: str) -> None:
    assert scope_of(question, "Backend Engineer", "Acme Inc").kind == kind


def test_scope_names_who_it_is_for() -> None:
    assert scope_of("Why us?", "Dev", "Acme") == Scope("company", "Acme")
    assert scope_of("Why this role?", "Dev", "Acme") == Scope("role", "Dev")
    assert scope_of("Do you drive?", "Dev", "Acme") == GENERAL


def test_role_key_ignores_the_level() -> None:
    assert role_key("Senior Backend Engineer (Remote)") == role_key("backend engineer II")
    assert role_key("Backend Engineer") != role_key("Data Engineer")


def bank(tmp_path: Path) -> AnswerBank:
    return AnswerBank(init_db(Settings(data_dir=tmp_path / "d").db_path), fake_embed)


Q = Question("a", "Why do you want to work here?", "textarea")


def test_company_answer_is_reused_only_for_that_company(tmp_path: Path) -> None:
    b = bank(tmp_path)
    b.save(Q.label, "I love Acme", "ai", scope=Scope("company", "Acme Inc"))
    assert b.lookup(Q, scope=Scope("company", "ACME")) == "I love Acme"
    assert b.lookup(Q, scope=Scope("company", "Beta")) is None
    assert b.lookup(Q) is None  # not a general answer


def test_an_unnamed_company_never_shares_answers(tmp_path: Path) -> None:
    b = bank(tmp_path)
    b.save(Q.label, "text", "ai", scope=Scope("company", "Unknown"))
    assert b.lookup(Q, scope=Scope("company", "Unknown")) is None


def test_role_answer_is_shared_across_companies_and_levels(tmp_path: Path) -> None:
    b = bank(tmp_path)
    q = Question("a", "Why this role?", "textarea")
    b.save(q.label, "Backend is my thing", "ai", scope=Scope("role", "Backend Engineer"))
    assert b.lookup(q, scope=Scope("role", "Senior Backend Engineer")) == "Backend is my thing"
    assert b.lookup(q, scope=Scope("role", "Data Engineer")) is None


def test_same_question_is_kept_once_per_company(tmp_path: Path) -> None:
    b = bank(tmp_path)
    b.save(Q.label, "A", "ai", scope=Scope("company", "Acme"))
    b.save(Q.label, "B", "ai", scope=Scope("company", "Beta"))
    b.save(Q.label, "A2", "ai", scope=Scope("company", "Acme"))
    with b.db() as s:
        got = {e.scope_name: e.answer for e in s.query(AnswerEntry)}
    assert got == {"Acme": "A2", "Beta": "B"}


def control(**kw: Any) -> Control:
    base: dict[str, Any] = {"id": "f1", "kind": "text", "name": "City", "required": False,
                            "options": [], "value": "", "empty": True, "html_name": "", "type": "",
                            "href": ""}  # fmt: skip
    return Control(**{**base, **kw})


def test_page_questions_come_from_the_labels() -> None:
    got = page_questions(
        [
            control(id="a", name="First name *", html_name="fname", required=True),
            control(id="b", kind="button", name="Next"),
            control(id="c", name="Search jobs"),
            control(id="d", name="Phone", empty=False, value="123"),  # the form already has it
            control(id="e", kind="password", name="Password"),
        ]
    )
    assert [(q.key, q.label, q.name, q.required) for q in got] == [
        ("a", "First name", "fname", True)
    ]


class FakeAI(LLMProvider):
    name = "fake"

    def __init__(self) -> None:
        super().__init__("fake")
        self.prompts: list[str] = []
        self.limit = False

    async def _call(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.limit:
            raise UsageLimitError("limit")
        keys = [
            ln.split("key:")[1].split()[0].strip('"|,')
            for ln in prompt.splitlines()
            if "key:" in ln
        ]
        return json.dumps(
            {"answers": [{"key": k, "known": True, "answer": "Drafted"} for k in keys]}
        )


@pytest.fixture
def env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, FakeAI, dict[str, int]]]:
    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings)
    db = app.state.db
    cv = tmp_path / "cv.docx"
    from test_tailor import make_cv

    make_cv(cv)
    import_profile(db, ProfileIn(full_name="Jane Doe", email="jane@example.com", phone="+20 100",
                                 location="Cairo", cv_path=cv), settings.data_dir)  # fmt: skip
    ids = {}
    with db.begin() as s:
        for company in ("Acme", "Beta"):
            job = Job(source="linkedin", url=f"https://l.test/{company}", title="Backend Engineer",
                      company=company, location="Cairo", description="Python", dedupe_hash=company,
                      state=JobState.needs_user, data={})  # fmt: skip
            s.add(job)
            s.flush()
            s.add(ActionItem(job_id=job.id, kind=ActionKind.apply_in_browser, code="x"))
            ids[company] = job.id
    ai = FakeAI()
    monkeypatch.setattr(providers, "get_provider", lambda *a, **k: ai)

    async def embedder(_settings: Any) -> Any:
        return fake_embed

    monkeypatch.setattr(pipeline, "_get_embedder", embedder)
    with TestClient(app, base_url=BASE) as c:
        yield c, ai, ids


def plan(c: TestClient, job_id: int, *controls: dict[str, Any]) -> dict[str, Any]:
    t = c.get("/api/assist/token").json()["token"]
    body = {"job_id": job_id, "controls": list(controls)}
    r = c.post("/api/assist/plan", json=body, headers={**EXT, "x-linkit-token": t})
    assert r.status_code == 200, r.text
    got: dict[str, Any] = r.json()
    return got


NAME = {"id": "a", "kind": "text", "name": "First name", "required": True}
MAIL = {"id": "b", "kind": "email", "name": "Email address", "required": True}
WHY = {"id": "c", "kind": "textarea", "name": "Why do you want to work here?", "required": True}
NOISE = {"id": "d", "kind": "text", "name": "Promo code"}


def test_recorded_data_fills_the_form_without_any_ai(env: Any) -> None:
    c, ai, ids = env
    r = plan(c, ids["Acme"], NAME, MAIL, NOISE)
    assert r["fill"] == {"a": "Jane", "b": "jane@example.com"} and r["missing"] == []
    assert ai.prompts == []  # not even to read the page


def test_ai_answers_are_saved_per_company_and_reused(env: Any) -> None:
    c, ai, ids = env
    first = plan(c, ids["Acme"], NAME, WHY)
    assert (
        first["fill"]["c"] == "Drafted" and first["sources"]["c"] == "ai" and len(ai.prompts) == 1
    )
    plan(c, ids["Acme"], WHY)
    assert len(ai.prompts) == 1  # the saved answer was used
    plan(c, ids["Beta"], WHY)
    assert len(ai.prompts) == 2  # another company gets its own
    rows = c.get("/api/answers").json()
    assert {(r["scope"], r["scope_name"]) for r in rows} == {
        ("company", "Acme"),
        ("company", "Beta"),
    }


def test_out_of_ai_still_fills_recorded_answers(env: Any) -> None:
    c, ai, ids = env
    ai.limit = True
    r = plan(c, ids["Acme"], NAME, WHY)
    assert r["fill"] == {"a": "Jane"} and [m["id"] for m in r["missing"]] == ["c"]


def test_sensitive_question_never_reaches_the_ai(env: Any) -> None:
    c, ai, ids = env
    q = {"id": "s", "kind": "text", "name": "What is your expected salary?", "required": True}
    r = plan(c, ids["Acme"], q)
    assert [m["id"] for m in r["missing"]] == ["s"] and ai.prompts == []


def typed(c: TestClient, job_id: int, control: dict[str, Any], value: Any) -> dict[str, Any]:
    t = c.get("/api/assist/token").json()["token"]
    body = {"job_id": job_id, "control": control, "value": value}
    r = c.post("/api/assist/typed", json=body, headers={**EXT, "x-linkit-token": t})
    assert r.status_code == 200, r.text
    got: dict[str, Any] = r.json()
    return got


def test_only_fields_without_profile_data_are_watched(env: Any) -> None:
    c, _, ids = env
    assert plan(c, ids["Acme"], NAME, NOISE)["asked"] == ["d"]


def test_what_the_user_types_is_kept_for_that_company_without_ai(env: Any) -> None:
    c, ai, ids = env
    assert typed(c, ids["Acme"], WHY, "Their open source work") == {
        "saved": True,
        "scope": "company",
    }
    r = plan(c, ids["Acme"], WHY)
    assert r["fill"]["c"] == "Their open source work" and ai.prompts == []
    assert [(a["source"], a["scope_name"]) for a in c.get("/api/answers").json()] == [
        ("user", "Acme")
    ]
    plan(c, ids["Beta"], WHY)
    assert len(ai.prompts) == 1  # another company is asked afresh


def test_a_correction_replaces_the_ai_answer(env: Any) -> None:
    c, _, ids = env
    plan(c, ids["Acme"], WHY)
    typed(c, ids["Acme"], WHY, "My own words")
    assert [(a["answer"], a["source"]) for a in c.get("/api/answers").json()] == [
        ("My own words", "user")
    ]


@pytest.mark.parametrize(
    ("kind", "name"),
    [
        ("text", "What is your expected salary?"),  # never answers for the user later
        ("radio", "Do you require visa sponsorship?"),
        ("text", "Password"),
        ("text", "Enter the verification code"),
        ("text", "OTP"),
        ("text", "Card number"),
        ("text", "Passport number"),
        ("text", "الرقم القومي"),
        ("checkbox", "I agree to the terms"),
        ("date", "Available from"),
        ("file", "Resume"),
        ("textarea", "Cover letter"),
        ("password", "Choose a passphrase"),
        ("button", "Next"),
    ],
)
def test_sensitive_secret_and_one_off_fields_are_not_kept(env: Any, kind: str, name: str) -> None:
    c, _, ids = env
    assert typed(c, ids["Acme"], {"id": "x", "kind": kind, "name": name}, "v") == {"saved": False}
    assert c.get("/api/answers").json() == []


def test_a_word_inside_another_is_not_a_secret(env: Any) -> None:
    c, _, ids = env  # "hotpot" holds "otp"
    assert typed(c, ids["Acme"], {"id": "x", "kind": "text", "name": "Favourite hotpot"}, "v")[
        "saved"
    ]


def test_nothing_is_kept_for_an_empty_field(env: Any) -> None:
    c, _, ids = env
    assert typed(c, ids["Acme"], NOISE, "") == {"saved": False}


def page_plan(c: TestClient, *controls: dict[str, Any], **extra: Any) -> dict[str, Any]:
    t = c.get("/api/assist/token").json()["token"]
    body = {
        "job_id": None,
        "title": "Apply",
        "text": "Join us",
        "controls": list(controls),
        **extra,
    }
    r = c.post("/api/assist/plan", json=body, headers={**EXT, "x-linkit-token": t})
    assert r.status_code == 200, r.text
    got: dict[str, Any] = r.json()
    return got


def test_right_click_lets_the_ai_answer_optional_fields_too(env: Any) -> None:
    c, ai, ids = env
    t = c.get("/api/assist/token").json()["token"]
    body = {"job_id": ids["Acme"], "fill_all": True, "controls": [NOISE]}
    r = c.post("/api/assist/plan", json=body, headers={**EXT, "x-linkit-token": t}).json()
    assert r["fill"] == {"d": "Drafted"} and r["sources"] == {"d": "ai"} and len(ai.prompts) == 1
    assert plan(c, ids["Acme"], NOISE)["fill"] == {"d": "Drafted"}  # now recorded


def test_a_page_with_no_waiting_job_still_fills_from_the_profile(env: Any) -> None:
    c, ai, _ = env
    assert page_plan(c, NAME, MAIL)["fill"] == {"a": "Jane", "b": "jane@example.com"}
    assert ai.prompts == []


def test_a_company_answer_on_such_a_page_is_filled_but_not_kept(env: Any) -> None:
    c, ai, _ = env
    assert page_plan(c, WHY)["fill"]["c"] == "Drafted" and len(ai.prompts) == 1
    assert c.get("/api/answers").json() == []
    t = c.get("/api/assist/token").json()["token"]
    body = {"job_id": None, "control": WHY, "value": "x"}
    got = c.post("/api/assist/typed", json=body, headers={**EXT, "x-linkit-token": t}).json()
    assert got == {"saved": False}


def test_a_general_answer_on_such_a_page_is_kept(env: Any) -> None:
    c, _, _ = env
    t = c.get("/api/assist/token").json()["token"]
    body = {"job_id": None, "control": NOISE, "value": "SAVE10"}
    got = c.post("/api/assist/typed", json=body, headers={**EXT, "x-linkit-token": t}).json()
    assert got == {"saved": True, "scope": "general"}


def test_a_job_with_no_tailored_cv_sends_the_users_own(env: Any) -> None:
    c, _, ids = env
    t = c.get("/api/assist/token").json()["token"]
    h = {"x-linkit-token": t}
    upload = {"id": "f", "kind": "file", "name": "Resume", "required": True}
    assert plan(c, ids["Acme"], upload)["fill"] == {"f": "cv"}
    assert c.get(f"/api/assist/cv/{ids['Acme']}", headers=h).status_code == 200
    assert c.get("/api/assist/cv/0", headers=h).status_code == 200


def test_a_sensitive_bank_answer_in_the_page_text_never_reaches_the_ai(env: Any) -> None:
    from linkit_all.apply.answers import secrets_seen

    c, ai, _ = env
    secrets_seen.clear()
    try:
        with c.app.state.db.begin() as s:
            s.add(AnswerEntry(question="Pay?", answer="Zorbian-77", source="user", sensitive=True))
        got = page_plan(c, WHY, text="You said Zorbian-77 earlier", title="Hi Zorbian-77")
        assert got["fill"] == {"c": "Drafted"} and ai.prompts
        assert not any("Zorbian-77" in p for p in ai.prompts)
    finally:
        secrets_seen.clear()
