"""Seeded fake jobs with ground truth. Same `n` and `seed` -> the same jobs, always."""

import random
from dataclasses import dataclass, replace

CV_LINES = (
    "Jane Doe - Backend Software Engineer",
    "Backend Engineer at Acme, 2019-2024",
    "Built and ran backend services and REST APIs in Python with FastAPI and Django",
    "Designed PostgreSQL schemas, tuned slow queries and added Redis caching",
    "Shipped microservices on Docker and Kubernetes with CI pipelines and automated tests",
    "Software Engineer at Initech, 2016-2019",
    "Wrote data pipelines and background workers in Python and Go",
)
CV_SKILLS = ["Python", "FastAPI", "Django", "PostgreSQL", "Redis", "Docker", "Kubernetes", "Go"]
RELEVANT = "backend"

# family -> (titles, sentences a posting is built from). A few honest sentences use scam words
# (WhatsApp, bank account, registration fees) to catch false alarms. Tech neighbours of the
# CV's family are there on purpose: telling backend from frontend or data work is the ranking test.
FAMILIES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "backend": (
        ("Backend Engineer", "Senior Python Developer", "Python Backend Developer",
         "Software Engineer, Backend", "مهندس برمجيات بايثون"),
        ("Build backend services and REST APIs in Python.",
         "You will work with FastAPI or Django, PostgreSQL and Redis.",
         "Deploy microservices with Docker and Kubernetes.",
         "Write automated tests and keep CI pipelines green.",
         "Design database schemas and tune slow queries.",
         "خبرة في بايثون وقواعد البيانات PostgreSQL وتطوير واجهات REST API."),
    ),
    "frontend": (
        ("Frontend Engineer", "React Developer", "Senior UI Engineer", "Angular Developer"),
        ("Build web interfaces with React and TypeScript.",
         "Turn Figma designs into accessible, responsive components.",
         "Own CSS architecture and the design system.",
         "Measure and improve page load and Core Web Vitals."),
    ),
    "data": (
        ("Data Analyst", "Data Scientist", "Business Intelligence Analyst"),
        ("Build dashboards in Power BI or Tableau for business teams.",
         "Run statistical analysis and A/B test readouts.",
         "Train forecasting models and explain them to stakeholders.",
         "Write SQL reports for finance and operations."),
    ),
    "devops": (
        ("DevOps Engineer", "Site Reliability Engineer", "Cloud Infrastructure Engineer"),
        ("Run AWS infrastructure with Terraform.",
         "Own on-call, incident response and monitoring with Prometheus.",
         "Harden networks, manage secrets and patch servers.",
         "Maintain build agents and release tooling."),
    ),
    "mobile": (
        ("iOS Developer", "Android Developer", "Flutter Developer"),
        ("Build native mobile apps in Swift or Kotlin.",
         "Publish releases to the App Store and Google Play.",
         "Work on offline sync, push notifications and app performance."),
    ),
    "sales": (
        ("Sales Executive", "Account Manager", "Business Development Representative",
         "مندوب مبيعات"),
        ("Prospect new clients by phone and email and close deals.",
         "Hit a monthly quota and keep the CRM up to date.",
         "Negotiate contracts and renewals with key accounts.",
         "Answer customer questions on WhatsApp Business and by phone.",
         "مطلوب مندوب مبيعات لديه خبرة في التعامل مع العملاء وتحقيق المستهدف الشهري."),
    ),
    "accounting": (
        ("Accountant", "Senior Financial Analyst", "Accounts Payable Specialist", "محاسب"),
        ("Prepare monthly closings, reconciliations and financial statements.",
         "Handle invoices, payroll and tax filings.",
         "Support audits and budgeting.",
         "Reconcile bank account statements and record student registration fees.",
         "مطلوب محاسب لديه خبرة في إعداد القوائم المالية والتسويات البنكية."),
    ),
    "nursing": (
        ("Registered Nurse", "ICU Nurse", "Clinical Nurse Specialist"),
        ("Provide bedside patient care and give medication.",
         "Work rotating shifts in a hospital ward.",
         "Document care plans and coordinate with physicians."),
    ),
    "marketing": (
        ("Marketing Specialist", "Content Writer", "Social Media Manager"),
        ("Plan campaigns and write copy for social media.",
         "Manage the content calendar, SEO and newsletters.",
         "Report on reach, leads and ad spend.",
         "Run the company Telegram channel and work from home two days a week."),
    ),
    "teaching": (
        ("Mathematics Teacher", "English Teacher", "Primary School Teacher"),
        ("Plan lessons and teach classes of 25 students.",
         "Mark homework and meet parents each term.",
         "Prepare students for national exams."),
    ),
}  # fmt: skip
WEIGHTS = (12, 10, 9, 9, 7, 12, 11, 10, 10, 10)  # one per family, in order

