"""Seeded fake jobs with ground truth. Same `n` and `seed` -> the same jobs, always.

The cases are written from how real postings look, not from the pipeline's rules: when the
pipeline misses one, fix the pipeline or leave the miss in the numbers. Do not soften the case.
"""

import random
from dataclasses import dataclass, replace
from typing import Any

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
# "backend_plain" is the same work described without naming the CV's tools.
RELEVANT = frozenset({"backend", "backend_plain"})

# family -> (titles, sentences a posting is built from). A few honest sentences use scam words
# (WhatsApp, bank account, wire transfers, weekly pay, Bitcoin) to catch false alarms. Tech
# neighbours of the CV's family are there on purpose: telling backend from frontend or data
# work is the ranking test.
FAMILIES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "backend": (
        ("Backend Engineer", "Senior Python Developer", "Python Backend Developer",
         "Software Engineer, Backend", "مهندس برمجيات بايثون"),
        ("Build backend services and REST APIs in Python.",
         "You will work with FastAPI or Django, PostgreSQL and Redis.",
         "Deploy microservices with Docker and Kubernetes.",
         "Write automated tests and keep CI pipelines green.",
         "Design database schemas and tune slow queries.",
         "Work on the deposit and withdrawal services of our Bitcoin exchange.",
         "خبرة في بايثون وقواعد البيانات PostgreSQL وتطوير واجهات REST API."),
    ),
    "backend_plain": (
        ("Software Engineer (Platform)", "API Developer", "Server-Side Engineer",
         "Senior Services Engineer", "مطور خدمات خلفية"),
        ("Design and operate the server-side systems behind our web and mobile products.",
         "Own web services, data storage and caching layers end to end.",
         "Improve the reliability and response times of our APIs.",
         "Ship in containers through an automated release pipeline.",
         "Model relational data and keep queries fast.",
         "تطوير الخدمات الخلفية وواجهات البرمجة وقواعد البيانات العلائقية."),
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
         "Interviews are held on Microsoft Teams or a WhatsApp video call.",
         "مطلوب مندوب مبيعات لديه خبرة في التعامل مع العملاء وتحقيق المستهدف الشهري."),
    ),
    "accounting": (
        ("Accountant", "Senior Financial Analyst", "Accounts Payable Specialist", "محاسب"),
        ("Prepare monthly closings, reconciliations and financial statements.",
         "Handle invoices, payroll and tax filings.",
         "Support audits and budgeting.",
         "Reconcile bank account statements and record student registration fees.",
         "Process wire transfers and Western Union payouts for our retail clients.",
         "مطلوب محاسب لديه خبرة في إعداد القوائم المالية والتسويات البنكية."),
    ),
    "nursing": (
        ("Registered Nurse", "ICU Nurse", "Clinical Nurse Specialist"),
        ("Provide bedside patient care and give medication.",
         "Work rotating shifts in a hospital ward.",
         "Document care plans and coordinate with physicians.",
         "Weekly pay of $1,800 through our staffing agency."),
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
WEIGHTS = (9, 6, 10, 9, 9, 7, 11, 10, 9, 10, 10)  # one per family, in order
# Many real postings end with this. It names every scam word and is not one.
DISCLAIMER = (
    "We never ask candidates for payment, bank details or fees at any stage of hiring; "
    "report anyone who does."
)

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
    ("Logistics Coordinator (Home Based)",
     "Receive parcels at your home address, check the contents, repack them and post them "
     "abroad with the labels we email you. $40 for every parcel, paid monthly."),
    ("Product Reviewer",
     "Rate hotels and products in our app and earn a commission on every task. Top up your "
     "account balance to unlock the higher-paying task levels. Withdraw any time."),
    ("Remote Operations Associate",
     "Your salary is paid in USDT. To activate your work account you make a one-time USDT "
     "transfer to the company wallet, returned with your first payout."),
    ("Mystery Shopper",
     "Evaluate money transfer outlets near you. We post you a check: keep $300 as your pay "
     "and send the rest by MoneyGram to the next evaluator."),
    ("Office Administrator",
     "Shortlisted candidates must complete a background screening through our partner link "
     "before the interview. The $35 screening cost is paid by the candidate."),
    ("Payroll Onboarding Clerk",
     "To set you up on payroll before your start date, send a photo of your passport and "
     "your online banking username and password to our onboarding officer."),
    ("مسوق من المنزل",
     "اشترك بمبلغ 200 جنيه فقط واربح عمولة عن كل شخص تضمه إلى الفريق. دخل يومي مضمون "
     "والتواصل عبر تيليجرام."),
)  # fmt: skip
# Ghost = a posting with no opening behind it. Half are old, half look freshly posted.
GHOSTS: tuple[tuple[str, str], ...] = (
    ("Talent Pool", "We are always hiring. Join our talent pool for future opportunities."),
    ("General Application",
     "Don't see a role that fits? Submit your resume for general consideration and we will "
     "reach out when something opens up."),
    ("Future Opportunities",
     "We are always looking for great people. Send us your CV and we will keep it on file."),
    ("Expression of Interest - Engineering",
     "There is no vacancy right now. Register your interest and our recruiters will contact "
     "you if a suitable position becomes available."),
    ("Talent Community",
     "Join our talent community to hear about roles before they are advertised. This is not "
     "an application for a specific job."),
    ("سجل سيرتك الذاتية",
     "لا توجد وظيفة شاغرة حاليا. سجل سيرتك الذاتية في قاعدة بياناتنا وسنتواصل معك عند توفر "
     "فرص مستقبلية."),
)  # fmt: skip
# Not relevant to the CV, though full of its keywords: a different job that mentions the tools.
DECOYS: tuple[tuple[str, str], ...] = (
    ("Python Instructor",
     "Teach Python, Django and PostgreSQL to beginners in evening classes. Prepare slides, "
     "mark assignments and mentor students. Classroom teaching experience is required."),
    ("Technical Recruiter",
     "Source and interview backend engineers skilled in Python, FastAPI, Docker and "
     "Kubernetes. Manage the hiring pipeline and negotiate offers."),
    ("Sales Engineer",
     "Sell our Kubernetes and Docker platform to enterprise buyers. Run demos, answer RFPs "
     "and hit a quarterly quota. Knowing Redis and PostgreSQL helps on calls."),
    ("Technical Writer",
     "Write the documentation for our REST APIs and Python SDKs. Interview engineers and "
     "publish guides and release notes."),
    ("Marketing Analyst (Python)",
     "Analyse campaign data in Python and PostgreSQL, build dashboards and present findings "
     "to the marketing team."),
)  # fmt: skip
PAIRS = {"scam": SCAMS, "ghost": GHOSTS, "decoy": DECOYS}
LOCATIONS = ("Cairo, Egypt", "Dubai, UAE", "Riyadh, Saudi Arabia", "Berlin, Germany",
             "London, UK", "Austin, TX", "Toronto, Canada", "Remote")  # fmt: skip
