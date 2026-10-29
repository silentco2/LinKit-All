"""Prepare the data folder for the usability study (docs/usability/README.md).

    uv run python scripts/seed_usability.py --data-dir <path> [--lang en|ar] [--reset]

Writes a clearly fictional, realistic state into an empty data dir: a finished profile with the
sample CV, a search config, ~67 jobs in every state the study looks at, parked questions in
"Needs you", and a finished practice run with screenshots (so "Ready to apply for real?" shows).
Everything goes through the app's own helpers; filter reasons come from `rule_violation` itself.
"""

import argparse
import io
import shutil
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import docx
from docx.oxml import OxmlElement
from PIL import Image, ImageDraw
from platformdirs import user_data_dir
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.apply.answers import ApplicationAnswers
from linkit_all.core.db import init_db
from linkit_all.core.models import (
    ActionItem,
    ActionKind,
    Job,
    JobEvent,
    JobState,
    Profile,
    Run,
    RunStatus,
    Tier,
    utcnow,
)
from linkit_all.core.profile import ProfileFields, save_cv, save_fields
from linkit_all.core.search import (
    AISection,
    FiltersSection,
    SearchConfig,
    SearchSection,
    SourcesSection,
    save_search,
)
from linkit_all.core.state import transition
from linkit_all.matching.rules import rule_violation
from linkit_all.sources.text import job_hash

S = JobState
NOTICE = "What is your notice period?"
PRIVACY = "I have read and accept the privacy notice"

# --- the sample CV (docs/usability/sample-cv.md) -------------------------------------------
# (kind, text); kind: name | plain | head | job | bullet
CV: dict[str, list[tuple[str, str]]] = {
    "en": [
        ("name", "Layla Hassan"),
        ("plain", "Cairo, Egypt"),
        ("plain", "layla.sample@example.com · +20 100 000 0000"),
        ("head", "Summary"),
        (
            "plain",
            "Backend developer with five years of experience building web services in "
            "Python. Likes clean code, clear documentation and small, steady releases.",
        ),
        ("head", "Skills"),
        ("bullet", "Python, FastAPI, Flask"),
        ("bullet", "PostgreSQL, Redis"),
        ("bullet", "Docker, GitHub Actions"),
        ("bullet", "REST APIs, unit testing, code review"),
        ("bullet", "English (fluent), Arabic (native)"),
        ("head", "Experience"),
        ("job", "Backend Developer, Nile Example Software, Cairo (March 2022 to present)"),
        ("bullet", "Build and maintain the booking service used by about 40 partner companies."),
        ("bullet", "Wrote the payment-reminder module and its automated tests."),
        (
            "bullet",
            "Cut the average response time of the search endpoint by simplifying database queries.",
        ),
        ("bullet", "Help new colleagues with code reviews and short guides."),
        ("job", "Junior Developer, Delta Sample Systems, Alexandria (July 2019 to February 2022)"),
        ("bullet", "Fixed bugs and added small features to an internal reporting tool."),
        ("bullet", "Wrote scripts that moved data between two systems."),
        ("bullet", "Took part in weekly planning and demos."),
        ("head", "Education"),
        ("plain", "B.Sc. in Computer Science, Example University of Cairo (2015 to 2019)"),
        ("head", "Certificates"),
        ("bullet", "Cloud Fundamentals, Sample Learning Academy (2021)"),
    ],
    "ar": [
        ("name", "ليلى حسن"),
        ("plain", "القاهرة، مصر"),
        ("plain", "layla.sample@example.com · +20 100 000 0000"),
        ("head", "نبذة"),
        (
            "plain",
            "مطوّرة خلفية بخبرة خمس سنوات في بناء خدمات الويب بلغة بايثون. تحب الشيفرة "
            "النظيفة والتوثيق الواضح والإصدارات الصغيرة المنتظمة.",
        ),
        ("head", "المهارات"),
        ("bullet", "بايثون، FastAPI، Flask"),
        ("bullet", "PostgreSQL، Redis"),
        ("bullet", "Docker، GitHub Actions"),
        ("bullet", "واجهات REST، الاختبار الآلي، مراجعة الشيفرة"),
        ("bullet", "العربية (لغة أم)، الإنجليزية (بطلاقة)"),
        ("head", "الخبرة العملية"),
        ("job", "مطوّرة خلفية، شركة النيل للبرمجيات (نموذج)، القاهرة (مارس 2022 حتى الآن)"),
        ("bullet", "أبني وأصون خدمة الحجز التي تستخدمها نحو 40 شركة شريكة."),
        ("bullet", "كتبتُ وحدة تذكير الدفع واختباراتها الآلية."),
        ("bullet", "قلّلتُ متوسط زمن استجابة نقطة البحث بتبسيط استعلامات قاعدة البيانات."),
        ("bullet", "أساعد الزملاء الجدد بمراجعات الشيفرة وأدلة قصيرة."),
        (
            "job",
            "مطوّرة مبتدئة، دلتا لنظم البرمجيات (نموذج)، الإسكندرية (يوليو 2019 حتى فبراير 2022)",
        ),
        ("bullet", "أصلحتُ أخطاء وأضفتُ ميزات صغيرة لأداة تقارير داخلية."),
        ("bullet", "كتبتُ سكربتات لنقل البيانات بين نظامين."),
        ("bullet", "شاركتُ في التخطيط الأسبوعي وعروض العمل."),
        ("head", "التعليم"),
        ("plain", "بكالوريوس علوم الحاسب، جامعة القاهرة النموذجية (2015 إلى 2019)"),
        ("head", "الشهادات"),
        ("bullet", "أساسيات الحوسبة السحابية، أكاديمية التعلّم النموذجية (2021)"),
    ],
}
PROFILE = {
    "en": (
        "Layla Hassan",
        "Cairo, Egypt",
        [
            "Python",
            "FastAPI",
            "Flask",
            "PostgreSQL",
            "Redis",
            "Docker",
            "GitHub Actions",
            "REST APIs",
        ],
        [
            "Nile Example Software",
            "Delta Sample Systems",
            "Example University of Cairo",
            "Sample Learning Academy",
            "B.Sc. in Computer Science",
        ],
    ),
    "ar": (
        "ليلى حسن",
        "القاهرة، مصر",
        [
            "Python",
            "FastAPI",
            "Flask",
            "PostgreSQL",
            "Redis",
            "Docker",
            "GitHub Actions",
            "REST APIs",
        ],
        [
            "شركة النيل للبرمجيات (نموذج)",
            "دلتا لنظم البرمجيات (نموذج)",
            "جامعة القاهرة النموذجية",
            "أكاديمية التعلّم النموذجية",
            "بكالوريوس علوم الحاسب",
        ],
    ),
}


