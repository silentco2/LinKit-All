# ruff: noqa: F811
"""UX7 backend fixes: usage-limit pauses, optional LibreOffice, run kinds, message codes."""

import asyncio
import hashlib
import io
import json
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from loguru import logger
from test_api import SAME_ORIGIN, client, mem_keyring  # noqa: F401  (fixtures)
from test_matching import fake_embed
from test_park_codes import NoAI
from test_tailor import make_cv
from test_ux_api import put_cfg

from linkit_all import pipeline
from linkit_all.api.events import EventBus
from linkit_all.apply import runner
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.lo_install import LibreOfficeInstaller
from linkit_all.core.models import Job, JobEvent, JobState, Profile, Run, RunStatus
from linkit_all.core.runs import current_run, run_kind
from linkit_all.core.search import SearchConfig, save_search
from linkit_all.providers import base, claude_cli, codex_cli
from linkit_all.providers.base import ProviderError, UsageLimitError, classify
from linkit_all.sources.base import JobStub
from linkit_all.sources.store import Deduper, store_page
from linkit_all.tailor import pipeline as tailor_pipeline

H = SAME_ORIGIN
VENDOR = (
    "You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
    "https://chatgpt.com/codex/settings/usage to purchase more credits or try again at "
    "Nov 4th, 2026 12:36 AM."
)

# --- 1. usage limit -------------------------------------------------------------------


def test_codex_usage_limit_is_one_short_sentence_without_links() -> None:
    events = "\n".join(  # Codex prints the same error as an event and as turn.failed
        [
            json.dumps({"type": "error", "message": VENDOR}),
            json.dumps({"type": "turn.failed", "error": {"message": VENDOR}}),
        ]
    )
    with pytest.raises(UsageLimitError) as e:
        codex_cli.parse_output(1, events, "", "")
    assert e.value.kind == "usage_limit" and e.value.provider == "codex_cli"
    assert e.value.until == "2026-11-04"
    assert e.value.message == str(e.value)
    assert e.value.message == "ChatGPT (Codex) usage limit reached; try again after Nov 4, 2026."
    assert "http" not in e.value.message and "Upgrade" not in e.value.message


def test_claude_usage_limit_with_epoch_and_without_a_date() -> None:
    out = json.dumps({"is_error": True, "result": "Claude AI usage limit reached|1793750400"})
    with pytest.raises(UsageLimitError) as e:
        claude_cli.parse_output(1, out, "")
    assert (e.value.provider, e.value.until) == ("claude_cli", "2026-11-04")
    plain = classify("You have hit your usage limit", "claude_cli")
    assert isinstance(plain, UsageLimitError) and plain.until is None
    assert plain.message == "Claude usage limit reached."


def test_other_failures_are_not_limits_and_are_deduplicated() -> None:
    err = classify("not logged in; not logged in\nnot logged in", "codex_cli")
    assert type(err) is ProviderError and str(err) == "not logged in"
    assert base.parse_until("resets 4 Nov 2026") == "2026-11-04"
    assert base.parse_until("on 2026-13-45") is None  # not a date: no guess


def test_litellm_rate_limit_is_a_usage_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    import litellm
    from litellm.exceptions import RateLimitError

    from linkit_all.providers.litellm_api import LiteLLMProvider

    async def boom(**kw: Any) -> Any:
        raise RateLimitError("quota exceeded, try again at Nov 4th, 2026", "openai", "gpt")

    monkeypatch.setattr(litellm, "acompletion", boom)
    with pytest.raises(UsageLimitError) as e:
        asyncio.run(LiteLLMProvider("openai/gpt")._call("hi"))
    assert (e.value.provider, e.value.until) == ("litellm", "2026-11-04")


class Failing(base.LLMProvider):
    name = "fake"

    def __init__(self, error: Exception) -> None:
        super().__init__("fake")
        self.error = error

    async def check(self) -> str:
        raise self.error

    async def _call(self, prompt: str) -> str:
        raise self.error


