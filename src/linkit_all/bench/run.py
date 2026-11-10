"""Run the real stages against the fake board and score the result.

Finding and ranking read the board in-process (httpx ASGI transport, no port). Applying needs a
browser, so for that part the same board is also served on a local port.
ponytail: CV tailoring is not benchmarked (it needs LibreOffice and a model's patches); the
applications here send the CV as uploaded.
"""

import contextlib
import re
import socket
import threading
import time
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import docx
import httpx
import uvicorn
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.apply.answers import ApplicationAnswers
from linkit_all.apply.runner import apply_jobs
from linkit_all.bench.ai import ScriptedAI
from linkit_all.bench.board import HOST, FakeBoard, form_kind, make_app
from linkit_all.bench.data import CV_LINES, CV_QUERIES, CV_SKILLS, FakeJob, generate
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import ActionItem, Job, JobState, Profile
from linkit_all.core.profile import ProfileIn, import_profile
from linkit_all.core.runs import current_run
from linkit_all.core.search import SearchConfig, TrustSection
from linkit_all.matching.rank import Embed, rank_jobs
from linkit_all.matching.score import score_jobs
from linkit_all.matching.trust_stage import score_jobs_trust
from linkit_all.sources.base import Source
from linkit_all.sources.http import Http
from linkit_all.sources.runner import discover, enrich


