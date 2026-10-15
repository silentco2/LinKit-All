"""Pipeline stages, shared by the CLI (`linkit run <stage>`) and the UI's run button."""

import asyncio
from dataclasses import asdict
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.config import Settings
from linkit_all.core.models import Run, RunStatus, utcnow
from linkit_all.core.runs import record_stats
from linkit_all.core.search import SearchConfig, load_search

STAGES = ("discover", "enrich", "rank", "score")


class PipelineError(RuntimeError):
    pass


def ai_settings(
    settings: Settings, cfg: SearchConfig, override: dict[str, Any] | None = None
) -> Settings:
    """CLI flags > the wizard's AI choice (saved with the search config) > env defaults."""
    chosen = {k: v for k, v in cfg.ai.model_dump().items() if v}
    try:
        return Settings.model_validate({**settings.model_dump(), **chosen, **(override or {})})
    except ValidationError as e:
        raise PipelineError(f"invalid AI settings: {e}") from e


_embedder: Any = None  # the model takes seconds to load; keep it for the process


async def run_stage(
    stage: str,
    db: sessionmaker[Session],
    settings: Settings,
    run_id: int,
    ai_override: dict[str, Any] | None = None,  # CLI --provider/--model beat the wizard
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
                stats = asdict(await discover(db, cfg, run_id, Http(client), registry()))
            else:
                stats = {"enriched": await enrich(db, Http(client), registry())}
    elif stage == "rank":
        global _embedder
        from linkit_all.matching.rank import Embedder, rank_jobs

        if _embedder is None:
            _embedder = await asyncio.to_thread(
                Embedder, settings.embedding_model, settings.data_dir / "models"
            )
        try:
            stats = await asyncio.to_thread(rank_jobs, db, cfg, _embedder)
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
