"""`linkit` command-line entry point."""

import asyncio
import os
import shutil
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, NamedTuple

import typer
from pydantic import ValidationError

from linkit_all.core.config import Settings, get_settings
from linkit_all.providers import ProviderError, get_provider

app = typer.Typer(no_args_is_help=True, add_completion=False)


class Check(NamedTuple):
    name: str
    path: str | None
    required: bool
    hint: str


def _find(names: list[str], fallbacks: list[Path]) -> str | None:
    """First executable on PATH, else first existing fallback (Windows/macOS install dirs)."""
    for name in names:
        if found := shutil.which(name):
            return found
    return next((str(p) for p in fallbacks if p.is_file()), None)


def run_checks() -> list[Check]:
    program_dirs = [
        Path(v)
        for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")
        if (v := os.environ.get(k))
    ]
    soffice = [d / "LibreOffice/program/soffice.exe" for d in program_dirs]
    soffice.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    chrome = [d / "Google/Chrome/Application/chrome.exe" for d in program_dirs]
    chrome.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    py_ok = sys.version_info >= (3, 11)
    return [
        Check("Python >= 3.11", sys.executable if py_ok else None, True, "uv python install 3.12"),
        Check(
            "LibreOffice",
            _find(["soffice", "libreoffice"], soffice),
            True,
            "https://www.libreoffice.org/download/",
        ),
        Check(
            "Google Chrome",
            _find(["google-chrome", "google-chrome-stable", "chrome"], chrome),
            False,
            "needed to apply: https://www.google.com/chrome/",
        ),
        Check("Codex CLI", _find(["codex"], []), False, "npm i -g @openai/codex"),
        Check("Claude CLI", _find(["claude"], []), False, "https://claude.com/claude-code"),
        Check(
            "Tectonic",
            _find(["tectonic"], []),
            False,
            "LaTeX CVs only: https://tectonic-typesetting.github.io",
        ),
    ]


def _show_version(value: bool) -> None:
    if value:
        typer.echo(version("linkit-all"))
        raise typer.Exit()


@app.callback()
def main(
    _version: Annotated[
        bool, typer.Option("--version", callback=_show_version, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    """LinKit All: AI job search, CV tailoring and auto-apply."""


@app.command()
def doctor() -> None:
    """Check the external tools LinKit All depends on."""
    checks = run_checks()
    for c in checks:
        mark = "ok" if c.path else ("MISSING" if c.required else "optional")
        typer.echo(f"[{mark}] {c.name}: {c.path or c.hint}")
    if any(c.required and not c.path for c in checks):
        raise typer.Exit(1)


@app.command("ai-check")
def ai_check(
    provider: Annotated[str | None, typer.Option(help="codex_cli | claude_cli | litellm")] = None,
    model: Annotated[str | None, typer.Option(help="Model name; default = provider's own.")] = None,
) -> None:
    """Send a tiny test prompt to the configured AI provider."""
    overrides = {k: v for k, v in {"provider": provider, "model": model}.items() if v}
    try:
        settings = Settings.model_validate({**get_settings().model_dump(), **overrides})
        if settings.provider.endswith("_cli"):
            typer.echo("Note: CLI usage counts against your own plan limits.")
        typer.echo(asyncio.run(get_provider(settings).check()))
    except (ProviderError, ValidationError) as e:
        typer.echo(f"AI check failed: {e}", err=True)
        raise typer.Exit(1) from e