def test_ai_check_reports_usage_limit_and_plain_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure: list[Exception] = []
    monkeypatch.setattr("linkit_all.providers.get_provider", lambda *a, **k: Failing(failure[0]))
    body = {"provider": "codex_cli"}

    failure[:] = [UsageLimitError(VENDOR, "codex_cli")]
    got = client.post("/api/ai/check", json=body, headers=H).json()
    assert got == {
        "ok": False,
        "kind": "usage_limit",
        "provider": "codex_cli",
        "until": "2026-11-04",
        "message": "ChatGPT (Codex) usage limit reached; try again after Nov 4, 2026.",
    }
    failure[:] = [ProviderError("no such file; no such file")]
    got = client.post("/api/ai/check", json=body, headers=H).json()
    assert got == {"ok": False, "kind": "error", "message": "no such file"}


# --- a usage limit pauses the run -----------------------------------------------------


def wait_idle(client: TestClient) -> dict[str, Any]:
    for _ in range(100):
        got: dict[str, Any] = client.get("/api/runs").json()
        if not got["current"]["running"]:
            return got
        time.sleep(0.05)
    raise AssertionError("run did not end")


def start(client: TestClient, stages: list[str], new: bool = False) -> int:
    body = {"stages": stages, "new": new}
    return client.post("/api/runs", json=body, headers=H).status_code


