"""Job state machine. Every transition writes a `job_events` row (CLAUDE.md §4)."""

from collections.abc import Iterable

from sqlalchemy.orm import Session

from linkit_all.core.models import Job, JobEvent, JobState

S = JobState

ALLOWED: dict[JobState, frozenset[JobState]] = {
    S.discovered: frozenset({S.enriched, S.filtered_out}),
    S.enriched: frozenset({S.filtered_out, S.ranked}),
    S.ranked: frozenset({S.scored, S.below_threshold}),  # local rank may drop to low
    S.scored: frozenset({S.below_threshold, S.awaiting_review, S.queued_apply}),
    S.below_threshold: frozenset({S.queued_apply}),  # user opted in to apply low tier
    S.awaiting_review: frozenset({S.queued_apply}),
    S.queued_apply: frozenset({S.tailored, S.failed}),
    S.tailored: frozenset({S.applying, S.failed}),
    S.applying: frozenset({S.needs_user, S.applied, S.failed}),
    S.needs_user: frozenset({S.queued_apply, S.applying, S.failed}),  # resolved in Action Center
    S.failed: frozenset({S.queued_apply}),  # retry
    S.filtered_out: frozenset({S.enriched}),  # filters changed: checked again
    S.applied: frozenset(),
    S.skipped: frozenset(),
}
TERMINAL = frozenset({S.filtered_out, S.applied, S.skipped})


class InvalidTransition(ValueError):
    pass


def can_transition(src: JobState, dst: JobState) -> bool:
    # The user may skip any job that is not finished yet.
    return dst in ALLOWED[src] or (dst == S.skipped and src not in TERMINAL)


def transition(
    session: Session,
    job: Job,
    to: JobState,
    message: str = "",
    artifacts: Iterable[str] = (),
) -> bool:
    """Move `job` to `to` and log the event. Same state is a no-op (stages are idempotent).

    Returns True if the state changed. The caller commits.
    """
    if job.state == to:
        return False
    if not can_transition(job.state, to):
        raise InvalidTransition(f"job {job.id}: {job.state} -> {to}")
    session.add(
        JobEvent(
            job=job, from_state=job.state, to_state=to, message=message, artifacts=list(artifacts)
        )
    )
    job.state = to
    return True
