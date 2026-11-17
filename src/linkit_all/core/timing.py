"""Where an application's time goes, step by step, to find what to speed up.

`Applier.apply` starts a `Timings` for each job; code inside wraps its steps in `step("...")`.
A step's own time excludes the steps inside it, so the totals add up and nothing is counted
twice. `note()` says why the running step took long (a retry, a page that never went idle, a
fresh AI call); steps of `SLOW_S` or more are kept with their note. Outside an application
every call is a no-op.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

SLOW_S = 2.0  # a step this long is listed with its note
MAX_SLOW = 12  # per job


@dataclass
class _Open:
    name: str
    start: float
    inner: float = 0.0  # time spent in steps inside this one
    note: str = ""


@dataclass
class Timings:
    started: float = field(default_factory=time.perf_counter)
    steps: dict[str, list[float]] = field(default_factory=dict)  # name -> [seconds, times]
    slow: list[dict[str, Any]] = field(default_factory=list)
    _stack: list[_Open] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """{"total": s, "steps": {name: [s, n]}, "slow": [{step, s, note}]}; the time no step
        covered is "other" (our own code, the database, pacing pauses outside a step)."""
        total = time.perf_counter() - self.started
        steps = {k: [round(s, 2), int(n)] for k, (s, n) in self.steps.items()}
        covered = sum(s for s, _ in self.steps.values())
        if total - covered >= 0.05:
            steps["other"] = [round(total - covered, 2), 1]
        slow = sorted(self.slow, key=lambda x: -x["s"])[:MAX_SLOW]
        return {"total": round(total, 2), "steps": steps, "slow": slow}


_CURRENT: ContextVar[Timings | None] = ContextVar("linkit_timings", default=None)


def start() -> Timings:
    t = Timings()
    _CURRENT.set(t)
    return t


def stop() -> None:
    _CURRENT.set(None)


@contextmanager
def step(name: str) -> Iterator[None]:
    t = _CURRENT.get()
    if t is None:
        yield
        return
    o = _Open(name, time.perf_counter())
    t._stack.append(o)
    try:
        yield
    finally:
        t._stack.pop()
        took = time.perf_counter() - o.start
        own = max(took - o.inner, 0.0)
        if t._stack:
            t._stack[-1].inner += took
        s = t.steps.setdefault(name, [0.0, 0])
        s[0] += own
        s[1] += 1
        if own >= SLOW_S:
            t.slow.append({"step": name, "s": round(own, 1), "note": o.note})


def note(text: str) -> None:
    """Why the running step is slow (kept with it when it is)."""
    t = _CURRENT.get()
    if t is not None and t._stack:
        o = t._stack[-1]
        o.note = f"{o.note}; {text}" if o.note else text
