from pathlib import Path

import pytest
from typer.testing import CliRunner

from linkit_all import cli
from linkit_all.core.tools import find_tool

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
