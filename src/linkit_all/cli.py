"""`linkit` command-line entry point."""

import asyncio
import shutil
import sys
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, NamedTuple

import typer
from pydantic import ValidationError

from linkit_all.core.config import Settings, get_settings
from linkit_all.core.db import init_db
from linkit_all.core.log import setup_logging
from linkit_all.core.profile import ProfileIn, import_profile
from linkit_all.core.tools import chrome_path, soffice_path
from linkit_all.providers import ProviderError, get_provider

app = typer.Typer(no_args_is_help=True, add_completion=False)
profile_app = typer.Typer(no_args_is_help=True, help="Manage your profile.")
app.add_typer(profile_app, name="profile")

ProviderOpt = Annotated[str | None, typer.Option(help="codex_cli | claude_cli | litellm")]
ModelOpt = Annotated[str | None, typer.Option(help="Model name; default = provider's own.")]


class Check(NamedTuple):
    name: str
    path: str | None
    required: bool
    hint: str


def run_checks() -> list[Check]:
    py_ok = sys.version_info >= (3, 11)
    return [
        Check("Python >= 3.11", sys.executable if py_ok else None, True, "uv python install 3.12"),
        Check("LibreOffice", soffice_path(), True, "https://www.libreoffice.org/download/"),
        Check("Google Chrome", chrome_path(), False, "needed to apply: https://www.google.com/chrome/"),
        Check("Codex CLI", shutil.which("codex"), False, "npm i -g @openai/codex"),
        Check("Claude CLI", shutil.which("claude"), False, "https://claude.com/claude-code"),
        Check("Tectonic", shutil.which("tectonic"), False, "LaTeX CVs only: https://tectonic-typesetting.github.io"),
    ]  # fmt: skip


def _settings(provider: str | None = None, model: str | None = None) -> Settings:
    overrides = {k: v for k, v in {"provider": provider, "model": model}.items() if v}
    try:
        return Settings.model_validate({**get_settings().model_dump(), **overrides})
    except ValidationError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e


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
def ai_check(provider: ProviderOpt = None, model: ModelOpt = None) -> None:
    """Send a tiny test prompt to the configured AI provider."""
    settings = _settings(provider, model)
    if settings.provider.endswith("_cli"):
        typer.echo("Note: CLI usage counts against your own plan limits.")
    try:
        typer.echo(asyncio.run(get_provider(settings).check()))
    except ProviderError as e:
        typer.echo(f"AI check failed: {e}", err=True)
        raise typer.Exit(1) from e


@profile_app.command("import")
def profile_import(path: Path) -> None:
    """Load profile.json: full_name, email, phone, location, skills, cv_path, locked_facts."""
    try:
        data = ProfileIn.model_validate_json(path.read_text("utf-8"))
    except (OSError, ValidationError) as e:
        typer.echo(f"Cannot import {path}: {e}", err=True)
        raise typer.Exit(1) from e
    settings = get_settings()
    cv = import_profile(init_db(settings.db_path), data, settings.data_dir)
    typer.echo(
        f"Saved profile for {data.full_name}: {len(data.locked_facts)} locked facts, CV {cv}"
    )


@app.command()
def tailor(
    jd: Annotated[Path, typer.Argument(help="Text file with the job description.")],
    title: Annotated[str, typer.Option(help="Job title.")] = "",
    company: Annotated[str, typer.Option(help="Company name.")] = "",
    out: Annotated[Path | None, typer.Option(help="Output folder.")] = None,
    provider: ProviderOpt = None,
    model: ModelOpt = None,
) -> None:
    """Tailor your CV to a job description and print the red-line patch list."""
    from linkit_all.tailor.pipeline import TailorError, load_profile, tailor_for
    from linkit_all.tailor.render.libreoffice import RenderError

    settings = _settings(provider, model)
    setup_logging(settings)
    db = init_db(settings.db_path)
    out_dir = out or settings.data_dir / "tailored" / f"adhoc-{datetime.now():%Y%m%d-%H%M%S}"
    try:
        profile, facts = load_profile(db)
        result = asyncio.run(
            tailor_for(
                profile, facts, title, company, jd.read_text("utf-8"),
                get_provider(settings, cache=db), settings, out_dir,
            )
        )  # fmt: skip
    except (TailorError, ProviderError, RenderError, OSError) as e:
        typer.echo(f"Tailoring failed: {e}", err=True)
        raise typer.Exit(1) from e

    for p in result.applied:
        typer.echo(f"[{p.segment_id}] {p.reason}")
        typer.secho(f"  - {p.old_text}", fg="red")
        typer.secho(f"  + {p.new_text}", fg="green")
    for p, why in result.rejected:
        typer.secho(f"[{p.segment_id}] rejected: {why}", fg="yellow")
        typer.echo(f"  {p.old_text!r} -> {p.new_text!r}")
    if result.verify:
        v = result.verify
        typer.echo(
            f"Layout check: {'ok' if v.ok else 'FAILED'} (worst SSIM {v.min_ssim:.3f}) {v.reason}"
        )
    typer.echo(f"{len(result.applied)} applied, {len(result.rejected)} rejected -> {result.pdf}")