def build_cv(lang: str) -> bytes:
    doc = docx.Document()
    for kind, text in CV[lang]:
        p = doc.add_paragraph(style="List Bullet" if kind == "bullet" else None)
        run = p.add_run(text)
        run.bold = kind in ("name", "head", "job")
        if lang == "ar":  # right-to-left paragraph and run
            p._p.get_or_add_pPr().append(OxmlElement("w:bidi"))
            run._r.get_or_add_rPr().append(OxmlElement("w:rtl"))
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


# --- fictional jobs ------------------------------------------------------------------------

PREFIXES = [
    "Nile",
    "Delta",
    "Pyramid",
    "Sinai",
    "Luxor",
    "Red Sea",
    "Giza",
    "Aswan",
    "Horus",
    "Delta Wave",
    "Papyrus",
    "Oasis",
]
SUFFIXES = [
    "Example Software",
    "Sample Systems",
    "Demo Labs",
    "Test Works",
    "Fiction Digital",
    "Placeholder Tech",
]
AR_COMPANIES = [
    "الأهرام للبرمجيات (نموذج)",
    "النخيل للحلول (نموذج)",
    "شمس للتقنية (نموذج)",
    "الواحة الرقمية (نموذج)",
    "سيناء للأنظمة (نموذج)",
    "فرعون لابس (نموذج)",
    "البحر الأحمر للبيانات (نموذج)",
    "أسوان تك (نموذج)",
]
TITLES = [
    "Backend Developer",
    "Python Developer",
    "Senior Python Engineer",
    "FastAPI Developer",
    "Software Engineer",
    "Platform Engineer",
    "Data Engineer",
    "DevOps Engineer",
    "Full Stack Developer",
    "API Developer",
    "QA Automation Engineer",
    "Junior Backend Developer",
    "Cloud Engineer",
    "Integration Engineer",
    "مطور بايثون",
    "مطور برمجيات خلفية",
    "مهندس برمجيات",
    "مهندس بيانات",
    "مطور واجهات برمجية",
    "مهندس ضمان جودة",
]
PLACES = [
    "Cairo, Egypt",
    "Giza, Egypt",
    "Alexandria, Egypt",
    "Remote",
    "Cairo, Egypt (Hybrid)",
    "القاهرة، مصر",
    "الإسكندرية، مصر",
    "Remote (Egypt)",
]
REASONS = [
    "Your Python and FastAPI work matches the main requirements.",
    "The role asks for backend services and REST APIs, like your booking service.",
    "Docker and PostgreSQL are both in your CV.",
    "Team size and level look right for five years of experience.",
]
GAPS = ["Kubernetes", "Kafka", "AWS", "GraphQL", "Terraform", "Go"]

