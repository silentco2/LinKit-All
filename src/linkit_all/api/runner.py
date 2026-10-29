"""Runs pipeline stages in the server's event loop, one run at a time."""

import asyncio
from dataclasses import asdict, dataclass, field
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.api.events import EventBus
from linkit_all.apply.vault import Vault
from linkit_all.core.config import Settings
from linkit_all.core.models import utcnow
from linkit_all.core.runs import cancel_run, current_run
from linkit_all.pipeline import STAGES, PipelineError, finish_run, run_stage


class RunBusy(RuntimeError):
    pass


@dataclass
class RunState:
    running: bool = False
    stopping: bool = False  # cancel asked; the worker is finishing its current step
    run_id: int | None = None
    stages: list[str] = field(default_factory=list)
    stage: str | None = None
    started_at: str | None = None
    error: str | None = None
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

    def start(self, stages: list[str], new: bool = False) -> RunState:
        if self.state.running:
            raise RunBusy("a run is already in progress")
        unknown = set(stages) - set(STAGES)
        if unknown or not stages:
            raise ValueError(f"stages must be some of {', '.join(STAGES)}")
        ordered = [s for s in STAGES if s in stages]  # always pipeline order
        run_id = current_run(self.db, new)
        self.state = RunState(running=True, run_id=run_id, stages=ordered,
                              started_at=utcnow().isoformat(timespec="seconds") + "Z")  # fmt: skip
        self.bus.publish({"type": "run", "status": "started", **self.state.as_dict()})
        self._task = asyncio.create_task(self._run(run_id, ordered))
        return self.state

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
                except PipelineError as e:
                    self.state.error, status = str(e), "failed"
                    self.bus.publish(
                        {"type": "stage", "stage": stage, "status": "failed", "error": str(e)}
                    )
                    break
                self.state.results[stage] = result
                self.bus.publish(
                    {"type": "stage", "stage": stage, "status": "done", "result": result}
                )
            else:
                finish_run(self.db, run_id)
        except asyncio.CancelledError:
            status = "cancelled"
            cancel_run(self.db, run_id)
        except Exception as e:  # keep the server alive; show what broke
            logger.exception("run {} crashed", run_id)
            self.state.error, status = f"{type(e).__name__}: {e}", "failed"
        finally:
            self.state.running, self.state.stopping, self.state.stage = False, False, None
            self.bus.last_shot = None  # the browser is gone: new viewers get no stale frame
            self.bus.publish({"type": "run", "status": status, **self.state.as_dict()})