def _pr(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    """Precision and recall; 1.0 when there was nothing to find or nothing was flagged."""
    return {
        "precision": round(tp / (tp + fp), 4) if tp + fp else 1.0,
        "recall": round(tp / (tp + fn), 4) if tp + fn else 1.0,
        "found": tp,
        "wrong": fp,
        "missed": fn,
    }


def _top(titles: list[str], n: int = 8) -> dict[str, int]:
    """The most common titles: enough to see which kind of case went wrong."""
    return dict(Counter(titles).most_common(n))


def quality(
    jobs: list[FakeJob],
    stored: dict[int, Job],
    scores: dict[int, tuple[int, int]],  # fake uid -> (scam score, ghost score)
    limits: TrustSection,
) -> dict[str, Any]:
    """Compare what the pipeline did (`stored`: fake uid -> Job row) with the ground truth."""
    by_uid = {j.uid: j for j in jobs}
    dropped = [j for j in jobs if j.uid not in stored]
    kept_dups = [j for j in jobs if j.duplicate_of is not None and j.uid in stored]
    dedupe: dict[str, Any] = _pr(
        sum(j.duplicate_of is not None for j in dropped),
        sum(j.duplicate_of is None for j in dropped),
        len(kept_dups),
    )
    dedupe["missed_examples"] = [f"{j.title} | {j.location}" for j in kept_dups[:8]]
    dedupe["wrong_examples"] = [
        f"{j.title} | {j.location}" for j in dropped if j.duplicate_of is None
    ][:8]

    def trust(family: str, flagged: set[int]) -> dict[str, Any]:
        truth = {j.uid for j in jobs if j.family == family and j.uid in stored}
        out: dict[str, Any] = _pr(len(truth & flagged), len(flagged - truth), len(truth - flagged))
        out["missed_titles"] = _top([by_uid[u].title for u in sorted(truth - flagged)])
        out["wrong_titles"] = _top([by_uid[u].title for u in sorted(flagged - truth)])
        return out

    # Scored here for every stored job, not read back from the run: a scam with an unrelated
    # title is hidden as off-title before the trust check ever sees it, and that is fine, but
    # it would leave the trust rules unmeasured.
    scam = {u for u, (sc, _) in scores.items() if sc >= limits.scam_threshold}
    ghost = {u for u, (_, gh) in scores.items() if gh >= limits.ghost_threshold}
    ranked = [
        u
        for u, j in sorted(
            ((u, j) for u, j in stored.items() if j.state == JobState.ranked),
            key=lambda t: (-t[1].data["rank"], t[0]),
        )
    ]
    hits = [by_uid[u].relevant for u in ranked]
    off_title = [u for u, j in stored.items() if j.data.get("trash") == "off_title"]
    r = sum(hits)  # with a perfect ranking, the top `r` are exactly the relevant jobs

    def at(k: int) -> float:
        return round(sum(hits[:k]) / min(k, len(hits)), 4) if hits and k else 0.0

    return {
        "dedupe": dedupe,
        "scam": trust("scam", scam),
        "ghost": trust("ghost", ghost),
        "rank": {
            "ranked": len(hits),
            "relevant": r,
            "relevant_share": round(r / len(hits), 4) if hits else 0.0,  # the baseline
            "precision_at_10": at(10),
            "precision_at_50": at(50),
            "precision_at_r": at(r),
            # what sits in the top r that should not, and what was pushed out of it
            "intruders": dict(
                Counter(by_uid[u].family for u in ranked[:r] if not by_uid[u].relevant)
            ),
            "pushed_out": dict(Counter(by_uid[u].family for u in ranked[r:] if by_uid[u].relevant)),
            # hidden for good as "not a job you are looking for": a lost match is the costly error
            # scams and ghosts that still reached the ranked list, by any route
            "bad_ranked": sum(by_uid[u].family in ("scam", "ghost") for u in ranked),
            "relevant_hidden": sum(by_uid[u].relevant for u in off_title),
            "others_hidden": sum(not by_uid[u].relevant for u in off_title),
        },
    }


PHONE = "+20 100 000 0000"
DIGITS = re.sub(r"\D", "", PHONE)
SENSITIVE = re.compile(r"salary|gender|sponsor|authori[sz]ed|disab|veteran|race|ethnic", re.I)


@contextlib.contextmanager
def serve(app: FastAPI) -> Iterator[str]:
    """The board on a free local port, for the browser. Yields its base URL."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _field(filled: dict[str, Any], label: str) -> Any:
    """The value the form filler recorded for the field whose label starts with `label`."""
    return next((v.get("value") for k, v in filled.items() if k.startswith(label)), None)


async def _apply(
    db: sessionmaker[Session],
    cfg: SearchConfig,
    run_id: int,
    embed: Embed,
    app: FastAPI,
    work: Path,
    n: int,
) -> dict[str, Any]:
    """Score the best `n` ranked jobs, then fill their forms in practice mode (nothing is ever
    submitted) and compare what was typed with what should have been."""
    ai = ScriptedAI()
    cfg = cfg.model_copy(deep=True)
    cfg.matching.ai_max_jobs = n
    cfg.apply.max_per_run, cfg.apply.headless, cfg.apply.tailor_cv = n, True, False
    with db.begin() as s:
        # Work rights are in the profile; salary and gender are left on "ask me" on purpose.
        s.get_one(Profile, 1).answers = ApplicationAnswers(
            country="Egypt",
            authorized_countries=["Egypt"],
            needs_sponsorship=False,
            years_experience=8,
        ).model_dump()
    tiers = await score_jobs(db, cfg, ai, run_id)
    with serve(app) as base:
        with db.begin() as s:
            # Stored job addresses are https on the in-process host; the browser needs the port.
            for job in s.scalars(select(Job).filter_by(state=JobState.queued_apply)):
                uid = job.url.rsplit("/", 1)[1]
                job.data = {**job.data, "apply_url": f"{base}/jobs/{uid}"}
        counts = await apply_jobs(db, Settings(data_dir=work / "data"), cfg, ai, embed)
    checks: Counter[str] = Counter()
    kinds: dict[str, Counter[str]] = {}
    with db() as s:
        parked = {a.job_id: a.kind.value for a in s.scalars(select(ActionItem))}
        for job in s.scalars(select(Job)):
            if not job.data.get("apply_url"):
                continue
            kind = form_kind(int(job.url.rsplit("/", 1)[1]))
            filled = job.data.get("filled") or {}
            done = bool(job.data.get("dry_run_at"))
            outcome = "filled" if done else f"waits: {parked.get(job.id, job.state.value)}"
            kinds.setdefault(kind, Counter())[outcome] += 1
            if kind == "sensitive":  # right = it waits for the user with a question
                checks["right_outcome"] += not done and job.id in parked
            else:
                checks["right_outcome"] += done
            if done:  # a form that waits for the user has recorded nothing yet
                got = {label: _field(filled, label) for label in ("Full name", "Email", "Phone")}
                checks["fields"] += 3
                checks["fields_right"] += got["Full name"] == "Jane Doe"
                checks["fields_right"] += got["Email"] == "jane@example.com"
                # the filler writes the number without spaces
                checks["fields_right"] += re.sub(r"\D", "", str(got["Phone"])) == DIGITS
            if kind == "simple":
                checks["uploads"] += 1
                checks["cv_attached"] += bool(_field(filled, "Resume/CV"))
            if kind == "two_page":
                checks["traps"] += 1
                checks["traps_left_empty"] += not _field(filled, "Leave this empty")
    attempted = sum(sum(c.values()) for c in kinds.values())
    return {
        "attempted": attempted,
        "scored_high": tiers.get("high", 0),
        "outcomes": counts,
        "by_form": {k: dict(c) for k, c in sorted(kinds.items())},
        "right_outcome": checks["right_outcome"],
        "fields_right": f"{checks['fields_right']}/{checks['fields']}",
        "cv_attached": f"{checks['cv_attached']}/{checks['uploads']}",
        "traps_left_empty": f"{checks['traps_left_empty']}/{checks['traps']}",
        # must be empty: a sensitive question may only be answered from the profile or the user
        "sensitive_sent_to_ai": sorted({q for q in ai.asked if SENSITIVE.search(q)}),
        "ai_calls": ai.calls,
        "ai": ai.name,
    }


async def run_bench(n: int, seed: int, embed: Embed, work: Path, apply: int = 0) -> dict[str, Any]:
    """The real stages on `n` fake jobs, in a throwaway data folder `work`. `apply` > 0 also
    scores the best jobs and fills that many fake application forms in practice mode."""
    jobs = generate(n, seed)
    db = init_db(work / "bench.db")
    cv = docx.Document()
    for line in CV_LINES:
        cv.add_paragraph(line)
    cv.save(str(work / "cv.docx"))
    import_profile(
        db,
        ProfileIn(
            full_name="Jane Doe",
            email="jane@example.com",
            phone=PHONE,
            location="Cairo, Egypt",
            cv_path=work / "cv.docx",
            skills=CV_SKILLS,
        ),
        work / "data",
    )
    # No date filter: ghost jobs are old, and the trust check is what should catch them here.
    # The titles are what a real user types at setup; without them nothing is "off-title".
    cfg = SearchConfig.model_validate(
        {"search": {"posted_within_hours": None, "queries": list(CV_QUERIES)}}
    )
    run_id = current_run(db, True)
    registry: dict[str, Source] = {FakeBoard.name: FakeBoard()}
    app = make_app(jobs, datetime.now(UTC).replace(tzinfo=None))
    timing: dict[str, float] = {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        http = Http(client, per_host_rate={HOST: 1e6})  # the fake board needs no pacing
        t = time.perf_counter()
        found = await discover(db, cfg, run_id, http, registry)
        timing["discover_s"] = time.perf_counter() - t
        t = time.perf_counter()
        enriched = await enrich(db, http, registry)
        timing["enrich_s"] = time.perf_counter() - t
    t = time.perf_counter()
    counts = rank_jobs(db, cfg, embed)
    timing["rank_s"] = time.perf_counter() - t
    with db() as s:
        stored = {int(j.url.rsplit("/", 1)[1]): j for j in s.scalars(select(Job))}
        trust = score_jobs_trust(s, list(stored.values()))
    scores = {
        u: (trust[j.id]["scam"]["score"], trust[j.id]["ghost"]["score"]) for u, j in stored.items()
    }
    total = sum(timing.values())  # finding and ranking only: applying is paced on purpose
    applied = None
    if apply:
        t = time.perf_counter()
        applied = await _apply(db, cfg, run_id, embed, app, work, apply)
        applied["seconds"] = round(time.perf_counter() - t, 2)
    return {
        "jobs": n,
        "seed": seed,
        "counts": {
            "new": found.new,
            "duplicates": found.duplicates,
            "enriched": enriched,
            "errors": len(found.errors),
            **counts,
        },
        "quality": quality(jobs, stored, scores, cfg.trust),
        **({"apply": applied} if applied else {}),
        # Timings change from run to run; everything above is the same for the same n and seed.
        "timing": {
            **{k: round(v, 2) for k, v in timing.items()},
            "total_s": round(total, 2),
            "jobs_per_minute": round(n / total * 60) if total else 0,
        },
    }
