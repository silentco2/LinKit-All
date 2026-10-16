"""What to search and how to filter/rank it, imported from search.toml until the UI exists."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.config import ProviderName
from linkit_all.core.models import SearchConfigRow

Seniority = Literal["intern", "junior", "mid", "senior", "lead", "manager", "executive"]


class SearchSection(BaseModel):
    queries: list[str] = []
    locations: list[str] = [""]  # "" = anywhere
    posted_within_days: int = Field(14, ge=1)
    max_results_per_query: int = Field(200, ge=1, le=1000)


class SourcesSection(BaseModel):
    companies: list[str] = []  # career-page URLs or "greenhouse:stripe" style shorthands
    jobspy: list[Literal["linkedin", "indeed", "glassdoor", "google", "zip_recruiter"]] = []
    jobspy_country: str = "usa"  # Indeed/Glassdoor country, e.g. "egypt", "united arab emirates"
    regional: list[Literal["wuzzuf", "bayt"]] = []


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


class ApplySection(BaseModel):
    live: bool = False  # off = dry run: fill forms and take screenshots, never submit
    submit_without_asking: bool = False  # off = each live submission waits for your click
    max_per_run: int = Field(10, ge=1, le=100)
    daily_cap_per_site: int = Field(20, ge=1, le=200)  # live submissions per ATS per day
    headless: bool = False  # True hides the browser window
    min_pause_s: int = Field(20, ge=0)  # random wait between live applications
    max_pause_s: int = Field(60, ge=0)


class AISection(BaseModel):
    """Chosen in the setup wizard; LINKIT_PROVIDER / LINKIT_MODEL apply when unset."""

    provider: ProviderName | None = None
    model: str | None = None


class EmailSection(BaseModel):
    """Mailbox that receives sign-up verification emails; the app password lives in the vault."""

    imap_host: str = "imap.gmail.com"
    imap_user: str = ""  # empty = the profile email
    timeout_s: int = Field(300, ge=30, le=1800)  # how long to wait for a verification email
    poll_s: int = Field(10, ge=3, le=120)


class SearchConfig(BaseModel):
    search: SearchSection = SearchSection()
    sources: SourcesSection = SourcesSection()
    filters: FiltersSection = FiltersSection()
    matching: MatchingSection = MatchingSection()
    apply: ApplySection = ApplySection()
    ai: AISection = AISection()
    email: EmailSection = EmailSection()


def save_search(db: sessionmaker[Session], cfg: SearchConfig) -> None:
    with db.begin() as s:
        s.merge(SearchConfigRow(id=1, data=cfg.model_dump()))


def import_search(db: sessionmaker[Session], path: Path) -> SearchConfig:
    cfg = SearchConfig.model_validate(tomllib.loads(path.read_text("utf-8")))
    save_search(db, cfg)
    return cfg


def load_search(db: sessionmaker[Session]) -> SearchConfig | None:
    with db() as s:
        row = s.get(SearchConfigRow, 1)
        return SearchConfig.model_validate(row.data) if row else None