def test_usage_limit_pauses_the_run_and_resume_continues(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def stage(name: str, *a: Any) -> dict[str, Any]:
        calls.append(name)
        if len(calls) == 1:
            raise UsageLimitError(VENDOR, "codex_cli")
        return {}

    monkeypatch.setattr(pipeline, "_run_stage", stage)
    assert start(client, ["rank", "apply"]) == 202
    got = wait_idle(client)
    run = got["recent"][0]
    assert run["status"] == "paused" and run["reason_code"] == "ai_usage_limit"
    assert run["reason_params"] == {"provider": "codex_cli", "until": "2026-11-04"}
    assert "http" not in run["pause_reason"]
    assert got["current"]["reason_code"] == "ai_usage_limit"
    assert got["current"]["error"] == run["pause_reason"]
    assert calls == ["rank"]  # the later stage did not run

    assert start(client, ["rank", "apply"]) == 202
    got = wait_idle(client)
    assert calls == ["rank", "rank", "apply"] and len(got["recent"]) == 1  # the same run
    assert got["recent"][0]["status"] == "done" and got["recent"][0]["reason_code"] is None


def test_other_failures_get_a_pipeline_error_code(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stage(name: str, *a: Any) -> dict[str, Any]:
        raise pipeline.PipelineError("no profile yet")

    monkeypatch.setattr(pipeline, "_run_stage", stage)
    start(client, ["rank"])
    got = wait_idle(client)
    assert got["current"]["reason_code"] == "pipeline_error"
    assert got["current"]["reason_params"] == {"detail": "no profile yet"}
    assert got["recent"][0]["reason_code"] == "pipeline_error"


def test_apply_blocked_with_a_code_pauses_without_one_it_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = init_db(tmp_path / "t.db")
    save_search(db, SearchConfig())
    run_id = current_run(db)
    blocked: list[runner.ApplyBlocked] = []

    async def boom(*a: Any, **k: Any) -> Any:
        raise blocked[0]

    async def no_embedder(settings: Settings) -> None:
        return None

    monkeypatch.setattr(runner, "apply_jobs", boom)
    monkeypatch.setattr(pipeline, "_get_embedder", no_embedder)
    settings = Settings(data_dir=tmp_path)

    blocked[:] = [runner.ApplyBlocked("LibreOffice is missing", "needs_libreoffice")]
    with pytest.raises(pipeline.PipelinePause) as p:
        asyncio.run(pipeline.run_stage("apply", db, settings, run_id))
    assert p.value.code == "needs_libreoffice"
    with db() as s:
        row = s.get_one(Run, run_id)
        assert row.status == RunStatus.paused and row.reason_code == "needs_libreoffice"
        assert row.stages == ["apply"]

    blocked[:] = [runner.ApplyBlocked("No profile yet")]
    with pytest.raises(pipeline.PipelineError) as f:
        asyncio.run(pipeline.run_stage("apply", db, settings, run_id))
    assert not isinstance(f.value, pipeline.PipelinePause)
    assert (f.value.code, f.value.params) == ("pipeline_error", {"detail": "No profile yet"})


# --- 6. run kind ----------------------------------------------------------------------


def test_run_kind_from_stages_and_old_stats() -> None:
    def kind(stages: list[str], stats: dict[str, Any] | None = None) -> str:
        return run_kind(Run(stages=stages, stats=stats or {}))

    assert kind(["discover", "enrich", "rank", "score"]) == "search"
    assert kind(["apply"]) == "apply"
    assert kind(["discover", "apply"]) == "mixed"
    assert kind([], {"discover": {}, "rank": {}}) == "search"  # runs from before `stages`
    assert kind([], {"apply": {}}) == "apply"


def test_runs_api_titles_by_stage(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def stage(name: str, *a: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(pipeline, "_run_stage", stage)
    start(client, ["apply"])
    wait_idle(client)
    start(client, ["discover", "enrich"], new=True)
    got = wait_idle(client)
    assert [(r["kind"], r["stages"]) for r in got["recent"]] == [
        ("search", ["discover", "enrich"]),
        ("apply", ["apply"]),
    ]


# --- 2. LibreOffice install -----------------------------------------------------------


def bundle() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("program/soffice.exe", "stub")
    return buf.getvalue()


def installing_client(
    client: TestClient, handler: Callable[[httpx.Request], httpx.Response], sha: str
) -> Path:
    data: Path = client.app.state.settings.data_dir  # type: ignore[attr-defined]
    settings = Settings(
        data_dir=data, lo_bundle_url="https://example.test/lo.zip", lo_bundle_sha256=sha
    )
    client.app.state.lo_installer = LibreOfficeInstaller(  # type: ignore[attr-defined]
        settings, httpx.MockTransport(handler)
    )
    return data


def wait_installed(client: TestClient) -> dict[str, Any]:
    for _ in range(100):
        got: dict[str, Any] = client.get("/api/tools/libreoffice").json()
        if not got["installing"]:
            return got
        time.sleep(0.05)
    raise AssertionError("install did not end")


def test_install_downloads_verifies_and_unpacks(client: TestClient) -> None:
    body = bundle()
    data = installing_client(
        client,
        lambda r: httpx.Response(200, content=body, headers={"content-length": str(len(body))}),
        hashlib.sha256(body).hexdigest().upper(),  # case does not matter
    )
    r = client.post("/api/tools/libreoffice/install", headers=H)
    assert r.status_code == 202 and r.json()["available"] is True
    got = wait_installed(client)
    exe = data / "tools" / "libreoffice" / "program" / "soffice.exe"
    assert got["error"] is None, got
    assert exe.is_file(), got
    assert got["installed"], got
    assert got["path"] == str(exe) and got["progress"] == 1.0
    assert not list((data / "tools" / "download").glob("*"))  # temp file gone


def test_install_refuses_a_checksum_mismatch_and_cleans_up(client: TestClient) -> None:
    body = bundle()
    data = installing_client(client, lambda r: httpx.Response(200, content=body), "0" * 64)
    client.post("/api/tools/libreoffice/install", headers=H)
    got = wait_installed(client)
    assert "checksum" in (got["error"] or "")
    assert not (data / "tools" / "libreoffice").exists()  # nothing unpacked, nothing run
    assert not list((data / "tools" / "download").glob("*"))


def test_install_download_error_is_reported(client: TestClient) -> None:
    installing_client(client, lambda r: httpx.Response(404), "a" * 64)
    client.post("/api/tools/libreoffice/install", headers=H)
    assert "Download failed" in wait_installed(client)["error"]


def test_install_unavailable_without_hash_or_https(client: TestClient) -> None:
    status = client.get("/api/tools/libreoffice").json()
    assert set(status) == {"installed", "path", "installing", "progress", "error", "available"}
    assert status["available"] is False  # the default has no pinned hash yet
    r = client.post("/api/tools/libreoffice/install", headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "lo_not_available"
    installing_client(client, lambda r: httpx.Response(200), "a" * 64)
    installer = client.app.state.lo_installer  # type: ignore[attr-defined]
    assert installer.available() is True
    installer.settings.lo_bundle_url = "http://example.test/lo.zip"
    assert client.get("/api/tools/libreoffice").json()["available"] is False


# --- 2. tailor, or the CV as uploaded -------------------------------------------------


class Tailor:
    """Stands in for tailor_job: counts calls, says where the "tailored" PDF is."""

    def __init__(self, pdf: Path) -> None:
        self.calls = 0
        self.pdf = pdf

    async def __call__(self, *a: Any, **k: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(pdf_path=str(self.pdf))


def applier_for(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fmt: str = "docx",
    tailor_cv: bool | None = None,
    live: bool = False,
    lo: bool = True,
    tectonic: bool = False,
) -> tuple[runner.Applier, Tailor, int]:
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    cvs = settings.data_dir / "cvs"
    (cvs / "original").mkdir(parents=True)
    base = cvs / ("cv.tex" if fmt == "tex" else "cv.docx")
    base.write_bytes(b"base")
    if fmt in ("pdf", "odt"):
        (cvs / "original" / f"cv.{fmt.upper()}").write_bytes(b"original")  # case as uploaded
    with db.begin() as s:
        s.add(Profile(id=1, full_name="Me", email="me@x.io", cv_path=str(base),
                      cv_source_format=fmt))  # fmt: skip
        job = Job(source="x", url="https://x/1", title="Dev", company="Acme", location="",
                  description="", ats="greenhouse", dedupe_hash="h", state=JobState.queued_apply)  # fmt: skip
        s.add(job)
        s.flush()
        job_id = job.id
    monkeypatch.setattr(tailor_pipeline, "soffice_path", lambda: "soffice" if lo else None)
    monkeypatch.setattr(tailor_pipeline, "tectonic_path", lambda: "tectonic" if tectonic else None)
    spy = Tailor(tmp_path / "tailored.pdf")
    monkeypatch.setattr(runner, "tailor_job", spy)
    cfg = SearchConfig.model_validate({"apply": {"tailor_cv": tailor_cv, "live": live}})
    return runner.Applier(db, settings, cfg, NoAI(), fake_embed), spy, job_id


def skipped_event(applier: runner.Applier, job_id: int) -> JobEvent | None:
    with applier.db() as s:
        job = s.get_one(Job, job_id)
        assert job.state == JobState.tailored
        return next((e for e in job.events if e.code == "tailor_skipped"), None)


def test_declined_tailoring_sends_the_original_file_with_no_ai_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, spy, job_id = applier_for(tmp_path, monkeypatch, tailor_cv=False, live=True)
    path = asyncio.run(a._cv_pdf(job_id))
    assert Path(path).name == "cv.docx" and spy.calls == 0  # LibreOffice is there; still declined
    event = skipped_event(a, job_id)
    assert event and event.params == {"reason": "declined"}


@pytest.mark.parametrize("fmt", ["pdf", "odt"])
def test_original_is_the_uploaded_pdf_or_odt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fmt: str
) -> None:
    a, spy, job_id = applier_for(tmp_path, monkeypatch, fmt=fmt, tailor_cv=False)
    assert Path(asyncio.run(a._cv_pdf(job_id))).name == f"cv.{fmt.upper()}" and spy.calls == 0


@pytest.mark.parametrize("choice", [None, True])
def test_practice_without_libreoffice_uses_the_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, choice: bool | None
) -> None:
    a, spy, job_id = applier_for(tmp_path, monkeypatch, tailor_cv=choice, lo=False)
    assert Path(asyncio.run(a._cv_pdf(job_id))).name == "cv.docx" and spy.calls == 0
    event = skipped_event(a, job_id)
    assert event and event.params == {"reason": "no_libreoffice"}
    assert event.message == "using your CV as it is (not tailored)"


@pytest.mark.parametrize("choice", [None, True])
def test_real_applications_without_libreoffice_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, choice: bool | None
) -> None:
    a, spy, job_id = applier_for(tmp_path, monkeypatch, tailor_cv=choice, live=True, lo=False)
    with pytest.raises(runner.ApplyBlocked) as e:
        asyncio.run(a._cv_pdf(job_id))
    assert e.value.code == "needs_libreoffice" and spy.calls == 0
    with a.db() as s:
        assert s.get_one(Job, job_id).state == JobState.queued_apply  # untouched


@pytest.mark.parametrize("live", [False, True])
def test_chosen_tailoring_with_libreoffice_never_sends_an_untailored_cv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live: bool
) -> None:
    a, spy, job_id = applier_for(tmp_path, monkeypatch, tailor_cv=True, live=live)
    assert asyncio.run(a._cv_pdf(job_id)) == str(spy.pdf) and spy.calls == 1
    with a.db() as s:
        assert not any(e.code == "tailor_skipped" for e in s.get_one(Job, job_id).events)


def test_latex_needs_tectonic_whatever_the_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for choice in (False, True):
        a, _, job_id = applier_for(
            tmp_path / str(choice), monkeypatch, fmt="tex", tailor_cv=choice, lo=True
        )
        with pytest.raises(runner.ApplyBlocked) as e:
            asyncio.run(a._cv_pdf(job_id))  # LibreOffice does not help a LaTeX CV
        assert e.value.code == "needs_tectonic"


def test_apply_choice_round_trips_through_search(client: TestClient) -> None:
    assert client.get("/api/search").json()["apply"]["tailor_cv"] is None
    put_cfg(client, apply={"tailor_cv": False})
    assert client.get("/api/search").json()["apply"]["tailor_cv"] is False


# --- preflight ------------------------------------------------------------------------


def test_real_run_start_says_up_front_that_libreoffice_is_needed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stage(name: str, *a: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(pipeline, "_run_stage", stage)
    monkeypatch.setattr(tailor_pipeline, "soffice_path", lambda: None)
    client.put("/api/profile", json={"full_name": "J", "email": "j@x.io"}, headers=H)
    cv = make_cv(client.app.state.settings.data_dir.parent / "cv.docx").read_bytes()  # type: ignore[attr-defined]
    client.post("/api/profile/cv", params={"filename": "cv.docx"}, content=cv, headers=H)

    put_cfg(client, apply={"live": True})  # undecided counts as tailoring
    r = client.post("/api/runs", json={"stages": ["apply"]}, headers=H)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "needs_libreoffice" and r.json()["detail"]["message"]
    assert client.get("/api/runs").json()["recent"] == []  # no run row was started

    put_cfg(client, apply={"live": False})  # practice mode works with the original CV
    assert start(client, ["apply"]) == 202
    wait_idle(client)
    put_cfg(client, apply={"live": True, "tailor_cv": False})  # declined: no LibreOffice needed
    assert start(client, ["apply"]) == 202
    wait_idle(client)
    put_cfg(client, apply={"live": True, "tailor_cv": True})
    assert start(client, ["apply"]) == 409
    assert start(client, ["discover"]) == 202  # searching never needs it
    wait_idle(client)


# --- 4. message codes -----------------------------------------------------------------


def test_discovered_jobs_get_a_found_by_event(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    with db.begin() as s:
        run = Run()
        s.add(run)
        s.flush()
        run_id, d = run.id, Deduper(s)
    stub = JobStub(source="greenhouse", url="https://x.io/1", title="Dev", company="A", location="")
    store_page(db, run_id, "k", 0, [stub], d)
    with db() as s:
        (event,) = s.get_one(Job, 1).events
    assert (event.code, event.params, event.from_state) == (
        "found_by",
        {"source": "greenhouse"},
        None,
    )
    assert event.message == "found by greenhouse"


def test_log_lines_carry_a_code_and_params() -> None:
    async def go() -> list[dict[str, Any]]:
        bus = EventBus()
        bus.bind(asyncio.get_running_loop())
        sink = logger.add(bus.log_sink, level="INFO")
        try:
            logger.bind(code="apply_start", params={"jobs": 4, "sites": 2}).info("apply: 4 jobs")
            logger.info("plain line")
            await asyncio.sleep(0.05)
        finally:
            logger.remove(sink)
        return [e for e in bus.recent if e["type"] == "log"]

    coded, plain = asyncio.run(go())
    assert (coded["code"], coded["params"]) == ("apply_start", {"jobs": 4, "sites": 2})
    assert coded["message"] == "apply: 4 jobs" and "code" not in plain


def test_question_hints_have_codes() -> None:
    from linkit_all.apply.answers import reason_code

    assert reason_code("nationality not set in your profile") == (
        "not_in_profile",
        {"what": "nationality"},
    )
    assert reason_code("work authorization: country unknown or not set in your profile") == (
        "not_in_profile",
        {"what": "work authorization"},
    )
    assert reason_code("criminal question: only you can answer") == (
        "own_answer",
        {"what": "criminal"},
    )
    assert reason_code("salary expectation needed")[0] == "not_in_profile"
    assert reason_code("no saved answer")[0] == "no_saved_answer"
    assert reason_code("something new") == ("other", {})