_ABBREV = (("Senior", "Sr."), ("Engineer", "Eng."), ("Developer", "Dev"), ("Manager", "Mgr"),
           ("Representative", "Rep"), ("Specialist", "Spec."))  # fmt: skip
_SYL = (
    ("Zen", "Nor", "Alt", "Vex", "Kal", "Mir", "Sol", "Tar", "Lum", "Bri",
     "Cor", "Dax", "Ely", "Fen", "Gal", "Hal", "Ix", "Jor", "Qua", "Ry"),
    ("vo", "ta", "mi", "ra", "lo", "ne", "su", "ki", "da", "pe",
     "zu", "xa", "ho", "bi", "ge", "fy", "wo", "cu", "ja", "ty"),
    ("lab", "works", "soft", "tech", "ware", "logic", "point", "grid", "nest", "forge",
     "hub", "mind", "path", "wave", "core", "link", "bay", "peak", "field", "stone"),
)  # fmt: skip
VARIANTS = 7


@dataclass(frozen=True)
class FakeJob:
    uid: int
    title: str
    company: str
    location: str
    description: str
    posted_days_ago: int
    family: str  # a FAMILIES key, "scam", "ghost" or "decoy"
    duplicate_of: int | None = None  # uid of the posting this one repeats

    @property
    def relevant(self) -> bool:
        return self.family in RELEVANT


