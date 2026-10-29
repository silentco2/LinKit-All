"""Why a job sits where it is: a short English sentence plus a stable code the UI translates.

Read-only. Built from what the pipeline already stored (the last `filtered_out` event, `job.data`,
`job.score`); nothing here decides anything. The rule messages come from `rules.rule_violation`
and `rank.py`; `tests/unit/test_ux_api.py` pins one example per code so a reworded message fails.
"""

import re
from datetime import datetime
from typing import Any

from linkit_all.core.models import Job, JobState, utcnow

Reason = tuple[str, str, dict[str, Any]]  # (English text, code, params)
FilterEvent = tuple[str, str | None, dict[str, Any]]  # (message, code, params) of the last drop

# Stage-written codes (rank.py, routes.py): the event already says what happened.
_BY_EVENT_CODE = {
    "scam_suspected": ("scam", "Likely scam (score {score})"),
    "ghost_suspected": ("ghost", "Possibly stale posting (score {score})"),
    "trust_reported": ("reported", "You reported this posting"),
}
# Free-text messages of the hard rules, in the order rule_violation checks them.
_BY_MESSAGE = [
    (r"title has none of the include words", "title_not_included",
     "Title has none of your wanted words"),
    (r"title contains excluded word (['\"])(?P<word>.*)\1$", "title_excluded",
     'Title contains "{word}"'),
    (r"work mode (?P<mode>\S+) is not one you chose", "work_mode",
     "Work mode {mode} is not one you chose"),
    (r"location .* not in your locations", "location", "Location not in your places"),
    (r"seniority (?P<level>\S+) not wanted", "seniority", "Seniority {level} is not one you want"),
    (r"posted more than (?P<limit>\d+) days ago", "too_old", "Posted more than {limit} days ago"),
    (r"salary up to (?P<amount>[\d,]+) (?P<currency>\S+)/month is below", "salary",
     "Salary below your floor"),
    (r"company is blacklisted", "blacklist", "Company on your blacklist"),
    (r"already in your pipeline for this company", "one_per_company",
     "Already in your pipeline for this company"),
    (r"a better match at this company", "one_per_company_better",
     "A better match at this company ranked higher"),
]  # fmt: skip


def filter_reason(job: Job, event: FilterEvent | None, now: datetime | None = None) -> Reason:
    message, code, params = event or ("", None, {})
    if code in _BY_EVENT_CODE:
        name, text = _BY_EVENT_CODE[code]
        shown = {} if name == "reported" else {"score": params.get("score")}
        return text.format(**shown), name, shown
    for pattern, name, text in _BY_MESSAGE:
        if not (m := re.match(pattern, message)):
            continue
        found: dict[str, Any] = dict(m.groupdict())
        for k in ("limit", "amount"):
            if k in found:
                found[k] = int(found[k].replace(",", ""))
        if name == "location":
            found["location"] = job.location
        if name == "too_old" and job.posted_at:
            found["days"] = max(0, ((now or utcnow()) - job.posted_at).days)
            text = "Posted {days} days ago"
        return text.format(**found), name, found
    fallback = (message[:1].upper() + message[1:]) if message else "Filtered out by your rules"
    return fallback, "other", {}


def job_reason(job: Job, filter_event: FilterEvent | None = None) -> Reason | None:
    """None when the job simply is where the pipeline put it (nothing worth explaining)."""
    if job.state == JobState.filtered_out:
        return filter_reason(job, filter_event)
    if job.state == JobState.below_threshold:
        trust = job.data.get("trust") or {}
        if trust.get("ghost_demoted"):
            score = (trust.get("ghost") or {}).get("score")
            return f"Possibly stale posting (score {score})", "ghost", {"score": score}
        if job.score is not None:
            return f"AI score {job.score} of 10", "low_score", {"score": job.score, "out_of": 10}
        return "Outside your top matches", "low_rank", {}
    return None
