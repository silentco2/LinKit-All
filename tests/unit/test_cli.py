from pathlib import Path

import pytest
from typer.testing import CliRunner

from linkit_all import cli

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_doctor_fails_when_required_tool_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_find", lambda names, fallbacks: None)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 1
    assert "[MISSING] LibreOffice" in result.output
    assert "[optional] Codex CLI" in result.output


def test_doctor_passes_when_tools_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_find", lambda names, fallbacks: "/bin/tool")
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    assert "MISSING" not in result.output


def test_find_uses_fallback_path(tmp_path: Path) -> None:
    exe = tmp_path / "soffice.exe"
    exe.touch()
    assert cli._find(["no-such-binary-xyz"], [tmp_path / "nope", exe]) == str(exe)
