"""Read-only tuning tools. `filter_audit`: what each title word in your filters decided and how
the jobs it let through scored. `why_missed`: why a posting you found yourself is not in your
list, and the one change that would have caught it. Nothing here writes.
Logic adapted from career-ops (MIT)."""

from dataclasses import dataclass, field
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from linkit_all.core.models import Job, JobEvent, JobState
from linkit_all.core.search import SearchConfig
from linkit_all.matching.reasons import job_reason
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.text import normalize_url


@dataclass
class WordStats:
    word: str
    kind: str  # include | exclude
    jobs: int = 0  # titles containing the word
    scored: list[int] = field(default_factory=list)  # AI scores of those jobs

    @property
    def avg_score(self) -> float | None:
        return round(mean(self.scored), 1) if self.scored else None


def filter_audit(s: Session, cfg: SearchConfig) -> list[WordStats]:
    """Per include/exclude title word: how many found jobs have it, their average AI score.
    An include word whose jobs score low is noise; an exclude word that hits nothing is dead."""
    f = cfg.filters
    stats = [WordStats(w, "include") for w in f.title_include]
    stats += [WordStats(w, "exclude") for w in f.title_exclude]
    for title, score in s.execute(select(Job.title, Job.score)):
        low = title.lower()
        for st in stats:
            if st.word.lower() in low:
                st.jobs += 1
                if score is not None:
                    st.scored.append(score)
    return stats


def why_missed(s: Session, cfg: SearchConfig, url: str) -> str:
    """One plain sentence: why this posting is not in your list, and what would catch it."""
    key = normalize_url(url)
    job = s.scalar(select(Job).where(Job.url == key))
    if job is not None:
        if job.state == JobState.filtered_out:
            event = s.scalar(
                select(JobEvent)
                .where(JobEvent.job_id == job.id, JobEvent.to_state == JobState.filtered_out)
                .order_by(JobEvent.id.desc())
            )
            reason = job_reason(job, (event.message, event.code, event.params) if event else None)
            why = reason[0] if reason else "a filter"
            return f"Found, then left out: {why}. Change that filter to keep jobs like it."
        return f"Found already: it is in your jobs as {job.state.replace('_', ' ')}."
    found = detect(url)
    if found is None:
        return (
            "No source reads this site. Add its careers page under Settings > Sources > "
            "Companies, or the board it is listed on."
        )
    ats, slug = found
    entry = f"{ats}:{slug}"
    if not any(c == entry or slug in c for c in cfg.sources.companies):
        return f"This is a {ats} board ({slug}) that is not in your companies. Add {entry!r}."
    return (
        f"The {ats} board {slug!r} is in your companies but this posting was not seen: it may "
        "be newer than your last search, or outside your search words and places."
    )
