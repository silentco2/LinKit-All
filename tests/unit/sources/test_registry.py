import asyncio
import re
import textwrap
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from loguru import logger

from linkit_all.core.db import init_db
from linkit_all.core.runs import current_run
from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http
from linkit_all.sources.runner import discover

LEGACY = {
    "greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "workable", "workday",
    "linkedin", "indeed", "glassdoor", "google", "zip_recruiter", "bayt",
    "wuzzuf", "forasna", "careers",
}  # fmt: skip

TOY = textwrap.dedent("""
    import re
    from linkit_all.sources.base import JobStub, Source, Task

    class ToyBoard(Source):
        name = "toyboard"
        kind = "board"

        def tasks(self, cfg):
            return [Task(self.name, "toyboard:1", query="x")]

        async def search(self, http, task, start_page):
            yield [JobStub(source=self.name, url="https://toy.example/1", title="Toy job",
                           company="Toy Co", description="d")]

    class ToyAts(Source):
        name = "toyats"
        kind = "ats"
        url_patterns = (re.compile(r"toyats\\.example/([\\w-]+)"),)

        async def search(self, http, task, start_page):
            yield []
""")


def toy_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: dict[str, str]) -> str:
    name = f"toy_{tmp_path.name}"  # unique: sys.modules caches packages by name
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "toys.py").write_text(TOY)
    for mod, code in extra.items():
        (pkg / f"{mod}.py").write_text(code)
    monkeypatch.syspath_prepend(str(tmp_path))
    return name


@pytest.fixture
def warnings() -> Any:
    seen: list[str] = []
    hid = logger.add(lambda m: seen.append(str(m)), level="WARNING", format="{message}")
    yield seen
    logger.remove(hid)


def test_registry_finds_every_existing_source() -> None:
    found = registry()
    assert set(found) >= LEGACY
    assert all(found[n].name == n for n in found)
    assert found["workday"].kind == "ats" and found["wuzzuf"].kind == "regional"
    assert found["linkedin"].kind == "jobspy" and found["careers"].kind == "careers"


def test_registry_passes_provider_and_data_dir(tmp_path: Path) -> None:
    careers = registry(None, tmp_path)["careers"]
    assert careers.provider is None  # type: ignore[attr-defined]


def test_toy_plugin_discovered_and_enabled_by_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkg = toy_package(tmp_path, monkeypatch, {})
    found = registry(extra_packages=[pkg])
    assert set(found) >= LEGACY and {"toyboard", "toyats"} <= set(found)
    toy = found["toyboard"]
    off = SearchConfig()
    on = SearchConfig.model_validate({"sources": {"enabled": ["toyboard"]}})
    assert not toy.is_enabled(off) and toy.is_enabled(on)
    assert found["wuzzuf"].is_enabled(off)  # self-gating kinds are always asked
    toy.default_on = True
    assert toy.is_enabled(off)

    db = init_db(tmp_path / "t.db")

    async def run(cfg: SearchConfig) -> Any:
        transport = httpx.MockTransport(lambda r: httpx.Response(404))
        async with httpx.AsyncClient(transport=transport) as c:
            return await discover(db, cfg, current_run(db), Http(c, attempts=1), {"toyboard": toy})

    toy.default_on = False
    assert asyncio.run(run(off)).new == 0
    assert asyncio.run(run(on)).new == 1


def test_toy_ats_pattern_feeds_detector(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = toy_package(tmp_path, monkeypatch, {})
    sources = registry(extra_packages=[pkg]).values()
    assert detect("https://toyats.example/acme/jobs", sources) == ("toyats", "acme")
    assert detect("toyats:acme", sources) == ("toyats", "acme")
    assert detect("https://boards.greenhouse.io/stripe", sources) == ("greenhouse", "stripe")
    assert detect("toyats:acme") is None  # not in the default registry


def test_broken_module_is_skipped_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warnings: list[str]
) -> None:
    pkg = toy_package(
        tmp_path,
        monkeypatch,
        {
            "broken": "raise RuntimeError('boom')",
            "needsarg": (
                "from linkit_all.sources.base import Source\n"
                "class NeedsArg(Source):\n"
                "    name = 'needsarg'\n"
                "    kind = 'board'\n"
                "    def __init__(self, token): ...\n"
                "    async def search(self, http, task, start_page):\n"
                "        yield []\n"
            ),
        },
    )
    found = registry(extra_packages=[pkg])
    assert "toyboard" in found and "needsarg" not in found
    assert any(f"{pkg}.broken" in w and "boom" in w for w in warnings)
    assert any(f"{pkg}.needsarg" in w for w in warnings)


def test_missing_package_and_duplicate_names_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warnings: list[str]
) -> None:
    dup = TOY.replace("toyats", "greenhouse").replace("ToyAts", "GreenhouseAgain")
    pkg = toy_package(tmp_path, monkeypatch, {"dup": dup})
    found = registry(extra_packages=[pkg, "no.such.package"])
    assert type(found["greenhouse"]).__module__ == "linkit_all.sources.greenhouse"
    assert any("no.such.package" in w for w in warnings)
    assert any("duplicate" in w for w in warnings)


def test_hook_module_supplies_its_own_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = (
        "from linkit_all.sources.base import Source\n"
        "class Multi(Source):\n"
        "    kind = 'board'\n"
        "    def __init__(self, name): self.name = name\n"
        "    async def search(self, http, task, start_page):\n"
        "        yield []\n"
        "def sources(**ctx): return [Multi('multi_a'), Multi('multi_b')]\n"
    )
    pkg = toy_package(tmp_path, monkeypatch, {"multi": hook})
    assert {"multi_a", "multi_b"} <= set(registry(extra_packages=[pkg]))


def test_every_ats_declares_patterns_and_detects_itself() -> None:
    found = registry()
    for name in ("greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "workable"):
        assert found[name].url_patterns, name
        assert all(isinstance(p, re.Pattern) for p in found[name].url_patterns)
        assert detect(f"{name}:slug") == (name, "slug")


class _Counts(Source):  # kept here so type checking covers the abstract signature
    name = "c"

    def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        raise NotImplementedError


def test_search_config_enabled_defaults_empty() -> None:
    assert SearchConfig().sources.enabled == []
    f: Callable[[], Source] = _Counts
    assert f().kind == "ats" and not f().default_on
