"""Park messages carry a stable code and params so the UI can show them translated (D3)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from test_matching import fake_embed
from test_vault import CHEAP, PASS

from linkit_all.apply import runner
from linkit_all.apply.accounts import KIND, Account
from linkit_all.apply.handlers.base import Handler, JobInfo
from linkit_all.apply.vault import Vault
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import ActionItem, ActionKind, Job, JobEvent, JobState, Profile
from linkit_all.core.search import SearchConfig
from linkit_all.providers.base import LLMProvider


class NoAI(LLMProvider):
    name = "none"

    def __init__(self) -> None:
        super().__init__("none")

    async def _call(self, prompt: str) -> str:
        raise AssertionError("no AI call expected")


class FakePage:
    async def screenshot(self, **kwargs: Any) -> None:
        return None


class GatedHandler(Handler):
    ats = "workday"
    two_factor = False

    def account_tenant(self, job: JobInfo) -> str | None:
        return "acme"

    async def signed_in(self, page: Any) -> bool:
        return False

    async def two_factor_shown(self, page: Any) -> bool:
        return self.two_factor

    async def login(self, page: Any, job: JobInfo, account: Account) -> None:
        return None


def make(tmp_path: Path, live: bool = False) -> tuple[runner.Applier, JobInfo, Profile]:
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    with db.begin() as s:
        s.add(Profile(id=1, full_name="Me", cv_path="cv.docx", email="me@example.com"))
        s.add(Job(source="x", url="https://x/1", title="Dev", company="Acme", location="",
                  description="", ats="workday", dedupe_hash="h", state=JobState.tailored))  # fmt: skip
    cfg = SearchConfig.model_validate({"apply": {"live": live}})
    applier = runner.Applier(db, settings, cfg, NoAI(), fake_embed)
    with db() as s:
        info = runner.job_info(s.get_one(Job, 1))
        profile = s.get_one(Profile, 1)
        s.expunge(profile)
    assert info is not None
    return applier, info, profile


def unlocked_vault(applier: runner.Applier) -> Vault:
    vault = Vault(applier.db, "server", kdf=CHEAP)
    vault.create(PASS)
    vault.unlock(PASS, remember=False)
    applier._vault = vault
    return vault


def gate(applier: runner.Applier, info: JobInfo, profile: Profile, h: Handler, tmp: Path) -> Any:
    return asyncio.run(applier._account_gate(FakePage(), h, info, profile, tmp))  # type: ignore[arg-type]


def rows(applier: runner.Applier) -> tuple[ActionItem | None, list[JobEvent]]:
    with applier.db() as s:
        return s.query(ActionItem).first(), list(s.query(JobEvent).order_by(JobEvent.id))


def test_locked_vault_parks_with_site(tmp_path: Path) -> None:
    applier, info, profile = make(tmp_path)
    out = gate(applier, info, profile, GatedHandler(), tmp_path)
    assert out.status == "needs_user"
    item, events = rows(applier)
    assert item is not None
    assert item.kind == ActionKind.login_issue
    assert (item.code, item.params) == ("vault_locked", {"site": "workday (acme)"})
    assert "Unlock" in item.message  # the English text stays
    assert events[-1].code == "vault_locked" and events[-1].to_state == JobState.needs_user


def test_dry_run_would_create_account_event(tmp_path: Path) -> None:
    applier, info, profile = make(tmp_path)
    unlocked_vault(applier)
    out = gate(applier, info, profile, GatedHandler(), tmp_path)
    assert out.status == "dry_run"
    item, events = rows(applier)
    assert item is None
    assert (events[-1].code, events[-1].params) == ("dry_run_signup", {"site": "workday (acme)"})


def test_live_without_email_parks_email_not_connected(tmp_path: Path) -> None:
    applier, info, profile = make(tmp_path, live=True)
    unlocked_vault(applier)
    gate(applier, info, profile, GatedHandler(), tmp_path)
    item, _ = rows(applier)
    assert item is not None and item.code == "email_not_connected"


@pytest.mark.parametrize(
    ("two_factor", "code", "kind"),
    [
        (True, "two_factor", ActionKind.two_factor),
        (False, "login_rejected", ActionKind.login_issue),
    ],
)
def test_saved_login_outcomes(
    tmp_path: Path, two_factor: bool, code: str, kind: ActionKind
) -> None:
    applier, info, profile = make(tmp_path)
    vault = unlocked_vault(applier)
    vault.put(KIND, "workday:acme", "me@example.com", "pw", {"status": "active"})
    h = GatedHandler()
    h.two_factor = two_factor
    gate(applier, info, profile, h, tmp_path)
    item, _ = rows(applier)
    assert item is not None
    assert item.kind == kind
    assert (item.code, item.params) == (code, {"site": "workday (acme)"})


def test_park_stores_code_on_item_and_event(tmp_path: Path) -> None:
    applier, _, _ = make(tmp_path)
    with applier.db.begin() as s:
        runner._park(
            s,
            s.get_one(Job, 1),
            ActionKind.unknown_question,
            "2 question(s) need your answer",
            [],
            {},
            [],
            "unknown_question",
            {"n": 2},
        )
    item, events = rows(applier)
    assert item is not None and (item.code, item.params) == ("unknown_question", {"n": 2})
    assert [e.code for e in events] == ["filling", "unknown_question"]
    assert events[-1].params == {"n": 2}
