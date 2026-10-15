"""What to search and how to filter/rank it, imported from search.toml until the UI exists."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import SearchConfigRow

Seniority = Literal["intern", "junior", "mid", "senior", "lead", "manager", "executive"]


class SearchSection(BaseModel):
    queries: list[str] = []
    locations: list[str] = [""]  # "" = anywhere
    posted_within_days: int = Field(14, ge=1)
    max_results_per_query: int = Field(200, ge=1, le=1000)


class SourcesSection(BaseModel):
    companies: list[str] = []  # career-page URLs or "greenhouse:stripe" style shorthands
    jobspy: list[str] = []  # linkedin, indeed, glassdoor, google, zip_recruiter
    jobspy_country: str = "usa"  # Indeed/Glassdoor country, e.g. "egypt", "uae"
    regional: list[str] = []  # wuzzuf, bayt


class FiltersSection(BaseModel):
    title_include: list[str] = []  # any of these words must be in the title (empty = all)
    title_exclude: list[str] = []
    locations: list[str] = []  # any substring match (empty = anywhere)
    remote: Literal["any", "remote", "hybrid", "onsite"] = "any"
    seniority: list[Seniority] = []  # empty = any
    salary_floor: int = 0  # yearly; only checked when the posting states a salary
    company_blacklist: list[str] = []
    one_per_company: bool = True


class MatchingSection(BaseModel):
    ai_max_jobs: int = Field(300, ge=0)  # best locally-ranked jobs sent to the AI per run
    tier_high: int = Field(8, ge=1, le=10)  # score >= this: auto-apply
    tier_mid: int = Field(5, ge=1, le=10)  # score >= this: needs your approval
    batch_size: int = Field(15, ge=1, le=30)  # jobs per AI call


class SearchConfig(BaseModel):
    search: SearchSection = SearchSection()
    sources: SourcesSection = SourcesSection()
    filters: FiltersSection = FiltersSection()
    matching: MatchingSection = MatchingSection()


def import_search(db: sessionmaker[Session], path: Path) -> SearchConfig:
    cfg = SearchConfig.model_validate(tomllib.loads(path.read_text("utf-8")))
    with db.begin() as s:
        s.merge(SearchConfigRow(id=1, data=cfg.model_dump()))
    return cfg


def load_search(db: sessionmaker[Session]) -> SearchConfig | None:
    with db() as s:
        row = s.get(SearchConfigRow, 1)
        return SearchConfig.model_validate(row.data) if row else None