def company_name(i: int) -> str:
    a, b, c = _SYL
    name = a[i % 20] + b[i // 20 % 20] + c[i // 400 % 20]
    return name if i < 8000 else f"{name} {i // 8000}"


def _variant(job: FakeJob, kind: int) -> dict[str, Any]:
    """How a repost of the same job differs from the original."""
    t = job.title
    if kind == 1:  # shouting
        return {"title": t.upper().replace(" ", "  ")}
    if kind == 2:  # word order
        return {"title": ", ".join(reversed(t.replace(",", "").split()))}
    if kind == 3:  # a recruiter's note
        return {"title": f"{t} (Urgent Hiring)"}
    if kind == 4:  # the ATS requisition number
        return {"title": f"{t} - REQ-{40000 + job.uid}"}
    if kind == 5:  # the place written the short way
        return {"location": job.location.split(",")[0]}
    if kind == 6:  # an abbreviation, or the German "any gender" tag
        for long, short in _ABBREV:
            if long in t:
                return {"title": t.replace(long, short)}
        return {"title": f"{t} (m/f/d)"}
    return {}  # 0: word for word


def generate(n: int, seed: int = 1) -> list[FakeJob]:
    """`n` postings. About 3% scams, 3% ghosts, 6% keyword decoys, 8% reposts of an earlier
    posting, and 2% the same title at the same company in another city (not a repost)."""
    rng = random.Random(seed)  # noqa: S311 - test data, not a secret
    n_dup, n_sib = n * 8 // 100, n * 2 // 100
    n_base = n - n_dup - n_sib
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
                else "decoy" if roll < 0.12
                else rng.choices(families, WEIGHTS)[0]
            )  # fmt: skip
            if family not in taken:
                break
        taken.add(family)
        company, days = company_name(c), rng.randint(0, 10)
        if family in PAIRS:
            title, body = rng.choice(PAIRS[family])
            if family == "ghost" and rng.random() < 0.5:
                days = rng.randint(200, 400)
        else:
            titles, sentences = FAMILIES[family]
            title = rng.choice(titles)
            picked = rng.sample(sentences, k=min(len(sentences), rng.randint(2, 4)))
            body = f"{company} is hiring a {title}. " + " ".join(picked)
            if rng.random() < 0.15:
                body = f"{body} {DISCLAIMER}"
            if rng.random() < 0.05:
                days = rng.randint(40, 60)  # a real opening that has simply been up a while
        base.append(FakeJob(uid, title, company, rng.choice(LOCATIONS), body, days, family))
    # A repost shows up some way after the original, as on a real board.
    order: list[tuple[float, FakeJob]] = [(float(j.uid), j) for j in base]
    for k in range(n_dup):
        orig = rng.choice(base)
        dup = replace(orig, uid=n_base + k, duplicate_of=orig.uid, **_variant(orig, k % VARIANTS))
        order.append((orig.uid + rng.uniform(0.5, 300), dup))
    cities: dict[int, set[str]] = {}  # per original: no two of its copies share a city
    for k in range(n_sib):
        orig = rng.choice(base)
        seen = cities.setdefault(orig.uid, {orig.location})
        city = rng.choice([c for c in LOCATIONS if c not in seen])
        seen.add(city)
        sibling = replace(orig, uid=n_base + n_dup + k, location=city)
        order.append((orig.uid + rng.uniform(0.5, 300), sibling))
    return [j for _, j in sorted(order, key=lambda t: (t[0], t[1].uid))]
