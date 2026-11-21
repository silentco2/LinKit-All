"""`linkit` command-line entry point."""

import asyncio
import shutil
import sys
import tomllib
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NamedTuple

import typer
from pydantic import ValidationError
from sqlalchemy import func, select

from linkit_all.core.config import Settings, get_settings
from linkit_all.core.db import init_db
from linkit_all.core.lo_install import install_libreoffice as install_libreoffice_bundle
from linkit_all.core.log import setup_logging
from linkit_all.core.models import Job
from linkit_all.core.profile import ProfileIn, import_profile
from linkit_all.core.runs import current_run
from linkit_all.core.search import import_search
from linkit_all.core.tools import (
    BROWSER_NAMES,
    CHROMIUM_HINT,
    SOFFICE_NAMES,
    browser_path,
    snap_only,
    soffice_path,
    tectonic_path,
)
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


def lo_hint() -> str:
    """How to get LibreOffice here: the one-click bundle is Windows only."""
    if sys.platform == "darwin":
        return "brew install --cask libreoffice, or https://www.libreoffice.org/download/"
    if sys.platform.startswith("linux"):
        return "install your distribution's libreoffice-writer package (apt, dnf, pacman)"
    return 'https://www.libreoffice.org/download/, or "Install it for me" in the app'


def run_checks() -> list[Check]:
    py_ok = sys.version_info >= (3, 11, 5)
    return [
        Check("Python >= 3.11.5", sys.executable if py_ok else None, True, "uv python install 3.12"),  # noqa: E501
        Check("LibreOffice", soffice_path(), True, lo_hint()),
        Check("Chromium browser", browser_path(), False, f"needed to apply: {CHROMIUM_HINT}"),
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
        names = {"LibreOffice": SOFFICE_NAMES, "Chromium browser": BROWSER_NAMES}.get(c.name)
        if names and not c.path and snap_only(names):
            typer.echo("       Snap builds cannot be used: install the .deb or apt package.")
    if any(c.required and not c.path for c in checks):
        raise typer.Exit(1)


def _backup_folder(settings: Settings) -> Path:
    from linkit_all.core.backup import folder_for, saved_folder

    return folder_for(settings.data_dir, saved_folder(settings.db_path))


@app.command()
def backup() -> None:
    """Copy the database now (the app also makes one a day and keeps 7)."""
    from linkit_all.core.backup import backup as make_backup

    settings = get_settings()
    if not settings.db_path.exists():
        typer.echo(f"No database at {settings.db_path}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Backed up to {make_backup(settings.db_path, _backup_folder(settings))}")


@app.command()
def restore(
    path: Path,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask first.")] = False,
) -> None:
    """Put a database copy back. Close LinKit All first; the current database is saved beside
    the backups as linkit-before-restore-<time>.db."""
    from linkit_all.core.backup import check
    from linkit_all.core.backup import restore as put_back

    settings = get_settings()
    try:
        check(path)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    if not yes and not typer.confirm(
        f"Replace {settings.db_path} with {path.name}? Close LinKit All first.", default=False
    ):
        raise typer.Exit(1)
    saved = put_back(settings.db_path, path, _backup_folder(settings))
    typer.echo(f"Restored {path.name}." + (f" The previous one is in {saved}" if saved else ""))


@app.command("install-libreoffice")
def install_libreoffice(
    source: Annotated[Path, typer.Argument(help="Minimal LibreOffice zip or folder.")],
) -> None:
    """Install the minimal portable LibreOffice (from scripts/bundle_libreoffice.py)."""
    try:
        dest = install_libreoffice_bundle(source)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
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


@app.command("seed-boards")
def seed_boards_cmd() -> None:
    """Store the bundled list of company job boards (crawled only with use_discovered_boards)."""
    from linkit_all.sources.discovery import seed_boards, seed_list

    typer.echo(f"{seed_boards(_stage_db())} new boards stored (of {len(seed_list())} in the list)")


@app.command("source-check")
def source_check_cmd(
    keys: Annotated[
        list[str] | None,
        typer.Argument(help="Source names or company entries; default: all switched on."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Ignore checks under an hour old.")
    ] = False,
) -> None:
    """Probe each switched-on source and company page live (one page each) and say which work."""
    from linkit_all.pipeline import check_sources
    from linkit_all.sources.health import COMPANY

    found = asyncio.run(check_sources(_stage_db(), get_settings(), keys or None, force))
    broken = 0
    for key, h in sorted(found.items()):
        mark = {"ok": "ok", "warn": "partly", "empty": "no jobs", "broken": "BROKEN"}[
            str(h["status"])
        ]
        broken += h["status"] == "broken"
        why = f": {h['error']}" if h["error"] else ""
        typer.echo(f"[{mark}] {key.removeprefix(COMPANY)} ({h['jobs']} jobs){why}")
    if not found:
        typer.echo("Nothing switched on to check.")
    raise typer.Exit(1 if broken else 0)


@app.command("find-board")
def find_board_cmd(
    names: Annotated[list[str], typer.Argument(help="Company names, e.g. Stripe.")],
    add: Annotated[bool, typer.Option("--add", help="Save what is found.")] = False,
) -> None:
    """Look a company up on the job-board platforms we read. Shows what it finds; --add saves it."""
    from linkit_all.core.search import SearchConfig, load_search, save_search
    from linkit_all.sources import registry
    from linkit_all.sources.resolve import resolve

    db = _stage_db()
    found, missing = asyncio.run(resolve(registry(), names))
    cfg = load_search(db) or SearchConfig()
    src = cfg.sources
    for name, boards in found.items():
        for b in boards:
            new = add and b.value.lower() not in {c.lower() for c in src.companies}
            if new:
                src.companies = [*src.companies, b.value]
                src.company_labels = {**src.company_labels, b.value: b.label}
            typer.echo(f"{name}: {b.label}, {b.jobs} jobs ({b.value}){' - added' if new else ''}")
    if add and found:
        save_search(db, cfg)
    for name in missing:
        hint = "Paste its careers page in Settings > Sources."
        typer.secho(f"{name}: no board found. {hint}", fg="yellow")
    if found and not add:
        typer.echo("Nothing saved. Run again with --add to keep these.")


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


@app.command("filter-audit")
def filter_audit_cmd() -> None:
    """What each title word in your filters decides, and how its jobs scored (read-only)."""
    from linkit_all.core.search import load_search
    from linkit_all.matching.audit import filter_audit

    db = init_db(get_settings().db_path)
    cfg = load_search(db)
    if cfg is None:
        typer.echo("Set up your search first.", err=True)
        raise typer.Exit(1)
    with db() as s:
        rows = filter_audit(s, cfg)
    if not rows:
        typer.echo("Your filters have no include or exclude title words.")
    for r in rows:
        avg = "-" if r.avg_score is None else f"{r.avg_score:.1f}"
        typer.echo(f"{r.kind:<8} {r.word[:30]:<30} jobs {r.jobs:>6}  average score {avg}")


@app.command("why-missed")
def why_missed_cmd(url: str) -> None:
    """Why a posting you found yourself is not in your list (read-only)."""
    from linkit_all.core.search import load_search
    from linkit_all.matching.audit import why_missed

    db = init_db(get_settings().db_path)
    cfg = load_search(db)
    if cfg is None:
        typer.echo("Set up your search first.", err=True)
        raise typer.Exit(1)
    with db() as s:
        typer.echo(why_missed(s, cfg, url))


@run_app.command("apply")
def run_apply() -> None:
    """Tailor and fill applications: a dry run unless Live applying is on in settings."""
    counts = _run_stage("apply")[1]
    typer.echo(", ".join(f"{k} {v}" for k, v in counts.items()))


@app.command()
def bench(
    jobs: Annotated[int, typer.Option(min=10, help="Fake jobs to generate.")] = 10000,
    seed: Annotated[int, typer.Option(help="Same seed, same jobs.")] = 1,
    out: Annotated[Path, typer.Option(help="Where to write the numbers.")] = Path("bench.json"),
    apply: Annotated[
        int,
        typer.Option(min=0, help="Also fill this many fake application forms (needs a browser)."),
    ] = 0,
) -> None:
    """Measure finding, ranking and the CV tailoring guard on built-in fake data, and with
    --apply the form filling too (practice mode: nothing is submitted). Touches none of your
    data and no real site; the AI is a scripted stand-in."""
    import json
    import tempfile

    from linkit_all.bench.run import run_bench
    from linkit_all.matching.rank import Embedder

    settings = get_settings()
    setup_logging(settings)
    embed = Embedder(settings.embedding_model, settings.data_dir / "models")
    # ignore_cleanup_errors: Windows may still hold the SQLite file when the folder goes
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        result = asyncio.run(run_bench(jobs, seed, embed, Path(tmp), apply))
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    q, t = result["quality"], result["timing"]
    typer.echo(f"{jobs} jobs in {t['total_s']} s ({t['jobs_per_minute']} jobs/minute)")
    for name in ("dedupe", "scam", "ghost"):
        typer.echo(
            f"{name:<7} precision {q[name]['precision']:.0%}  recall {q[name]['recall']:.0%}"
        )
    r = q["rank"]
    typer.echo(
        f"rank    top 10: {r['precision_at_10']:.0%}  top 50: {r['precision_at_50']:.0%} "
        f"relevant ({r['relevant_share']:.0%} by chance), "
        f"all {r['relevant']} relevant on top: {r['precision_at_r']:.0%}"
    )
    tl = result["tailor"]
    typer.echo(
        f"tailor  honest edits accepted {tl['honest_accepted']}, invented edits refused "
        f"{tl['invented_refused']}, layout {'ok' if tl['layout']['ok'] else 'CHANGED'}"
        + ("" if tl["layout"]["checked"] else " (not checked: no LibreOffice)")
    )
    if a := result.get("apply"):
        typer.echo(
            f"apply   {a['right_outcome']}/{a['attempted']} forms ended as they should, "
            f"fields right {a['fields_right']}, trap fields left empty {a['traps_left_empty']}, "
            f"sensitive questions sent to the AI: {len(a['sensitive_sent_to_ai'])}"
        )
    typer.echo(f"Numbers: {out}")


@app.command("apply-probe")
def apply_probe(
    per_source: Annotated[int, typer.Option(help="Jobs to try per source.")] = 1,
    job: Annotated[list[int] | None, typer.Option(help="Exact job ids (repeat).")] = None,
    limit: Annotated[int, typer.Option(help="At most this many jobs in all.")] = 60,
    fresh: Annotated[
        bool, typer.Option("--fresh", help="Only jobs no earlier test has tried.")
    ] = False,
    per_site: Annotated[
        int | None, typer.Option(help="At most this many per apply site (or company board).")
    ] = None,
    restore: Annotated[
        bool, typer.Option("--restore", help="Only put back jobs an earlier test borrowed.")
    ] = False,
    scorecard: Annotated[
        Path | None, typer.Option(help="Also write a per-platform summary to this file.")
    ] = None,
    provider: ProviderOpt = None,
    model: ModelOpt = None,
) -> None:
    """Practice-mode apply of one job per source, then a report of where each one got to.
    Nothing is submitted; the CV is sent as uploaded."""
    from linkit_all.apply import probe as probing
    from linkit_all.apply.probe import give_back_all, pick, probe, report
    from linkit_all.core.search import load_search
    from linkit_all.pipeline import _get_embedder, ai_settings

    db = _stage_db()
    if restore:
        typer.echo(f"Put back {give_back_all(db)} jobs.")
        return
    settings = get_settings()
    cfg = load_search(db)
    if cfg is None:
        typer.echo("No search saved yet: finish setup first.", err=True)
        raise typer.Exit(1)
    ids = pick(db, per_source, job, fresh, per_site)[:limit]
    typer.echo(f"Trying {len(ids)} jobs in Practice mode...")

    async def go() -> list[Any]:
        override = {k: v for k, v in {"provider": provider, "model": model}.items() if v}
        ai = get_provider(ai_settings(settings, cfg, override), cache=db)
        return await probe(db, settings, cfg, ai, await _get_embedder(settings), ids)

    rows = asyncio.run(go())
    if len(rows) < len(ids):
        typer.secho(
            f"Stopped after {len(rows)} of {len(ids)} jobs: the AI is not available right now.",
            fg="yellow",
        )
    for r in rows:
        typer.echo(f"{r.job_id:>6} {r.source:<16} {r.status:<10} {r.code:<20} {r.host}")
    typer.echo(f"Report: {report(rows, settings.data_dir / 'applications')}")
    if scorecard is not None:
        scorecard.write_text(probing.scorecard(rows, datetime.now()), encoding="utf-8")
        typer.echo(f"Scorecard: {scorecard}")
