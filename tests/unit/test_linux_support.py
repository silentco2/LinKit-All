"""Linux details: no screen stops the run with its own message; Snap builds are never used."""

import asyncio
from pathlib import Path

import pytest
from test_apply_skip import NoAI
from test_matching import fake_embed
from typer.testing import CliRunner

from linkit_all import cli
from linkit_all.apply import runner
from linkit_all.core import chrome, tools
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.search import SearchConfig
from linkit_all.tailor.render import libreoffice

real_profile_dir = libreoffice.profile_dir  # conftest swaps the module's name for a scratch folder


def test_no_screen_blocks_the_run_with_the_original_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PW:
        async def stop(self) -> None: ...

    class Starter:
        async def start(self) -> PW:
            return PW()

    monkeypatch.setattr(runner, "async_playwright", Starter)
    monkeypatch.setattr(chrome, "browser_path", lambda: "/usr/bin/google-chrome")
    monkeypatch.setattr(chrome.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    settings = Settings(data_dir=tmp_path / "data")
    cfg = SearchConfig.model_validate({"apply": {"headless": False}})

    async def go() -> None:
        async with runner.Applier(
            init_db(settings.db_path), settings, cfg, NoAI(), fake_embed
        ) as a:
            await a._context("lever")

    with pytest.raises(runner.ApplyBlocked, match="No screen") as e:
        asyncio.run(go())
    assert e.value.code == "no_screen"


def test_no_browser_blocks_the_run_with_its_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chrome, "browser_path", lambda: None)
    with pytest.raises(chrome.ChromeError, match="No Chromium") as e:
        asyncio.run(chrome.launch_chrome(tmp_path, headless=True))
    assert e.value.code == "no_browser"


def test_snap_paths_are_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools.shutil, "which", lambda n: f"/snap/bin/{n}")
    monkeypatch.setattr(tools.os.path, "realpath", lambda p: p)
    assert tools.find_tool(["libreoffice"], []) is None
    assert tools.snap_only(["libreoffice"])


def test_symlink_into_snap_and_user_folder_named_snap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools.os.path, "realpath", lambda p: "/snap/libreoffice/1/soffice")
    assert tools.is_snap("/usr/bin/soffice")  # a symlink whose target is in /snap
    monkeypatch.setattr(tools.os.path, "realpath", lambda p: p)
    assert not tools.is_snap("/home/snap/tools/soffice")  # only a folder called snap


def test_ubuntu_chromium_wrapper_script_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrapper = tmp_path / "chromium-browser"
    wrapper.write_text('#!/bin/sh\nexec /snap/bin/chromium "$@"\n')
    real = tmp_path / "brave"
    real.write_bytes(b"\x7fELF snap-looking binary")
    monkeypatch.setattr(
        tools.shutil, "which", lambda n: str({"chromium-browser": wrapper}.get(n, real))
    )
    assert tools.is_snap(str(wrapper))
    assert not tools.is_snap(str(real))
    assert tools.find_tool(["chromium-browser"], []) is None
    assert tools.find_tool(["brave"], []) == str(real)


def test_doctor_hints_when_only_a_snap_is_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "soffice_path", lambda: None)
    monkeypatch.setattr(cli, "snap_only", lambda names: "soffice" in names)
    out = CliRunner().invoke(cli.app, ["doctor"])
    assert "Snap builds cannot be used" in out.output


def test_libreoffice_profile_is_under_the_data_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(libreoffice, "get_settings", lambda: Settings(data_dir=tmp_path / "d"))
    path = real_profile_dir()
    assert path == tmp_path / "d" / "tools" / "lo-profile" and path.is_dir()
    assert real_profile_dir() == path  # again: no error
