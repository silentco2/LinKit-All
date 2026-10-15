"""SQLAlchemy models. `jobs.state` is the single source of truth for the pipeline."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import JSON, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    # ponytail: naive UTC everywhere, SQLite has no timezone type.
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSON,
        list[str]: JSON,
        list[dict[str, Any]]: JSON,
    }


class JobState(StrEnum):
    discovered = "discovered"
    enriched = "enriched"
    filtered_out = "filtered_out"
    ranked = "ranked"
    scored = "scored"
    below_threshold = "below_threshold"
    awaiting_review = "awaiting_review"
    queued_apply = "queued_apply"
    tailored = "tailored"
    applying = "applying"
    needs_user = "needs_user"
    applied = "applied"
    failed = "failed"
    skipped = "skipped"


class Tier(StrEnum):
    high = "high"
    mid = "mid"
    low = "low"


class RunStatus(StrEnum):
    running = "running"
    paused = "paused"
    done = "done"
    failed = "failed"


def _enum(cls: type[StrEnum]) -> Enum:
    # VARCHAR without CHECK constraint, so adding a member needs no migration.
    return Enum(cls, native_enum=False, length=32)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus), default=RunStatus.running)
    pause_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), index=True)
    source: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(Text, unique=True)  # normalized
    title: Mapped[str] = mapped_column(Text)
    company: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    posted_at: Mapped[datetime | None]
    ats: Mapped[str | None] = mapped_column(String(32))
    dedupe_hash: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[JobState] = mapped_column(
        _enum(JobState), default=JobState.discovered, index=True
    )
    tier: Mapped[Tier | None] = mapped_column(_enum(Tier))
    score: Mapped[int | None]
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)  # source extras, AI reasons
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    events: Mapped[list["JobEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobEvent.id"
    )


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(default=utcnow)
    from_state: Mapped[JobState | None] = mapped_column(_enum(JobState))
    to_state: Mapped[JobState] = mapped_column(_enum(JobState))
    message: Mapped[str] = mapped_column(Text, default="")
    artifacts: Mapped[list[str]] = mapped_column(default=list)

    job: Mapped[Job] = relationship(back_populates="events")


class LLMCache(Base):
    __tablename__ = "llm_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of model+prompt
    model: Mapped[str] = mapped_column(String(128))
    response: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Profile(Base):
    """The user's profile. Single row (id=1) for now."""

    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list[str]] = mapped_column(default=list)  # the only skills tailoring may add
    cv_path: Mapped[str] = mapped_column(Text)  # base DOCX copied into the data dir
    answers: Mapped[dict[str, Any]] = mapped_column(
        default=dict
    )  # apply.answers.ApplicationAnswers
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class LockedFact(Base):
    """Exact text tailoring must never change (employers, titles, dates, degrees...)."""

    __tablename__ = "locked_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text, unique=True)


class TailoredCV(Base):
    __tablename__ = "tailored_cvs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    docx_path: Mapped[str] = mapped_column(Text)
    pdf_path: Mapped[str] = mapped_column(Text)
    applied: Mapped[list[dict[str, Any]]] = mapped_column(default=list)  # patches, for red-line UI
    rejected: Mapped[list[dict[str, Any]]] = mapped_column(default=list)  # patch + reason
    verify: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SearchConfigRow(Base):
    """The imported search.toml (validated by core.search.SearchConfig). Single row."""

    __tablename__ = "search_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class SourceCheckpoint(Base):
    """Discovery progress per run and task, saved with every page so runs resume."""

    __tablename__ = "source_checkpoints"
    __table_args__ = (UniqueConstraint("run_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(Text)  # e.g. "greenhouse:stripe"
    next_page: Mapped[int] = mapped_column(default=0)
    done: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str | None] = mapped_column(Text)


class AnswerEntry(Base):
    """Answer bank: questions answered before, reused when a new form asks the same thing."""

    __tablename__ = "answer_bank"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[Any] = mapped_column(JSON)  # str, list[str] or bool
    source: Mapped[str] = mapped_column(String(8))  # "user" or "ai"
    sensitive: Mapped[bool] = mapped_column(default=False)
    uses: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ActionKind(StrEnum):
    unknown_question = "unknown_question"
    confirm_submit = "confirm_submit"
    captcha = "captcha"
    validation_error = "validation_error"
    login_issue = "login_issue"
    two_factor = "two_factor"


class ActionStatus(StrEnum):
    open = "open"
    resolved = "resolved"
    dismissed = "dismissed"


class ActionItem(Base):
    """Action Center: a parked job waiting for the user (CLAUDE.md §5.7)."""

    __tablename__ = "action_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[ActionKind] = mapped_column(_enum(ActionKind))
    status: Mapped[ActionStatus] = mapped_column(
        _enum(ActionStatus), default=ActionStatus.open, index=True
    )
    message: Mapped[str] = mapped_column(Text, default="")
    questions: Mapped[list[dict[str, Any]]] = mapped_column(default=list)  # asked of the user
    answers: Mapped[dict[str, Any]] = mapped_column(
        default=dict
    )  # the user's replies, or filled values
    artifacts: Mapped[list[str]] = mapped_column(default=list)  # screenshots
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    resolved_at: Mapped[datetime | None]