# (title, location, extra days old, company override or None) for the six filtered jobs.
FILTERED = [
    ("Software Engineering Intern", "Cairo, Egypt", 1, None),  # title contains excluded word
    ("Sales Engineer (Python tools)", "Cairo, Egypt", 2, None),  # title contains excluded word
    ("Backend Developer", "Dubai, UAE", 3, None),  # location
    ("Python Developer", "Riyadh, Saudi Arabia", 1, None),  # location
    ("Backend Developer", "Cairo, Egypt", 2, "Shadow Staffing"),  # company blacklist
    ("FastAPI Developer", "Giza, Egypt", 30, None),  # posted too long ago
]


class Seeder:
    def __init__(self, db: sessionmaker[Session], data_dir: Path, cfg: SearchConfig) -> None:
        self.db, self.data_dir, self.cfg = db, data_dir, cfg
        self.now = utcnow()
        self.n = 0
        self.run_id = 0
        self.s: Session  # the open transaction, set by seed()

    def job(
        self,
        title: str | None = None,
        location: str | None = None,
        *,
        age: int | None = None,
        company: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Job:
        i = self.n
        self.n += 1
        title = title or TITLES[i % len(TITLES)]
        location = location or PLACES[(i * 3) % len(PLACES)]
        company = company or (
            AR_COMPANIES[i // 8]
            if i % 8 == 7 and i // 8 < len(AR_COMPANIES)
            else f"{PREFIXES[i % len(PREFIXES)]} {SUFFIXES[i // len(PREFIXES) % len(SUFFIXES)]}"
        )
        job = Job(
            run_id=self.run_id,
            source="wuzzuf" if i % 3 else "greenhouse",
            url=f"https://jobs.example.test/p/{i + 1}",
            title=title,
            company=company,
            location=location,
            posted_at=self.now - timedelta(days=i % 9 if age is None else age),
            description=(
                f"{company} is hiring a {title}. You will build and maintain web services, "
                "write tests and review code with a small team. (Fictional posting for the "
                "usability study.)"
            ),
            dedupe_hash=job_hash(title, company, location),
            data=data or {},
        )
        self.s.add(job)
        self.s.flush()
        self.s.add(JobEvent(job=job, to_state=S.discovered, message="found by the study seed"))
        return job

    def walk(
        self,
        s: Session,
        job: Job,
        path: Sequence[JobState],
        rank: float | None = None,
        score: int | None = None,
    ) -> None:
        said = {
            S.enriched: "details fetched",
            S.ranked: f"local rank {rank}",
            S.scored: f"AI score {score}",
        }
        job.data = {**job.data, "rank": rank} if rank is not None else job.data
        for state in path:
            transition(s, job, state, said.get(state, ""))

    def ai(self, i: int, score: int) -> dict[str, Any]:
        return {
            "score": score,
            "reasons": REASONS[i % 3 : i % 3 + 2],
            "missing_skills": GAPS[i % 4 : i % 4 + 1 + i % 2],
            "red_flags": [],
            "legit": "ok",
            "trust_flags": [],
        }


def seed(data_dir: Path, lang: str = "en") -> dict[str, int]:
    """Fill an empty `data_dir`. Returns the job count per state."""
    db = init_db(data_dir / "linkit.db")
    if lang not in CV:
        raise ValueError("--lang must be en or ar")
    name, city, skills, locked = PROFILE[lang]
    save_cv(
        db, data_dir, "Sample CV.docx" if lang == "en" else "Sample CV AR.docx", build_cv(lang)
    )  # the upload route's code path: segments work, CV approved
    save_fields(
        db,
        ProfileFields(
            full_name=name,
            email="layla.sample@example.com",
            phone="+20 100 000 0000",
            location=city,
            skills=skills,
            locked_facts=locked,
        ),
    )
    answers = ApplicationAnswers(
        first_name=name.split()[0],
        last_name=name.split()[-1],
        city="Cairo",
        country="Egypt",
        current_title="Backend Developer",
        years_experience=5,
        authorized_countries=["Egypt"],
    )
    with db.begin() as s:
        s.get_one(Profile, 1).answers = answers.model_dump()

    cfg = SearchConfig(
        search=SearchSection(
            queries=["Backend Developer", "Python Developer", "مطور بايثون"],
            locations=["Egypt", "Remote"],
        ),
        sources=SourcesSection(regional=["wuzzuf"]),
        filters=FiltersSection(
            title_exclude=["intern", "sales"],
            locations=["Egypt", "Remote", "مصر"],
            company_blacklist=["Shadow Staffing"],
        ),
        ai=AISection(provider="codex_cli"),
    )
    save_search(db, cfg)

    sd = Seeder(db, data_dir, cfg)
    with db.begin() as s:
        sd.s = s
        run = Run(
            status=RunStatus.done,
            started_at=sd.now - timedelta(hours=3),
            finished_at=sd.now - timedelta(hours=2, minutes=40),
        )
        s.add(run)
        s.flush()
        sd.run_id = run.id

        for _ in range(34):  # ranked: waiting for the AI score
            j = sd.job()
            sd.walk(s, j, [S.enriched, S.ranked], rank=round(0.45 + 0.012 * sd.n, 2))
        for k in range(6):  # low tier: below the threshold
            j = sd.job()
            sd.walk(
                s, j, [S.enriched, S.ranked, S.scored, S.below_threshold], rank=0.4, score=3 + k % 2
            )
            j.score, j.tier, j.data = 3 + k % 2, Tier.low, {**j.data, "ai": sd.ai(k, 3 + k % 2)}

        for title, place, age, company in FILTERED:
            j = sd.job(title, place, age=age, company=company)
            why = rule_violation(j, cfg, sd.now)  # the exact message rank.py would store
            if why is None:
                raise RuntimeError(f"seed bug: {title!r} passes the filters")
            transition(s, j, S.enriched, "details fetched")
            transition(s, j, S.filtered_out, why)
        for k in range(8):  # mid tier: waiting for the user's approval
            j = sd.job()
            score = 5 + k % 3
            sd.walk(
                s, j, [S.enriched, S.ranked, S.scored, S.awaiting_review], rank=0.7, score=score
            )
            j.score, j.tier, j.data = score, Tier.mid, {**j.data, "ai": sd.ai(k, score)}
        for k in range(5):  # high tier: ready to apply
            j = sd.job()
            score = 8 + k % 2
            sd.walk(s, j, [S.enriched, S.ranked, S.scored, S.queued_apply], rank=0.85, score=score)
            j.score, j.tier, j.data = score, Tier.high, {**j.data, "ai": sd.ai(k, score)}

        # Parked in "Needs you": four jobs share one question, one asks the privacy notice.
        questions = [
            [
                {
                    "label": NOTICE,
                    "kind": "text",
                    "options": [],
                    "required": True,
                    "reason": "not in your profile",
                    "sensitive": False,
                }
            ]
        ] * 4
        questions.append(
            [
                {
                    "label": PRIVACY,
                    "kind": "checkbox",
                    "options": [],
                    "required": True,
                    "reason": "needs your own answer",
                    "sensitive": True,
                }
            ]
        )
        for qs in questions:
            j = sd.job()
            sd.walk(
                s,
                j,
                [S.enriched, S.ranked, S.scored, S.queued_apply, S.tailored, S.applying],
                rank=0.88,
                score=9,
            )
            j.score, j.tier, j.data = 9, Tier.high, {**j.data, "ai": sd.ai(0, 9)}
            msg = f"{len(qs)} question(s) need your answer"
            transition(s, j, S.needs_user, msg, code="unknown_question", params={"n": len(qs)})
            s.add(
                ActionItem(
                    job_id=j.id,
                    kind=ActionKind.unknown_question,
                    message=msg,
                    code="unknown_question",
                    params={"n": len(qs)},
                    questions=qs,
                )
            )

        # A finished practice run: forms filled and screenshotted, nothing sent.
        for k in range(3):
            j = sd.job()
            sd.walk(
                s,
                j,
                [S.enriched, S.ranked, S.scored, S.queued_apply, S.tailored],
                rank=0.9,
                score=9,
            )
            shot = data_dir / "applications" / f"job_{j.id}" / "form.png"
            shot.parent.mkdir(parents=True, exist_ok=True)
            fake_form(shot, j)
            filled = {
                "Full name": {"value": name, "source": "profile"},
                "Email": {"value": "layla.sample@example.com", "source": "profile"},
                "Phone": {"value": "+20 100 000 0000", "source": "profile"},
                "Years of experience": {"value": 5, "source": "profile"},
                "CV": {"value": "Sample CV.docx", "source": "profile"},
            }
            j.score, j.tier = 9, Tier.high
            j.data = {
                **j.data,
                "ai": sd.ai(k, 9),
                "dry_run_at": sd.now.isoformat(),
                "filled": filled,
            }
            s.add(
                JobEvent(
                    job=j,
                    from_state=j.state,
                    to_state=j.state,
                    message=f"dry run: {len(filled)} fields filled, not submitted",
                    code="dry_run_filled",
                    params={"fields": len(filled)},
                    artifacts=[str(shot)],
                )
            )

        total = Counter(s.scalars(select(Job.state)))
        for j in s.scalars(select(Job).where(Job.state != S.filtered_out)):
            if (why := rule_violation(j, cfg, sd.now)) is not None:  # one_per_company etc. stay ok
                raise RuntimeError(f"seed bug: {j.title!r} would be filtered: {why}")
        run.stats = {
            "discover": {"new": sd.n, "duplicates": 14, "tasks_done": 9},
            "enrich": {"enriched": sd.n},
            "rank": {"ranked": sd.n - 6, "filtered_out": 6},
            "score": {"high": 8, "mid": 8, "low": 6, "not_scored": 0},
            "apply": {"dry_run": 3, "applied": 0, "needs_user": 5, "failed": 0, "skipped": 0},
        }
    db.kw["bind"].dispose()  # release the SQLite files (Windows)
    return {str(k): v for k, v in total.items()}


def fake_form(path: Path, job: Job) -> None:
    """A small stand-in for the screenshot of a filled application form."""
    img = Image.new("RGB", (640, 400), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 640, 44), fill=(59, 111, 216))
    d.text(
        (16, 16),
        f"Practice - not sent | {job.company} | {job.title}".encode("ascii", "replace").decode(),
        fill="white",
    )
    for row, label in enumerate(["Full name", "Email", "Phone", "Years of experience", "CV"]):
        y = 70 + row * 56
        d.text((24, y), label, fill=(71, 85, 105))
        d.rectangle((24, y + 16, 616, y + 40), outline=(148, 163, 184), fill=(241, 245, 249))
        d.rectangle((32, y + 24, 32 + 90 + row * 40, y + 32), fill=(100, 116, 139))
    img.save(path, "PNG")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed a data folder for the usability study.")
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--lang", choices=sorted(CV), default="en")
    ap.add_argument("--reset", action="store_true", help="delete the data dir first")
    ap.add_argument(
        "--i-know",
        action="store_true",
        help="allow the real default data dir (never do this on your own data)",
    )
    args = ap.parse_args(argv)
    target = args.data_dir.resolve()
    real = Path(user_data_dir("linkit-all", appauthor=False)).resolve()
    if (target == real or real.is_relative_to(target)) and not args.i_know:
        print(
            f"Refusing: {target} is (or contains) your real LinKit data dir {real}.\n"
            "Pick another folder, or pass --i-know if you really mean it.",
            file=sys.stderr,
        )
        return 2
    if args.reset:
        print(f"Deleting {target}")
        shutil.rmtree(target, ignore_errors=True)
    if (target / "linkit.db").exists():
        print(f"{target} already has data; pass --reset to start over.", file=sys.stderr)
        return 1
    states = seed(target, args.lang)
    print(f"Seeded {target} ({args.lang}): {sum(states.values())} jobs")
    for state, count in sorted(states.items()):
        print(f"  {state:<16}{count}")
    print(f"Start it with:  $env:LINKIT_DATA_DIR='{target}'; uv run linkit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
