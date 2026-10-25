"""What to search and how to filter/rank it, imported from search.toml until the UI exists."""

import re
import tomllib
from itertools import product
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.config import ProviderName
from linkit_all.core.models import SearchConfigRow

Seniority = Literal["intern", "junior", "mid", "senior", "lead", "manager", "executive"]


WorkMode = Literal["remote", "hybrid", "onsite"]
WORK_MODES: list[WorkMode] = ["remote", "hybrid", "onsite"]


def expand_query(q: str) -> list[str]:
    """ "React/Next.JS Developer" -> "React Developer", "Next.JS Developer"."""
    alts = [w.split("/") if "/" in w else [w] for w in q.split()]
    return [" ".join(" ".join(p).split()) for p in product(*alts)]


# Public Telegram channels that post jobs, read through their web preview (t.me/s/<name>).
# Curated by freehire (MIT, https://github.com/strelov1/freehire), where this list came from.
DEFAULT_TELEGRAM_CHANNELS: tuple[str, ...] = (
    "hrlunapark",
    "normrabota",
    "budujobs",
    "streltsova_anastasiya",
    "it_vakansii_jobs",
    "vakansii_it",
    "zrabota",
    "huntmejob",
    "newdirections",
    "jobforjunior",
    "young_june",
    "juniors_rabota_jobs",
    "jobs_juniors_remote",
    "job_it_junior",
    "remotejun",
    "juno_jobs",
    "young_intern",
    "it_interns",
    "refer_me_it",
    "product_jobs",
    "productjobgo",
    "hireproproduct",
    "forproducts",
    "foranalysts",
    "serious_tester",
    "forallqa",
    "job_python",
    "Remoteit",
    "young_relocate",
    "remote_jobs_relocate",
    "avito_career",
    "mtsbankcareer",
    "job_web3",
    "crypto_vacancy_web3",
    "careers_crypto",
    "dot_aware",
    "gocareers",
    "jobs_and_internships_updates",
    "jobsandinternshipsupdates",
    "off_campus_jobs_and_internships",
    "offcampus_phodenge",
    "freshercareersdotin",
    "OceanOfJobs",
    "JobsPur",
    "jobvila",
    "hiringdaily",
    "TorchBearerr",
    "jobsstation_official",
    "tamilanjobupdates",
    "arunchauhanofficial",
    "jobwithmayra",
    "goyalarsh",
    "vijaykushal",
    "PrepTrain",
    "cs_algo",
    "dataanalyticsbuddy",
    "cv_2essence",
    "tohire_ng",
    "jobnetworkng",
    "dejob_global",
    "DeJob_official",
    "STEMJobsCR",
    "amalw3amal1",
    "seekingyourjobs",
    "cafeinavagas",
    "youritjob",
    "worklinketh",
    "talentatweb3",
    "work_for_top",
    "workfortop",
    "forchiefs",
    "xCareers",
    "middle_top_vacancies",
    "cgrowthcareer",
    "vacanciesbest",
    "morejobs",
    "moskovskayarabota",
    "digital_hr",
    "huggabletalents",
    "evacuatejobs",
    "zarubezhom_jobs",
    "marketing_jobs",
    "forallmarketing",
    "wantapply_marketing",
    "wantapply_managers",
    "wantapply_design",
    "wantapply_analytics",
    "wantapply_qa_jobs",
    "naymarnya",
    "halepnyirecruiting",
    "devops_dou",
    "dou_qa",
    "frontend_dou",
    "gamedev_dou",
    "junior_dou_ua",
)
_CHANNEL_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}")  # Telegram usernames: 4-32 characters
_CHANNEL_PREFIX = re.compile(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:s/)?|^@", re.I)


def normalize_channel(raw: str) -> str:
    """ "@name", "t.me/name", "https://t.me/s/name/123?x" -> "name"; ValueError if not a channel."""
    name = _CHANNEL_PREFIX.sub("", raw.strip()).split("/")[0].split("?")[0]
    if not _CHANNEL_NAME.fullmatch(name):
        raise ValueError(f"{raw.strip()!r} is not a Telegram channel name")
    return name


class SearchSection(BaseModel):
    queries: list[str] = []
    locations: list[str] = [""]  # "" = anywhere
    posted_within_days: int = Field(14, ge=1)
    max_results_per_query: int = Field(200, ge=1, le=1000)

    @field_validator("queries")
    @classmethod
    def _expand(cls, v: list[str]) -> list[str]:
        out: dict[str, str] = {}
        for e in (e for q in v for e in expand_query(q) if e):
            out.setdefault(e.casefold(), e)  # dedupe case-insensitively, first spelling wins
        return list(out.values())


class SourcesSection(BaseModel):
    companies: list[str] = []  # career-page URLs or "greenhouse:stripe" style shorthands
    jobspy: list[Literal["linkedin", "indeed", "glassdoor", "google", "zip_recruiter"]] = []
    jobspy_country: str = "usa"  # Indeed only (Glassdoor gets none); e.g. "egypt", "qatar"
    regional: list[Literal["wuzzuf", "bayt", "forasna"]] = []
    enabled: list[str] = []  # names of aggregator / board / company source plugins to run
    # Channels read when "telegram" is in `enabled`; "@name" and t.me links are accepted.
    telegram_channels: list[str] = Field(default_factory=lambda: list(DEFAULT_TELEGRAM_CHANNELS))

    @field_validator("telegram_channels")
    @classmethod
    def _channels(cls, v: list[str]) -> list[str]:
        out: dict[str, str] = {}
        for name in (normalize_channel(c) for c in v if c.strip()):
            out.setdefault(name.lower(), name)  # t.me names are case-insensitive; first wins
        return list(out.values())

    use_discovered_boards: bool = False  # also crawl stored boards (`linkit discover-boards`)
    boards_per_run: int = Field(300, ge=0, le=20000)  # stored boards crawled per run, oldest first


