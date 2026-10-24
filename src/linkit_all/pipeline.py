"""Pipeline stages, shared by the CLI (`linkit run <stage>`) and the UI's run button."""

import asyncio
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.config import Settings
from linkit_all.core.models import Run, RunStatus, utcnow
from linkit_all.core.runs import record_stats
from linkit_all.core.search import SearchConfig, load_search

if TYPE_CHECKING:
    from linkit_all.apply.vault import Vault

STAGES = ("discover", "enrich", "rank", "score", "apply")


class PipelineError(RuntimeError):
    pass


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


_embedder: Any = None  # the model takes seconds to load; keep it for the process


async def _get_embedder(settings: Settings) -> Any:
    global _embedder
    if _embedder is None:
        from linkit_all.matching.rank import Embedder

        _embedder = await asyncio.to_thread(
            Embedder, settings.embedding_model, settings.data_dir / "models"
        )
    return _embedder


async def run_stage(
    stage: str,
    db: sessionmaker[Session],
    settings: Settings,
    run_id: int,
    ai_override: dict[str, Any] | None = None,  # CLI --provider/--model beat the wizard
    vault: "Vault | None" = None,  # the server's unlocked vault; the CLI leaves it to the keyring
) -> dict[str, Any]:
    cfg = load_search(db)
    if cfg is None:
        raise PipelineError("Set up your search first (setup wizard or `linkit search import`)")
    if stage in ("discover", "enrich"):
        from linkit_all.sources import registry
        from linkit_all.sources.http import Http, make_client
        from linkit_all.sources.runner import discover, enrich

        async with make_client() as client:
            if stage == "discover":
                from linkit_all.providers import get_provider

                # Only the generic careers-page source uses the model, for pages without
                # JSON-LD; it falls back to the page title when the provider is unusable.
                provider = get_provider(ai_settings(settings, cfg, ai_override), cache=db)
                stats = asdict(
                    await discover(
                        db, cfg, run_id, Http(client), registry(provider, settings.data_dir)
                    )
                )
            else:
                stats = {"enriched": await enrich(db, Http(client), registry())}
    elif stage == "rank":
        from linkit_all.matching.rank import rank_jobs

        embedder = await _get_embedder(settings)
        try:
            stats = await asyncio.to_thread(rank_jobs, db, cfg, embedder)
        except ValueError as e:
            raise PipelineError(str(e)) from e
    elif stage == "score":
        from linkit_all.matching.score import score_jobs
        from linkit_all.providers import ProviderError, get_provider

        try:
            provider = get_provider(ai_settings(settings, cfg, ai_override), cache=db)
            stats = await score_jobs(db, cfg, provider, run_id)
        except (ValueError, ProviderError) as e:
            raise PipelineError(str(e)) from e
    elif stage == "apply":
        from linkit_all.apply.runner import ApplyBlocked, apply_jobs
        from linkit_all.providers import ProviderError, get_provider

        try:
            provider = get_provider(ai_settings(settings, cfg, ai_override), cache=db)
            stats = await apply_jobs(
                db, settings, cfg, provider, await _get_embedder(settings), vault
            )
        except (ApplyBlocked, ProviderError) as e:
            raise PipelineError(str(e)) from e
    else:
        raise PipelineError(f"unknown stage {stage!r}; stages: {', '.join(STAGES)}")
    record_stats(db, run_id, stage, stats)
    return stats


def finish_run(db: sessionmaker[Session], run_id: int) -> None:
    """Mark a run done unless a stage paused it (e.g. AI usage limit)."""
    with db.begin() as s:
        run = s.get_one(Run, run_id)
        if run.status == RunStatus.running:
            run.status, run.finished_at = RunStatus.done, utcnow()
