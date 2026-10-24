"""`linkit` command-line entry point."""

import asyncio
import shutil
import sys
import tomllib
import zipfile
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NamedTuple

import typer
from pydantic import ValidationError
from sqlalchemy import func, select

from linkit_all.core.config import Settings, get_settings
from linkit_all.core.db import init_db
from linkit_all.core.log import setup_logging
from linkit_all.core.models import Job
from linkit_all.core.profile import ProfileIn, import_profile
from linkit_all.core.runs import current_run
from linkit_all.core.search import import_search
from linkit_all.core.tools import bundled_libreoffice, chrome_path, soffice_path, tectonic_path
from linkit_all.providers import ProviderError, get_provider

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


app = typer.Typer(add_completion=False)
profile_app = typer.Typer(no_args_is_help=True, help="Manage your profile.")
app.add_typer(profile_app, name="profile")
search_app = typer.Typer(no_args_is_help=True, help="Manage what to search for.")
app.add_typer(search_app, name="search")
run_app = typer.Typer(no_args_is_help=True, help="Run one pipeline stage.")
app.add_typer(run_app, name="run")

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
        Check("Tectonic", tectonic_path(), False, "LaTeX CVs only: https://tectonic-typesetting.github.io"),
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


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    _version: Annotated[
        bool, typer.Option("--version", callback=_show_version, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    """LinKit All: AI job search, CV tailoring and auto-apply. No command: open the UI."""
    if ctx.invoked_subcommand is None:
        serve()


@app.command()
def serve(
    port: Annotated[int, typer.Option(help="Local port.")] = 8765,
    open_browser: Annotated[bool, typer.Option("--open/--no-open", help="Open a browser.")] = True,
) -> None:
    """Start the local web UI on 127.0.0.1."""
    from linkit_all.api.app import serve as run_server

    run_server(port=port, open_browser=open_browser)


@app.command()
def doctor() -> None:
    """Check the external tools LinKit All depends on."""
    checks = run_checks()
    for c in checks:
        mark = "ok" if c.path else ("MISSING" if c.required else "optional")
        typer.echo(f"[{mark}] {c.name}: {c.path or c.hint}")
    if any(c.required and not c.path for c in checks):
        raise typer.Exit(1)


@app.command("install-libreoffice")
def install_libreoffice(
    source: Annotated[Path, typer.Argument(help="Minimal LibreOffice zip or folder.")],
) -> None:
    """Install the minimal portable LibreOffice (from scripts/bundle_libreoffice.py)."""
    dest = bundled_libreoffice()
    shutil.rmtree(dest, ignore_errors=True)
    if source.is_dir():
        shutil.copytree(source, dest)
    else:
        with zipfile.ZipFile(source) as z:
            z.extractall(dest)  # zipfile strips absolute paths and ".." parts
    if not (dest / "program" / "soffice.exe").is_file():
        shutil.rmtree(dest, ignore_errors=True)
        typer.echo(f"{source} does not contain program/soffice.exe", err=True)
        raise typer.Exit(1)
    typer.echo(f"LibreOffice installed to {dest}")


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


def _stage_db() -> "sessionmaker[Session]":
    settings = get_settings()
    setup_logging(settings)
    return init_db(settings.db_path)


@search_app.command("import")
def search_import(path: Path) -> None:
    """Load search.toml: queries, locations, companies, sites, filters, tiers."""
    try:
        cfg = import_search(init_db(get_settings().db_path), path)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as e:
        typer.echo(f"Cannot import {path}: {e}", err=True)
        raise typer.Exit(1) from e
    sites = cfg.sources.jobspy + cfg.sources.regional
    typer.echo(
        f"Saved search: {len(cfg.search.queries)} queries x {len(cfg.search.locations)} "
        f"locations, {len(cfg.sources.companies)} companies, sites: {', '.join(sites) or 'none'}"
    )


def _run_stage(stage: str, new: bool = False, **ai: str | None) -> tuple[int, dict[str, Any]]:
    from linkit_all.pipeline import PipelineError, run_stage

    db = _stage_db()
    run_id = current_run(db, new)
    try:
        override = {k: v for k, v in ai.items() if v}
        return run_id, asyncio.run(run_stage(stage, db, get_settings(), run_id, override))
    except PipelineError as e:
        typer.echo(f"{stage} failed: {e}", err=True)
        raise typer.Exit(1) from e


@run_app.command("discover")
def run_discover(
    new: Annotated[
        bool, typer.Option("--new", help="Start a new run instead of resuming.")
    ] = False,
) -> None:
    """Fetch jobs from every configured source (resumes an unfinished run)."""
    run_id, stats = _run_stage("discover", new)
    typer.echo(
        f"Run {run_id}: {stats['new']} new jobs, {stats['duplicates']} duplicates, "
        f"{stats['tasks_done']} tasks done"
    )
    for key, err in stats["errors"].items():
        typer.secho(f"  error {key}: {err}", fg="yellow")
    for entry in stats["unsupported"]:
        typer.secho(f"  skipped {entry}", fg="yellow")


@app.command("discover-boards")
def discover_boards_cmd(
    ats: Annotated[
        list[str] | None, typer.Option("--ats", help="Only this ATS (repeatable); default all.")
    ] = None,
    max_per_ats: Annotated[int, typer.Option(min=1, help="Boards to keep per ATS.")] = 5000,
) -> None:
    """Find company job boards in Common Crawl's index and store them for crawling."""
    from linkit_all.sources import registry
    from linkit_all.sources.discovery import DiscoveryError, discover_boards, make_http
    from linkit_all.sources.http import make_client

    db = _stage_db()

    async def go() -> dict[str, Any]:
        async with make_client() as client:
            return await discover_boards(db, make_http(client), registry(), ats or (), max_per_ats)

    try:
        results = asyncio.run(go())
    except (DiscoveryError, ValueError) as e:
        typer.echo(f"discover-boards failed: {e}", err=True)
        raise typer.Exit(1) from e
    for name, r in results.items():
        line = f"{name}: {r.found} boards found, {r.new} new"
        typer.secho(
            f"{line} (stopped: {r.error})" if r.error else line, fg="yellow" if r.error else None
        )


@run_app.command("enrich")
def run_enrich() -> None:
    """Fill in missing job descriptions (discovered -> enriched)."""
    typer.echo(f"{_run_stage('enrich')[1]['enriched']} jobs enriched")


@run_app.command("rank")
def run_rank() -> None:
    """Hard filters + free local ranking (enriched -> ranked | filtered_out)."""
    counts = _run_stage("rank")[1]
    typer.echo(f"{counts['ranked']} ranked, {counts['filtered_out']} filtered out")


@run_app.command("score")
def run_score(provider: ProviderOpt = None, model: ModelOpt = None) -> None:
    """AI-tier the best ranked jobs: high -> apply queue, mid -> review, low -> hidden."""
    counts = _run_stage("score", provider=provider, model=model)[1]
    typer.echo(
        f"high {counts['high']} (auto-apply), mid {counts['mid']} (your review), "
        f"low {counts['low']}, not scored {counts['not_scored']}"
    )


@app.command()
def status() -> None:
    """Job counts by pipeline state and tier."""
    db = init_db(get_settings().db_path)
    with db() as s:
        by_state = s.execute(select(Job.state, func.count()).group_by(Job.state)).all()
        by_tier = s.execute(
            select(Job.tier, func.count()).where(Job.tier.is_not(None)).group_by(Job.tier)
        ).all()
    for state, n in sorted(by_state, key=lambda r: -r[1]):
        typer.echo(f"{state:<16} {n}")
    if by_tier:
        typer.echo("tiers: " + ", ".join(f"{t} {n}" for t, n in by_tier))


@app.command()
def jobs(
    tier: Annotated[str | None, typer.Option(help="high | mid | low")] = None,
    state: Annotated[str | None, typer.Option(help="e.g. ranked, awaiting_review")] = None,
    limit: Annotated[int, typer.Option(help="Rows to show.")] = 20,
) -> None:
    """List jobs, best first."""
    db = init_db(get_settings().db_path)
    query = select(Job)
    if tier:
        query = query.where(Job.tier == tier)
    if state:
        query = query.where(Job.state == state)
    with db() as s:
        rows = list(s.scalars(query))
    rows.sort(key=lambda j: (-(j.score or 0), -j.data.get("rank", 0)))
    for j in rows[:limit]:
        score = f"{j.score:>2}" if j.score else " -"
        head = f"{j.id:>6} {score} {j.data.get('rank', 0):.2f} {j.state:<15}"
        typer.echo(f"{head} {j.title[:45]:<45} | {j.company[:25]} | {j.location[:30]}")


@run_app.command("apply")
def run_apply() -> None:
    """Tailor and fill applications: a dry run unless Live applying is on in settings."""
    counts = _run_stage("apply")[1]
    typer.echo(", ".join(f"{k} {v}" for k, v in counts.items()))