SCAMS: tuple[tuple[str, str], ...] = (
    ("Data Entry Clerk (Work From Home)",
     "Work from home! Earn $900 weekly, no experience needed. To secure your position pay a "
     "registration fee of $50. Contact our HR manager on WhatsApp or Telegram @hr_fast. Send a "
     "copy of your ID and bank account details to start receiving payments."),
    ("Payment Processing Agent",
     "We need agents to receive funds into your personal bank account and forward them in "
     "Bitcoin, keeping a 10% commission. Immediate start, no interview. Email "
     "jobs.fastcash@gmail.com with your bank details."),
    ("Online Assistant",
     "Easy online job, earn $5000 weekly from your phone. Buy the starter kit for $80 to "
     "begin. Message us on Telegram only. Guaranteed income, limited seats."),
    # The quieter kind: no fee named up front, nothing in capitals.
    ("Personal Assistant to the CEO",
     "Our CEO is travelling and needs a remote assistant to run errands. You will receive a "
     "cheque to deposit, buy gift cards for clients and send us the codes. $700 weekly. Reply "
     "with your full name, home address and phone number."),
    ("Customer Support Representative",
     "Training is paid. You first purchase your home-office equipment from our vendor and we "
     "reimburse you with your first salary. The interview is by chat on Signal."),
    ("موظف إدخال بيانات من المنزل",
     "فرصة عمل من المنزل براتب 5000 دولار أسبوعيا بدون خبرة. مطلوب دفع رسوم تسجيل 50 دولار. "
     "للتواصل واتساب فقط وأرسل صورة البطاقة وبيانات الحساب البنكي."),
)  # fmt: skip
GHOSTS: tuple[tuple[str, str], ...] = (
    ("Talent Pool", "We are always hiring. Join our talent pool for future opportunities."),
    ("General Application",
     "Don't see a role that fits? Submit your resume for general consideration and we will "
     "reach out when something opens up."),
    ("Future Opportunities",
     "We are always looking for great people. Send us your CV and we will keep it on file."),
)  # fmt: skip
LOCATIONS = ("Cairo, Egypt", "Dubai, UAE", "Riyadh, Saudi Arabia", "Berlin, Germany",
             "London, UK", "Austin, TX", "Toronto, Canada", "Remote")  # fmt: skip
_SYL = (
    ("Zen", "Nor", "Alt", "Vex", "Kal", "Mir", "Sol", "Tar", "Lum", "Bri",
     "Cor", "Dax", "Ely", "Fen", "Gal", "Hal", "Ix", "Jor", "Qua", "Ry"),
    ("vo", "ta", "mi", "ra", "lo", "ne", "su", "ki", "da", "pe",
     "zu", "xa", "ho", "bi", "ge", "fy", "wo", "cu", "ja", "ty"),
    ("lab", "works", "soft", "tech", "ware", "logic", "point", "grid", "nest", "forge",
     "hub", "mind", "path", "wave", "core", "link", "bay", "peak", "field", "stone"),
)  # fmt: skip


@dataclass(frozen=True)
class FakeJob:
    uid: int
    title: str
    company: str
    location: str
    description: str
    posted_days_ago: int
    family: str  # a FAMILIES key, "scam" or "ghost"
    duplicate_of: int | None = None  # uid of the posting this one repeats

    @property
    def relevant(self) -> bool:
        return self.family == RELEVANT


def company_name(i: int) -> str:
    a, b, c = _SYL
    name = a[i % 20] + b[i // 20 % 20] + c[i // 400 % 20]
    return name if i < 8000 else f"{name} {i // 8000}"


def _variant(title: str, kind: int) -> str:
    """How a repost of the same job differs. 3 is the hard case: an added note."""
    if kind == 1:
        return title.upper().replace(" ", "  ")
    if kind == 2:
        return ", ".join(reversed(title.replace(",", "").split()))
    return f"{title} (Urgent Hiring)" if kind == 3 else title


def generate(n: int, seed: int = 1) -> list[FakeJob]:
    """`n` postings: about 3% scams, 3% ghost jobs and 8% reposts of an earlier one."""
    rng = random.Random(seed)  # noqa: S311 - test data, not a secret
    n_dup = n * 8 // 100
    n_base = n - n_dup
    n_companies = max(1, n_base // 2)
    families = list(FAMILIES)
    used: dict[int, set[str]] = {}  # two real openings at one company never share a family
    base: list[FakeJob] = []
    for uid in range(n_base):
        c = uid % n_companies
        taken = used.setdefault(c, set())
        while True:
            roll = rng.random()
            family = (
                "scam" if roll < 0.03
                else "ghost" if roll < 0.06
                else rng.choices(families, WEIGHTS)[0]
            )  # fmt: skip
            if family not in taken:
                break
        taken.add(family)
        company, days = company_name(c), rng.randint(0, 10)
        if family == "scam":
            title, body = rng.choice(SCAMS)
        elif family == "ghost":
            title, body = rng.choice(GHOSTS)
            days = rng.randint(200, 400)
        else:
            titles, sentences = FAMILIES[family]
            title = rng.choice(titles)
            picked = rng.sample(sentences, k=min(len(sentences), rng.randint(2, 4)))
            body = f"{company} is hiring a {title}. " + " ".join(picked)
        base.append(FakeJob(uid, title, company, rng.choice(LOCATIONS), body, days, family))
    # A repost shows up some way after the original, as on a real board.
    order: list[tuple[float, FakeJob]] = [(float(j.uid), j) for j in base]
    for k in range(n_dup):
        orig = rng.choice(base)
        dup = replace(
            orig, uid=n_base + k, title=_variant(orig.title, k % 4), duplicate_of=orig.uid
        )
        order.append((orig.uid + rng.uniform(0.5, 300), dup))
    return [j for _, j in sorted(order, key=lambda t: (t[0], t[1].uid))]
