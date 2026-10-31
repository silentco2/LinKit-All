"""Suggestions from bundled offline lists (countries, places, titles) and from stored jobs.

Nothing here is looked up online and nothing is written: a suggestion becomes data only when
the user picks it in the UI.
"""

from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core import fx, geo
from linkit_all.core.infer import _LEX, _LEX_CI, _LEX_CS, read_cv
from linkit_all.core.models import Job
from linkit_all.core.profile import load_fields

router = APIRouter(prefix="/api")

MAX_SKILLS = 15
MIN_JOBS = 2  # a lexicon skill must show up in this many descriptions to be "often"
_CANON = {w.casefold(): w for w in _LEX}


def _db(request: Request) -> sessionmaker[Session]:
    db: sessionmaker[Session] = request.app.state.db
    return db


def _cv_titles(db: sessionmaker[Session]) -> list[str]:
    """Job titles read from the stored CV; empty when there is none or it cannot be read."""
    from linkit_all.tailor.pipeline import cv_segments

    _, cv = load_fields(db)
    if not cv or not Path(cv).is_file():
        return []
    try:
        facts = read_cv([s.text for s in cv_segments(Path(cv))])
    except Exception:  # a damaged CV must not break typing in a box
        return []
    return [e.title for e in facts.experiences if e.title]


def _job_titles(db: sessionmaker[Session], q: str) -> list[str]:
    """The most frequent stored job titles that contain `q`: one grouped query."""
    stmt = select(Job.title).group_by(Job.title).order_by(func.count().desc()).limit(20)
    if q.strip():
        stmt = stmt.where(Job.title.icontains(q.strip(), autoescape=True))
    with db() as s:
        return list(s.scalars(stmt))


@router.get("/countries")
def get_countries() -> list[dict[str, str]]:
    return [asdict(c) for c in geo.countries()]


@router.get("/suggest/places")
def suggest_places(q: str = "", lang: str = "en") -> list[dict[str, str]]:
    return geo.search_places(q, lang)


@router.get("/suggest/titles")
def suggest_titles(request: Request, q: str = "") -> list[str]:
    db = _db(request)
    return geo.search_titles(q, extra=[*_cv_titles(db), *_job_titles(db, q)])


def _missing_skills(job_data: dict[str, Any]) -> set[str]:
    ai = job_data.get("ai")
    found = ai.get("missing_skills") if isinstance(ai, dict) else None
    if not isinstance(found, list):
        return set()
    return {x.strip() for x in found if isinstance(x, str) and 0 < len(x.strip()) <= 40}


@router.get("/suggest/skills")
def suggest_skills(request: Request) -> list[str]:
    """Skills the user does not list yet: what the AI found missing in the best-scored jobs,
    then lexicon skills that recur in job descriptions. Suggestions only; nothing is saved."""
    db = _db(request)
    with db() as s:
        owned = {x.casefold() for x in load_fields(db)[0].skills}
        top = s.scalars(
            select(Job.data).where(Job.score.is_not(None)).order_by(Job.score.desc()).limit(200)
        )
        missing = Counter[str]()
        shown: dict[str, str] = {}
        for data in top:
            for skill in _missing_skills(data):
                missing[skill.casefold()] += 1
                shown.setdefault(skill.casefold(), skill)
        mentioned = Counter[str]()
        for text in s.scalars(select(Job.description).order_by(Job.id.desc()).limit(500)):
            found = {m[0].casefold() for rx in (_LEX_CI, _LEX_CS) for m in rx.finditer(text)}
            mentioned.update(found)
    ranked = [k for k, _ in missing.most_common()]
    ranked += [k for k, n in mentioned.most_common() if n >= MIN_JOBS and k not in missing]
    return [shown.get(k) or _CANON.get(k, k) for k in ranked if k not in owned][:MAX_SKILLS]


@router.get("/fx")
def get_fx(request: Request) -> dict[str, Any]:
    table = fx.rates(request.app.state.settings.data_dir)
    return {"date": table.date, "base": table.base, "currencies": sorted(table.rates)}
