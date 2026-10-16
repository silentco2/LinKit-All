import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from linkit_all import cli
from linkit_all.core.config import get_settings
from linkit_all.core.tools import find_tool, soffice_path

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_doctor_fails_when_required_tool_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    checks = [cli.Check("LibreOffice", None, True, "x"), cli.Check("Codex CLI", None, False, "y")]
    monkeypatch.setattr(cli, "run_checks", lambda: checks)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 1
    assert "[MISSING] LibreOffice" in result.output
    assert "[optional] Codex CLI" in result.output


def test_doctor_passes_when_required_tools_found(monkeypatch: pytest.MonkeyPatch) -> None:
    checks = [cli.Check("LibreOffice", "/bin/soffice", True, "x"), cli.Check("C", None, False, "")]
    monkeypatch.setattr(cli, "run_checks", lambda: checks)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    assert "MISSING" not in result.output


def test_find_tool_uses_fallback_path(tmp_path: Path) -> None:
    exe = tmp_path / "soffice.exe"
    exe.touch()
    assert find_tool(["no-such-binary-xyz"], [tmp_path / "nope", exe]) == str(exe)


def test_install_libreoffice_zip_is_found_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LINKIT_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    bundle = tmp_path / "lo.zip"
    with zipfile.ZipFile(bundle, "w") as z:
        z.writestr("program/soffice.exe", "")
    try:
        result = runner.invoke(cli.app, ["install-libreoffice", str(bundle)])
        assert result.exit_code == 0, result.output
        assert soffice_path() == str(tmp_path / "data/tools/libreoffice/program/soffice.exe")

        with zipfile.ZipFile(bundle, "w") as z:
            z.writestr("readme.txt", "")
        assert runner.invoke(cli.app, ["install-libreoffice", str(bundle)]).exit_code == 1
    finally:
        get_settings.cache_clear()


def test_search_import_and_empty_discover(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINKIT_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    toml = tmp_path / "search.toml"
    toml.write_text('[search]\nqueries = ["python developer"]\n', encoding="utf-8")
    try:
        assert runner.invoke(cli.app, ["run", "discover"]).exit_code == 1  # nothing imported
        result = runner.invoke(cli.app, ["search", "import", str(toml)])
        assert result.exit_code == 0, result.output
        assert "1 queries" in result.output
        result = runner.invoke(cli.app, ["run", "discover"])
        assert result.exit_code == 0, result.output
        assert "Run 1: 0 new jobs" in result.output
        assert runner.invoke(cli.app, ["status"]).exit_code == 0
    finally:
        get_settings.cache_clear()


def test_doctor_finds_tectonic_through_the_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "tectonic_path", lambda: "/cargo/bin/tectonic")
    tectonic = next(c for c in cli.run_checks() if c.name == "Tectonic")
    assert tectonic.path == "/cargo/bin/tectonic"