class FiltersSection(BaseModel):
    title_include: list[str] = []  # any of these words must be in the title (empty = all)
    title_exclude: list[str] = []
    locations: list[str] = []  # any substring match (empty = anywhere)
    work_modes: list[WorkMode] = Field(default_factory=lambda: list(WORK_MODES))
    seniority: list[Seniority] = []  # empty = any
    salary_floor_monthly: int = Field(0, ge=0)  # only checked when the posting states a salary
    salary_currency: str = "EGP"  # only postings in this currency are compared
    company_blacklist: list[str] = []
    one_per_company: bool = True

    @model_validator(mode="before")
    @classmethod
    def _migrate(cls, data: Any) -> Any:
        """Configs saved before monthly pay / multi work mode: salary_floor (yearly), remote."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "salary_floor" in data:
            old = data.pop("salary_floor")
            if isinstance(old, int | float):
                data.setdefault("salary_floor_monthly", round(old / 12))
        if "remote" in data:
            old = data.pop("remote")
            data.setdefault("work_modes", list(WORK_MODES) if old == "any" else [old])
        return data

    @field_validator("work_modes")
    @classmethod
    def _modes(cls, v: list[WorkMode]) -> list[WorkMode]:
        if not v:
            raise ValueError("choose at least one work mode")
        return list(dict.fromkeys(v))

    @field_validator("salary_currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", v):
            raise ValueError("salary_currency must be a 3-letter code such as EGP")
        return v


class MatchingSection(BaseModel):
    ai_max_jobs: int = Field(300, ge=0)  # best locally-ranked jobs sent to the AI per run
    tier_high: int = Field(8, ge=1, le=10)  # score >= this: auto-apply
    tier_mid: int = Field(5, ge=1, le=10)  # score >= this: needs your approval
    batch_size: int = Field(15, ge=1, le=30)  # jobs per AI call
    auto_apply_low: bool = False  # opt in: low-tier jobs are applied to as well (best first)


class ApplySection(BaseModel):
    live: bool = False  # off = dry run: fill forms and take screenshots, never submit
    submit_without_asking: bool = False  # off = each live submission waits for your click
    max_per_run: int = Field(10, ge=1, le=100)
    daily_cap_per_site: int = Field(20, ge=1, le=200)  # live submissions per ATS per day
    headless: bool = False  # True hides the browser window
    min_pause_s: int = Field(20, ge=0)  # random wait between live applications
    max_pause_s: int = Field(60, ge=0)
    parallel_sites: int = Field(3, ge=1, le=3)  # sites worked on at the same time
    generic_agent: bool = True  # use the AI form agent for sites without a dedicated handler


class AISection(BaseModel):
    """Chosen in the setup wizard; LINKIT_PROVIDER / LINKIT_MODEL apply when unset."""

    provider: ProviderName | None = None
    model: str | None = None
    api_base: str | None = None  # local OpenAI-compatible server; litellm only. Keys stay in env.


class EmailSection(BaseModel):
    """Mailbox that receives sign-up verification emails; the app password lives in the vault."""

    imap_host: str = "imap.gmail.com"
    imap_user: str = ""  # empty = the profile email
    smtp_host: str = "smtp.gmail.com"  # outgoing mail (implicit SSL); same app password as IMAP
    smtp_port: int = Field(465, ge=1, le=65535)
    timeout_s: int = Field(300, ge=30, le=1800)  # how long to wait for a verification email
    poll_s: int = Field(10, ge=3, le=120)

    def effective_smtp_host(self) -> str:
        """The SMTP host; an unchanged Gmail default follows a Yahoo IMAP host."""
        if self.smtp_host == "smtp.gmail.com" and self.imap_host.lower() == "imap.mail.yahoo.com":
            return "smtp.mail.yahoo.com"
        return self.smtp_host


class ScheduleSection(BaseModel):
    """Automatic runs while the app is open (the server must be running at that time)."""

    enabled: bool = False
    days: list[int] = Field([0, 1, 2, 3, 4, 5, 6], min_length=1)  # 0 = Monday .. 6 = Sunday
    times: list[str] = Field(["09:00"], min_length=1, max_length=6)  # "HH:MM", 24 h, local time
    new_run: bool = True  # start a new discovery run each time (else resume an unfinished one)

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(not 0 <= d <= 6 for d in v):
            raise ValueError("days must be 0 (Monday) to 6 (Sunday)")
        return sorted(set(v))

    @field_validator("times")
    @classmethod
    def _times(cls, v: list[str]) -> list[str]:
        if any(not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t) for t in v):
            raise ValueError("times must look like 09:30 (24-hour HH:MM)")
        return sorted(set(v))


class TrustSection(BaseModel):
    """Scam and ghost-job checks run in the rank stage (offline, no AI)."""

    enabled: bool = True
    scam_threshold: int = Field(65, ge=1, le=100)  # scam score at or above: filtered out
    ghost_threshold: int = Field(50, ge=1, le=100)  # ghost score at or above: demoted to low tier
    filter_ghost: bool = False  # filter ghost jobs out instead of demoting them to the low tier
    allow_companies: list[str] = []  # "Not a scam": these companies skip the scam rule


class SearchConfig(BaseModel):
    search: SearchSection = SearchSection()
    sources: SourcesSection = SourcesSection()
    filters: FiltersSection = FiltersSection()
    trust: TrustSection = TrustSection()
    matching: MatchingSection = MatchingSection()
    apply: ApplySection = ApplySection()
    ai: AISection = AISection()
    email: EmailSection = EmailSection()
    schedule: ScheduleSection = ScheduleSection()


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
