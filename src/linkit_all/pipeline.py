"""Pipeline stages, shared by the CLI (`linkit run <stage>`) and the UI's run button."""

import asyncio
from collections.abc import Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.config import Settings
from linkit_all.core.models import Run, RunStatus, utcnow
from linkit_all.core.runs import add_stage, note_failure, pause_run, record_stats
from linkit_all.core.search import SearchConfig, load_search
from linkit_all.providers.base import UsageLimitError

if TYPE_CHECKING:
    from linkit_all.apply.vault import Vault

STAGES = ("discover", "enrich", "rank", "score", "apply")


class PipelineError(RuntimeError):
    """A stage failed. `code`/`params` let the UI show the reason in the user's language."""

    def __init__(
        self, message: str, code: str | None = None, params: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code or "pipeline_error"
        self.params: dict[str, Any] = (params or {}) if code else {"detail": message[:200]}


class PipelinePause(PipelineError):
    """A stage stopped cleanly (AI usage limit, LibreOffice missing): not a failure. Jobs keep
    their state and resuming the run continues."""


def ai_settings(
    settings: Settings, cfg: SearchConfig, override: dict[str, Any] | None = None
) -> Settings:
    """CLI flags > the wizard's AI choice (saved with the search config) > env defaults."""
    chosen = {k: v for k, v in cfg.ai.model_dump().items() if v}
    if chosen.get("provider") != "litellm":
        chosen.pop("api_base", None)  # only the API/local adapter talks to a server
    try:
        return Settings.model_validate({**settings.model_dump(), **chosen, **(override or {})})
    except ValidationError as e:
        raise PipelineError(f"invalid AI settings: {e}") from e


def api_key_getter(
    db: sessionmaker[Session], settings: Settings, vault: "Vault | None" = None
) -> Callable[[str], dict[str, str] | None]:
    """`keys(provider)` for source plugins: the server's vault, else this data dir's vault opened
    with the keyring. None while the vault is locked or the provider has no saved keys."""
    from linkit_all.apply.vault import vault_for
    from linkit_all.core.api_keys import get_keys

    def keys(name: str) -> dict[str, str] | None:
        v = vault if vault is not None else vault_for(settings, db)
        if not v.unlocked() and v.initialized():
            v.unlock_from_keyring()
        return get_keys(v, name)

    return keys


_embedder: Any = None  # the model takes seconds to load; keep it for the process


async def _get_embedder(settings: Settings) -> Any:
    global _embedder
    if _embedder is None:
        from linkit_all.matching.rank import Embedder

        _embedder = await asyncio.to_thread(
            Embedder, settings.embedding_model, settings.data_dir / "models"
        )
    return _embedder


async def check_sources(
    db: sessionmaker[Session],
    settings: Settings,
    keys: list[str] | None = None,
    force: bool = False,
    vault: "Vault | None" = None,
) -> dict[str, Any]:
    """Live one-page probes of the switched-on sources and company pages (or `keys`), built
    exactly as discovery builds them; returns `health.summary` of what was checked."""
    from linkit_all.providers import get_provider
    from linkit_all.sources import health, registry
    from linkit_all.sources.http import Http, make_client

    cfg = load_search(db) or SearchConfig()
    provider = get_provider(ai_settings(settings, cfg), cache=db)
    sources = registry(provider, settings.data_dir, api_key_getter(db, settings, vault))
    wanted = (
        health.wanted(cfg, sources)
        if keys is None
        else [
            k if k in sources or k.startswith(health.COMPANY) else health.COMPANY + k for k in keys
        ]
    )  # anything but a source name is a company entry (a link or "greenhouse:stripe")
    try:
        async with make_client() as client:
            await health.check(db, Http(client, attempts=1), sources, cfg, wanted, force)
    finally:
        await asyncio.gather(*(src.aclose() for src in sources.values()))
    return health.summary(db, wanted)


async def run_stage(
    stage: str,
    db: sessionmaker[Session],
    settings: Settings,
    run_id: int,
    ai_override: dict[str, Any] | None = None,  # CLI --provider/--model beat the wizard
    vault: "Vault | None" = None,  # the server's unlocked vault; the CLI leaves it to the keyring
    publish: Callable[[dict[str, Any]], None] | None = None,  # live events (server only)
) -> dict[str, Any]:
    """One stage. A usage limit (anywhere) or an `ApplyBlocked` with a code pauses the run;
    any other `PipelineError` is noted on the run and re-raised."""
    if stage in STAGES:
        add_stage(db, run_id, stage)
    try:
        stats = await _run_stage(stage, db, settings, run_id, ai_override, vault, publish)
    except UsageLimitError as e:
        pause = PipelinePause(e.message, e.code, {"provider": e.provider, "until": e.until})
    except PipelinePause as e:
        pause = e
    except PipelineError as e:
        note_failure(db, run_id, str(e), e.code, e.params)
        raise
    else:
        record_stats(db, run_id, stage, stats)
        return stats
    pause_run(db, run_id, str(pause), pause.code, pause.params)
    raise pause


async def _run_stage(
    stage: str,
    db: sessionmaker[Session],
    settings: Settings,
    run_id: int,
    ai_override: dict[str, Any] | None = None,  # CLI --provider/--model beat the wizard
    vault: "Vault | None" = None,  # the server's unlocked vault; the CLI leaves it to the keyring
    publish: Callable[[dict[str, Any]], None] | None = None,  # live events (server only)
) -> dict[str, Any]:
    cfg = load_search(db)
    if cfg is None:
        raise PipelineError("Set up your search first (setup wizard or `linkit search import`)")
    if stage in ("discover", "enrich"):
        from linkit_all.sources import registry
        from linkit_all.sources.http import Http, make_client
        from linkit_all.sources.runner import discover, enrich

        keys = api_key_getter(db, settings, vault)
        async with make_client() as client:
            if stage == "discover":
                from linkit_all.providers import get_provider

                # Only the careers source uses the model: once per JS-rendered site, to pick
                # how to read it (browser_extract). Everything else in discovery is script.
                provider = get_provider(ai_settings(settings, cfg, ai_override), cache=db)
                sources = registry(provider, settings.data_dir, keys)
                stats = asdict(await discover(db, cfg, run_id, Http(client), sources))
            else:
                stats = {"enriched": await enrich(db, Http(client), registry(keys=keys))}
    elif stage == "rank":
        from linkit_all.matching.rank import rank_jobs

        embedder = await _get_embedder(settings)
        try:
            stats = await asyncio.to_thread(rank_jobs, db, cfg, embedder, settings.data_dir)
        except ValueError as e:
            raise PipelineError(str(e)) from e
    elif stage == "score":
        from linkit_all.matching.score import score_jobs
        from linkit_all.providers import ProviderError, get_provider

        try:
            provider = get_provider(ai_settings(settings, cfg, ai_override), cache=db)
            stats = await score_jobs(db, cfg, provider, run_id)
        except UsageLimitError:
            raise
        except (ValueError, ProviderError) as e:
            raise PipelineError(str(e)) from e
    elif stage == "apply":
        from linkit_all.apply.runner import ApplyBlocked, apply_jobs
        from linkit_all.providers import ProviderError, get_provider

        try:
            provider = get_provider(ai_settings(settings, cfg, ai_override), cache=db)
            stats = await apply_jobs(
                db, settings, cfg, provider, await _get_embedder(settings), vault, publish
            )
            await _after_apply(db, settings, cfg, vault, provider)
        except ApplyBlocked as e:  # with a code: nothing wrong, the run waits (see ApplyBlocked)
            raise (PipelinePause if e.code else PipelineError)(str(e), e.code, e.params) from e
        except UsageLimitError:
            raise
        except ProviderError as e:
            raise PipelineError(str(e)) from e
    else:
        raise PipelineError(f"unknown stage {stage!r}; stages: {', '.join(STAGES)}")
    return stats


async def _after_apply(
    db: sessionmaker[Session],
    settings: Settings,
    cfg: SearchConfig,
    vault: "Vault | None",
    provider: Any,
) -> None:
    """Mail work after applying: employer replies -> outcomes (opt-in), then one follow-up for
    email applications left without a reply. Never fails the stage."""
    from linkit_all.apply.followup import send_followups
    from linkit_all.apply.replies import read_replies
    from linkit_all.apply.runner import emails_sent_today
    from linkit_all.apply.vault import vault_for
    from linkit_all.core.models import Profile

    if vault is None:
        vault = vault_for(settings, db)
        if not vault.unlocked() and vault.initialized():
            vault.unlock_from_keyring()
    with db() as s:
        profile = s.get(Profile, 1)
        email = profile.email if profile else ""
    await read_replies(db, cfg.email, vault, email)  # logs its counts; outcomes show on jobs
    with db() as s:
        sent_today = emails_sent_today(s)
    try:
        counts = await send_followups(db, settings, cfg, provider, vault, sent_today)
    except Exception as e:
        logger.warning("follow-ups skipped ({})", type(e).__name__)
        return
    logger.info("follow-ups: {} sent, {} previewed, {} due", counts["sent"], counts["previewed"],
                counts["due"])  # fmt: skip


def finish_run(db: sessionmaker[Session], run_id: int) -> None:
    """Mark a run done unless a stage paused it (e.g. AI usage limit)."""
    with db.begin() as s:
        run = s.get_one(Run, run_id)
        if run.status == RunStatus.running:
            run.status, run.finished_at = RunStatus.done, utcnow()
