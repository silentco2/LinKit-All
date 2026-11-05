# ruff: noqa: F811
"""Readable names for added sources ("Stripe · Greenhouse") and the structured AI-check result."""

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from test_api import SAME_ORIGIN, client, mem_keyring  # noqa: F401  (fixtures)

from linkit_all.core.search import SearchConfig, SourcesSection, load_search, save_search
from linkit_all.providers import base
from linkit_all.providers.claude_cli import ClaudeCLI
from linkit_all.sources import labels, registry
from linkit_all.sources.ats_detector import detect

Handler = Callable[[httpx.Request], httpx.Response]


def serve(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    monkeypatch.setattr(labels, "_TRANSPORT", httpx.MockTransport(handler))


def page(html: str) -> Handler:
    return lambda request: httpx.Response(200, text=html)


def add(client: TestClient, value: str) -> Any:
    r = client.post("/api/sources/add", json={"value": value}, headers=SAME_ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


# --- ATS labels (no network) --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("greenhouse:stripe", "Stripe · Greenhouse"),
        ("https://boards.greenhouse.io/stripe", "Stripe · Greenhouse"),
        ("https://jobs.lever.co/palantir", "Palantir · Lever"),
        ("https://jobs.ashbyhq.com/notion", "Notion · Ashby"),
        ("https://jobs.smartrecruiters.com/BoschGroup", "BoschGroup · SmartRecruiters"),
        ("https://acme.wd5.myworkdayjobs.com/en-US/Careers", "Acme · Workday"),
        ("lever:my-company_x", "My Company X · Lever"),
    ],
)
def test_ats_label(text: str, label: str) -> None:
    assert labels.offline_label(text) == label


def test_every_platform_has_a_label_and_the_map_names_real_platforms() -> None:
    ats = {s.name for s in registry().values() if s.kind == "ats"}
    assert set(labels.PLATFORMS) <= ats  # no stale keys
    for name in ats:
        assert labels.ats_label(name, "acme").startswith("Acme · ")
        assert detect(f"{name}:acme") == (name, "acme")


def test_domain_fallback() -> None:
    assert labels.domain_name("https://www.notion.com/careers") == "notion.com"
    assert labels.domain_name("careers.notion.com/jobs") == "notion.com"
    assert labels.domain_name("https://jobs.example.co.uk/x") == "example.co.uk"


# --- careers pages: one fetch --------------------------------------------------------------


def test_title_is_cut_at_the_first_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="<title>Notion - Jobs | Careers</title>")

    serve(monkeypatch, handler)
    assert labels.careers_label("https://notion.com/careers") == "Notion · careers page"
    assert len(seen) == 1 and seen[0].headers["user-agent"].startswith("LinKitAll")
    serve(monkeypatch, page("<title>Acme \u2013 Careers</title>"))
    assert labels.careers_label("https://acme.com/jobs") == "Acme · careers page"


def test_og_site_name_beats_the_title(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        "<head><title>Jobs | Whatever</title>"
        '<meta property="og:site_name" content="Notion Labs"></head>'
    )
    serve(monkeypatch, page(html))
    assert labels.careers_label("https://notion.com/careers") == "Notion Labs · careers page"


def test_redirects_are_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "old.example.com":
            return httpx.Response(301, headers={"location": "https://new.example.com/jobs"})
        return httpx.Response(200, text="<title>Newco | Jobs</title>")

    serve(monkeypatch, handler)
    assert labels.careers_label("https://old.example.com/") == "Newco · careers page"


