"""Runs pipeline stages in the server's event loop, one run at a time."""

import asyncio
from dataclasses import asdict, dataclass, field
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.api.events import EventBus
from linkit_all.apply.runner import NEEDS_TOOL
from linkit_all.apply.vault import Vault
from linkit_all.core import fx
from linkit_all.core.config import Settings
from linkit_all.core.models import Profile, utcnow
from linkit_all.core.runs import add_stage, cancel_run, current_run, note_failure, pause_of
from linkit_all.core.search import load_search
from linkit_all.pipeline import STAGES, PipelineError, PipelinePause, finish_run, run_stage
from linkit_all.tailor.pipeline import cv_plan


class RunBusy(RuntimeError):
    pass


class RunBlocked(RuntimeError):
    """The run cannot start as set up. `code` is stable (the UI translates it)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class RunState:
    running: bool = False
    stopping: bool = False  # cancel asked; the worker is finishing its current step
    run_id: int | None = None
    stages: list[str] = field(default_factory=list)
    stage: str | None = None
    started_at: str | None = None
    error: str | None = None  # English; with reason_code the UI shows its own translation
    reason_code: str | None = None  # ai_usage_limit | needs_libreoffice | pipeline_error ...
    reason_params: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PipelineRunner:
    def __init__(
        self,
        db: sessionmaker[Session],
        settings: Settings,
        bus: EventBus,
        vault: Vault | None = None,
    ) -> None:
        self.db, self.settings, self.bus, self.vault = db, settings, bus, vault
        self.state = RunState()
        self._task: asyncio.Task[None] | None = None
        self._fx_task: asyncio.Task[bool] | None = None  # kept so it is not collected mid-flight

    def start(self, stages: list[str], new: bool = False) -> RunState:
        if self.state.running:
            raise RunBusy("a run is already in progress")
        unknown = set(stages) - set(STAGES)
        if unknown or not stages:
            raise ValueError(f"stages must be some of {', '.join(STAGES)}")
        ordered = [s for s in STAGES if s in stages]  # always pipeline order
        if "apply" in ordered:
            self._preflight()
        run_id = current_run(self.db, new)
        for stage in ordered:  # known up front, so the run is titled by what it does
            add_stage(self.db, run_id, stage)
        self.state = RunState(running=True, run_id=run_id, stages=ordered,
                              started_at=utcnow().isoformat(timespec="seconds") + "Z")  # fmt: skip
        self.bus.publish({"type": "run", "status": "started", **self.state.as_dict()})
        self._task = asyncio.create_task(self._run(run_id, ordered))
        # Fresh exchange rates for the salary rule: never blocks or fails the run, no personal data.
        self._fx_task = asyncio.create_task(fx.refresh(self.settings.data_dir))
        return self.state

    def _preflight(self) -> None:
        """Real applications that cannot be made right (CV tool missing) say so now, not later."""
        cfg = load_search(self.db)
        with self.db() as s:
            profile = s.get(Profile, 1)
        if cfg is None or profile is None:
            return  # the stage itself explains what is missing
        plan = cv_plan(profile.cv_source_format, cfg.apply.tailor_cv, cfg.apply.live)
        if plan.mode == "blocked":
            raise RunBlocked(plan.reason, NEEDS_TOOL[plan.reason])

    def cancel(self) -> bool:
        if self._task is None or self._task.done():
            return False
        self._task.cancel()  # the run stays resumable: checkpoints and job states are saved
        if not self.state.stopping:
            self.state.stopping = True
            self.bus.publish({"type": "run", "status": "stopping", **self.state.as_dict()})
        return True

    async def _run(self, run_id: int, stages: list[str]) -> None:
        status = "finished"
        try:
            for stage in stages:
                self.state.stage = stage
                self.bus.publish({"type": "stage", "stage": stage, "status": "started"})
                try:
                    result = await run_stage(
                        stage, self.db, self.settings, run_id, None, self.vault, self.bus.publish
                    )
                except PipelinePause as e:  # not a failure: the run waits, resuming continues it
                    self._reason(e, e.code, e.params)
                    status = "paused"
                    self._stage_stopped(stage, "paused", e)
                    break
                except PipelineError as e:
                    self._reason(e, e.code, e.params)
                    status = "failed"
                    self._stage_stopped(stage, "failed", e)
                    break
                self.state.results[stage] = result
                self.bus.publish(
                    {"type": "stage", "stage": stage, "status": "done", "result": result}
                )
                if paused := pause_of(self.db, run_id):  # a stage stopped itself (score)
                    message, code, params = paused
                    self._reason(message, code, params)
                    status = "paused"
                    break
            else:
                finish_run(self.db, run_id)
        except asyncio.CancelledError:
            status = "cancelled"
            cancel_run(self.db, run_id)
        except Exception as e:  # keep the server alive; show what broke
            logger.exception("run {} crashed", run_id)
            detail = f"{type(e).__name__}: {e}"
            self._reason(detail, "pipeline_error", {"detail": detail[:200]})
            note_failure(self.db, run_id, detail, "pipeline_error", {"detail": detail[:200]})
            status = "failed"
        finally:
            self.state.running, self.state.stopping, self.state.stage = False, False, None
            self.bus.last_shot = None  # the browser is gone: new viewers get no stale frame
            self.bus.publish({"type": "run", "status": status, **self.state.as_dict()})

    def _stage_stopped(self, stage: str, status: str, e: PipelineError) -> None:
        self.bus.publish({"type": "stage", "stage": stage, "status": status, "error": str(e),
                          "code": e.code, "params": e.params})  # fmt: skip

    def _reason(self, message: object, code: str, params: dict[str, Any]) -> None:
        self.state.error, self.state.reason_code, self.state.reason_params = (
            str(message), code, params,
        )  # fmt: skip