@pytest.mark.parametrize("failure", ["timeout", "refused", "500", "no title"])
def test_failures_fall_back_to_the_domain(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        if failure == "refused":
            raise httpx.ConnectError("refused", request=request)
        if failure == "500":
            return httpx.Response(500, text="<title>Oops</title>")
        return httpx.Response(200, text="<html><body>hi</body></html>")

    serve(monkeypatch, handler)
    assert labels.careers_label("https://www.notion.com/careers") == "notion.com · careers page"


def test_timeout_is_about_five_seconds() -> None:
    assert labels.TIMEOUT_S == 5


# --- the API -------------------------------------------------------------------------------


def test_add_returns_and_stores_the_label(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(monkeypatch, page("<title>Notion | Careers</title>"))
    ats = add(client, "https://boards.greenhouse.io/stripe")
    assert ats["label"] == "Stripe · Greenhouse"
    careers = add(client, "https://www.notion.com/careers")
    assert (careers["kind"], careers["label"]) == ("careers", "Notion · careers page")
    want = {
        "https://boards.greenhouse.io/stripe": "Stripe · Greenhouse",
        "https://www.notion.com/careers": "Notion · careers page",
    }
    assert careers["config"]["company_labels"] == want
    assert client.get("/api/search").json()["sources"]["company_labels"] == want
    assert add(client, "@my_channel")["label"] == "@my_channel"  # Telegram keeps its @name


def test_add_with_a_dead_site_uses_the_domain(client: TestClient) -> None:  # offline by conftest
    assert add(client, "careers.example.com/jobs")["label"] == "example.com · careers page"


def test_get_computes_missing_labels_without_saving(client: TestClient) -> None:
    db = client.app.state.db  # type: ignore[attr-defined]
    stored = {"https://jobs.lever.co/palantir": "Palantir Technologies · Lever"}
    companies = ["greenhouse:stripe", "https://jobs.lever.co/palantir", "https://acme.com/jobs"]
    save_search(
        db, SearchConfig(sources=SourcesSection(companies=companies, company_labels=stored))
    )
    got = client.get("/api/search").json()["sources"]["company_labels"]
    assert got == {
        "greenhouse:stripe": "Stripe · Greenhouse",
        "https://jobs.lever.co/palantir": "Palantir Technologies · Lever",  # stored wins
        "https://acme.com/jobs": "acme.com · careers page",
    }
    saved = load_search(db)
    assert saved is not None and saved.sources.company_labels == stored  # GET wrote nothing


def test_removing_a_company_drops_its_label(client: TestClient) -> None:
    add(client, "greenhouse:stripe")
    add(client, "lever:acme")
    cfg = client.get("/api/search").json()
    assert len(cfg["sources"]["company_labels"]) == 2
    cfg["sources"]["companies"] = ["lever:acme"]
    saved = client.put("/api/search", json=cfg, headers=SAME_ORIGIN).json()
    assert saved["sources"]["company_labels"] == {"lever:acme": "Acme · Lever"}


def test_old_config_without_labels_loads() -> None:
    cfg = SearchConfig.model_validate({"sources": {"companies": ["greenhouse:stripe"]}})
    assert cfg.sources.company_labels == {}
    assert SourcesSection().company_labels == {}


# --- structured AI-test result --------------------------------------------------------------


class Fine(base.LLMProvider):
    name = "fake"

    def __init__(self, version: str | None) -> None:
        super().__init__("fake")
        self.version = version

    async def check(self) -> str:
        return "fake ok"

    async def _call(self, prompt: str) -> str:
        return "{}"


@pytest.mark.parametrize(
    ("body", "label", "model", "version"),
    [
        ({"provider": "codex_cli"}, "ChatGPT (Codex)", None, "codex 0.1"),
        ({"provider": "claude_cli", "model": "sonnet"}, "Claude", "sonnet", "2.1.305"),
        ({"provider": "litellm", "model": "openai/gpt-5"}, "API key", "openai/gpt-5", None),
        (
            {"provider": "litellm", "model": "openai/g", "api_base": "http://127.0.0.1:1234/v1"},
            "Local model",
            "openai/g",
            None,
        ),
    ],
)
def test_ai_check_structured_success(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, str],
    label: str,
    model: str | None,
    version: str | None,
) -> None:
    monkeypatch.setattr("linkit_all.providers.get_provider", lambda *a, **k: Fine(version))
    got = client.post("/api/ai/check", json=body, headers=SAME_ORIGIN).json()
    assert got == {
        "ok": True,
        "provider": body["provider"],
        "provider_label": label,
        "model": model,
        "version": version,
        "message": "fake ok",
    }


def test_cli_check_records_the_version(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str], *a: Any) -> tuple[int, str, str]:
        return 0, "2.1.305 (Claude Code)\n", ""

    async def ping(self: Any, *a: Any, **k: Any) -> Any:
        return base.Ping(ok=True)

    monkeypatch.setattr(base, "run_cli", fake_run)
    monkeypatch.setattr(base.LLMProvider, "complete", ping)
    monkeypatch.setattr(base.shutil, "which", lambda b: "claude")
    p = ClaudeCLI(None)
    assert asyncio.run(p.check()).endswith("2.1.305 (Claude Code)")
    assert p.version == "2.1.305 (Claude Code)"
