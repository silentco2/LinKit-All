# ruff: noqa: RUF001
"""Offline scam scorer: every signal in English and Arabic, evasion, negation, floors, speed."""

import time

import pytest

from linkit_all.matching.trust import Verdict
from linkit_all.matching.trust.scam import SalaryLike, score_scam

GH = "https://boards.greenhouse.io/acme/jobs/4012345"


def run(
    desc: str,
    *,
    title: str = "Office Assistant",
    company: str = "Acme Corp",
    url: str | None = None,
    salary: SalaryLike | None = None,
    hint: str | None = None,
) -> Verdict:
    return score_scam(title, company, desc, url, salary, hint)


def codes(v: Verdict) -> set[str]:
    return {s.code for s in v.signals}


# ---- one test per signal, EN + AR --------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "A one time registration fee of $50 applies.",
        "You must pay a refundable deposit before you start.",
        "Pay to start working today.",
        "Training charge payable upfront.",
        "رسوم تسجيل 50 دولار",
        "يجب دفع رسوم الاشتراك",
        "عربون لتفعيل الحساب",
    ],
)
def test_upfront_fee(text: str) -> None:
    v = run(text)
    assert "upfront_fee" in codes(v)
    assert next(s for s in v.signals if s.code == "upfront_fee").weight == 26


@pytest.mark.parametrize(
    "text",
    [
        "Deposit the check we send you and wire the balance to our vendor.",
        "Receive packages at home and forward them to our warehouse.",
        "You will be a payment processing agent using Western Union.",
        "ويسترن يونيون وتحويل المبلغ",
    ],
)
def test_money_mule(text: str) -> None:
    v = run(text)
    assert "money_mule" in codes(v)
    assert v.score >= 80


@pytest.mark.parametrize(
    "text",
    [
        "Deposit USDT into the company wallet to activate your account.",
        "You need to fund your wallet with bitcoin first.",
        "ايداع مبلغ بيتكوين في المحفظة",
    ],
)
def test_crypto_deposit(text: str) -> None:
    v = run(text)
    assert "crypto_deposit" in codes(v)
    assert v.score >= 80


@pytest.mark.parametrize(
    "text",
    [
        "Applicants will purchase their starter kit from our partner.",
        "Buy gift cards for clients and we will reimburse you.",
        "You must buy the materials yourself.",
        "شراء بطاقات هدايا للعملاء",
    ],
)
def test_buy_to_work(text: str) -> None:
    v = run(text)
    assert "buy_to_work" in codes(v)
    assert v.score >= 65


@pytest.mark.parametrize(
    "text",
    [
        "Send your social security number to HR@example.org.",
        "Please provide your bank login so we can set up payroll.",
        "Share the OTP code you receive.",
        "Upload a selfie holding your ID.",
        "Send a copy of your passport today.",
        "ارسل صورة البطاقة",
        "ابعت رقم الضمان",
    ],
)
def test_credential_harvest(text: str) -> None:
    v = run(text)
    assert "credential_harvest" in codes(v)
    assert v.score >= 80


@pytest.mark.parametrize(
    "text",
    [
        "No interview needed!",
        "Get hired without an interview.",
        "Skip the interview and start",
        "بدون مقابلة",
        "بدون مقابلات شخصية",
    ],
)
def test_no_interview(text: str) -> None:
    assert "no_interview" in codes(run(text))


@pytest.mark.parametrize(
    ("text", "code", "weight"),
    [
        ("Message us on Telegram to apply", "off_platform_telegram", 20),
        ("Our recruiter is at t.me/jobsnow", "off_platform_telegram", 20),
        ("تواصل تلغرام", "off_platform_telegram", 20),
        ("Chat with us on WhatsApp", "off_platform_whatsapp", 17),
        ("Send CV to wa.me/123456789", "off_platform_whatsapp", 17),
        ("تواصل واتساب", "off_platform_whatsapp", 17),
        ("Add us on WeChat", "off_platform_chat", 15),
        ("Contact us on Discord", "off_platform_chat", 15),
        ("Add me on Skype", "off_platform_chat", 15),
        ("DM us on Signal app", "off_platform_chat", 15),
        ("Contact recruiter on Line ID jobs1", "off_platform_chat", 15),
        ("راسل على ديسكورد", "off_platform_chat", 15),
    ],
)
def test_off_platform(text: str, code: str, weight: int) -> None:
    v = run(text)
    sig = next(s for s in v.signals if s.code == code)
    assert sig.weight == weight


@pytest.mark.parametrize(
    "text",
    [
        "Our community lives on Discord.",
        "You will be a Discord moderator for our game studio.",
        "Experience with signal processing is a plus.",
        "Report to your line manager.",
    ],
)
def test_ambiguous_channels_need_a_pivot_verb(text: str) -> None:
    assert "off_platform_chat" not in codes(run(text))


def test_pivot_verb_must_share_the_clause() -> None:
    assert "off_platform_chat" not in codes(run("Contact HR, our team also hangs out on Discord."))
    assert "off_platform_chat" in codes(run("Contact us on Discord."))


@pytest.mark.parametrize(
    "addr",
    [
        "hr.jobs@gmail.com",
        "hiring@yahoo.com",
        "x@outlook.com",
        "a@hotmail.co.uk",
        "a@icloud.com",
        "a@proton.me",
        "a@aol.com",
    ],
)
def test_free_email(addr: str) -> None:
    v = run(f"Send your CV to {addr}")
    sig = next(s for s in v.signals if s.code == "free_email_contact")
    assert sig.weight == 12
    assert "hr.jobs" not in sig.evidence  # the local part is not echoed


def test_company_email_is_fine() -> None:
    assert "free_email_contact" not in codes(run("Send your CV to jobs@acme.com"))


def test_apply_domain_mismatch() -> None:
    v = run("Great role.", url="https://sites.google.com/view/acme-hr")
    assert next(s for s in v.signals if s.code == "apply_domain_mismatch").weight == 20
    assert "apply_domain_mismatch" not in codes(run("x", url="https://careers.acme.com/apply/12"))
    assert "apply_domain_mismatch" not in codes(run("x", url="https://acmecorp-jobs.net/12"))
    assert "apply_domain_mismatch" not in codes(
        run("x", company="Initech", url="https://hr.example.org/j", hint="https://www.example.org")
    )
    assert "apply_domain_mismatch" in codes(
        run("x", company="Initech", url="https://hr.other.org/j", hint="example.org")
    )
    assert "apply_domain_mismatch" not in codes(run("x", url="https://www.wuzzuf.net/jobs/p/1"))


@pytest.mark.parametrize(
    "url",
    [
        GH,
        "https://jobs.lever.co/acme/123",
        "https://jobs.ashbyhq.com/acme/abc",
        "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/1",
        "https://acme.bamboohr.com/careers/9",
        "https://acme.recruitee.com/o/dev",
        "https://careers.smartrecruiters.com/Acme/1",
        "https://www.linkedin.com/jobs/view/1",
    ],
)
def test_trusted_ats_bonus_and_no_mismatch(url: str) -> None:
    v = run("We are hiring.", company="Totally Different Name", url=url)
    assert codes(v) == {"trusted_ats"}
    assert v.score == 25 - 8


def test_trusted_ats_includes_domains_from_our_plugins() -> None:
    v = run("We are hiring.", company="Zed", url="https://zed.applytojob.com/apply/x")
    assert "apply_domain_mismatch" not in codes(v)


def test_trusted_bonus_skipped_when_a_floor_applies() -> None:
    v = run("Pay to start; send your social security number.", url=GH)
    assert "trusted_ats" not in codes(v)
    assert v.score >= 80


@pytest.mark.parametrize(
    ("desc", "title", "expected"),
    [
        ("Earn $80,000 per week from home", "Sales Rep", "implausible_pay"),
        ("Make 60000 usd weekly", "Sales Rep", "implausible_pay"),
        ("Pay: $3,500 a week", "Junior Assistant", "implausible_pay"),
        ("Pay: $3k/week", "Intern", "implausible_pay"),
        ("Pay: 3000 usd weekly", "Entry Level Clerk", "implausible_pay"),
        ("يصل الى 5000 دولار اسبوعيا", "متدرب مبيعات", "implausible_pay"),
        ("Pay: $3,500 a week", "Senior Surgeon", "weekly_pay"),
        ("Earn $900 per week", "Cashier", "weekly_pay"),
        ("٥٠٠ دولار اسبوعيا", "كاشير", "weekly_pay"),
    ],
)
def test_weekly_pay(desc: str, title: str, expected: str) -> None:
    v = run(desc, title=title)
    got = codes(v) & {"implausible_pay", "weekly_pay"}
    assert got == {expected}
    assert next(s for s in v.signals if s.code == expected).weight == (
        30 if expected == "implausible_pay" else 12
    )


def test_weekly_pay_ignores_hours_and_other_intervals() -> None:
    assert not codes(run("Part time, 20 hours per week. $90,000 per year.")) & {
        "weekly_pay",
        "implausible_pay",
    }


def test_structured_weekly_salary() -> None:
    v = run(
        "Nice job.",
        title="Trainee",
        salary={"min": 3500, "max": 4000, "currency": "USD", "interval": "week"},
    )
    assert "implausible_pay" in codes(v)
    stored = {
        "salary_min": 900,
        "salary_max": 1000,
        "salary_currency": "USD",
        "salary_interval": "week",
    }
    assert "weekly_pay" in codes(run("Nice job.", salary=stored))  # type: ignore[arg-type]
    assert not codes(run("Nice job.", salary={"max": 90000, "interval": "year"})) & {
        "weekly_pay",
        "implausible_pay",
    }


@pytest.mark.parametrize(
    "text",
    [
        "Be your own boss with unlimited earning potential!",
        "Earn $300 per day working from home",
        "Join our network marketing team",
        "اربح 100 دولار يوميا",
        "كن رئيس نفسك",
        "ارباح غير محدودة",
    ],
)
def test_mlm(text: str) -> None:
    assert "mlm_language" in codes(run(text))


def test_company_missing() -> None:
    assert (
        next(s for s in run("x", company="  ").signals if s.code == "company_missing").weight == 14
    )
    assert "company_missing" not in codes(run("x"))


# ---- negation and coercion ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "There is no registration fee.",
        "We never ask for payment from applicants.",
        "Please note we do not charge a training fee",
        "We will never contact you on Telegram or WhatsApp.",
        "لا توجد رسوم تسجيل",
        "بدون رسوم",
        "لن نطلب اي رسوم",
        "We never ask for your social security number.",
    ],
)
def test_negation_suppresses(text: str) -> None:
    assert codes(run(text)) == set()


@pytest.mark.parametrize(
    "text",
    [
        "You must pay a registration fee.",
        "You cannot start without paying the activation fee",
        "No experience needed, registration fee applies",
        "We never charge anything. Registration fee is due before onboarding",
        "No worries but you must pay the training fee",
        "لا توجد رسوم لكن يجب دفع رسوم",
        "لا توجد خبرة ويجب دفع رسوم",
    ],
)
def test_coercion_and_clause_scope_keep_the_hit(text: str) -> None:
    assert "upfront_fee" in codes(run(text))


# ---- evasion -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Contact us on tеlegram", "off_platform_telegram"),  # Cyrillic e
        ("Contact us on Tele​gram", "off_platform_telegram"),
        ("Contact us on T3l3gr@m", "off_platform_telegram"),
        ("Contact us on Te1egram", "off_platform_telegram"),
        ("Contact us on w h a t s a p p", "off_platform_whatsapp"),
        ("Contact us on W.h.a.t.s.A.p.p", "off_platform_whatsapp"),
        ("Contact us on ＷＨＡＴＳＡＰＰ", "off_platform_whatsapp"),
        ("Pay a registrati0n f33", "upfront_fee"),
        ("Pay the activatiоn fеe", "upfront_fee"),
        ("N0 1nterview required", "no_interview"),
        ("رُسُوم تَسْجِيل", "upfront_fee"),
        ("رســـوم تسجيل", "upfront_fee"),
        ("ارسل صورة الهويّة", "credential_harvest"),
        ("تواصل واتســـاب", "off_platform_whatsapp"),
    ],
)
def test_evasion(text: str, code: str) -> None:
    assert code in codes(run(text))


def test_leetspeak_does_not_wreck_numbers() -> None:
    assert "weekly_pay" in codes(run("Earn $900 per week"))
    assert "free_email_contact" in codes(run("Mail hr2024@gmail.com"))


def test_apply_url_is_scanned_for_chat_links() -> None:
    assert "off_platform_telegram" in codes(run("Apply now", url="https://t.me/hr_acme"))


# ---- scoring -----------------------------------------------------------------------------------


def test_clean_greenhouse_job_scores_17() -> None:
    desc = (
        "Acme builds payment tooling. You will design Python services, mentor engineers and "
        "collaborate with product. Salary $140,000 - $170,000 per year. Equal opportunity employer. "
        "Interview process: recruiter call, technical screen, onsite. Benefits include health "
        "insurance and 401(k). Apply via our careers page."
    )
    v = run(
        desc,
        title="Senior Backend Engineer",
        url=GH,
        salary={"min": 140000, "max": 170000, "currency": "USD", "interval": "year"},
    )
    assert (v.score, v.band) == (17, "low")
    assert [s.code for s in v.signals] == ["trusted_ats"]


def test_plain_job_without_url_is_base_score() -> None:
    v = run("We need a barista. Hourly wage plus tips and a share of the service charge.")
    assert (v.score, v.signals, v.band) == (25, (), "low")


def test_classic_advance_fee_scam_is_high() -> None:
    v = run(
        "URGENT HIRING! Work from home, no interview. Pay a one time registration fee of $60 to "
        "activate your account. Contact our manager on Telegram @acme_hr or gmail: hr.acme@gmail.com",
        title="Data Entry Clerk",
        company="",
        url="https://bit.ly/3xYz",
    )
    assert v.band == "high"
    assert v.score >= 85
    assert {
        "upfront_fee",
        "no_interview",
        "off_platform_telegram",
        "free_email_contact",
        "company_missing",
    } <= codes(v)


def test_arabic_scam_is_high() -> None:
    v = run("وظيفة من المنزل. رسوم تسجيل 100 جنيه. تواصل واتساب. بدون مقابلة.")
    assert v.band == "high"
    assert {"upfront_fee", "off_platform_whatsapp", "no_interview"} <= codes(v)


def test_floor_fee_plus_other_signal() -> None:
    v = run("Registration fee applies.", company="Acme", url=None)
    assert (v.score, codes(v)) == (51, {"upfront_fee"})  # alone: 25 + 26, medium
    assert v.band == "medium"
    v = run("Registration fee applies. Be your own boss.")
    assert v.score == 66 and v.band == "high"
    assert any(s.code == "score_floor" for s in v.signals) is False  # 25+26+15 is already above


def test_floor_fee_plus_weak_signal_is_lifted() -> None:
    v = run("Registration fee applies.", company="")
    assert v.score == 65  # 25 + 26 + 14 = 65 exactly
    v = run("Registration fee applies. Email hr@acme.com")
    assert v.score == 51


def test_floor_off_platform_plus_no_interview() -> None:
    v = run("No interview. Message us on Telegram.", company="Acme")
    assert v.score == 25 + 18 + 20 == 63 or v.score == 65
    assert v.score == 65
    floor = next(s for s in v.signals if s.code == "score_floor")
    assert floor.weight == 2
    assert 25 + sum(s.weight for s in v.signals) == v.score


def test_floor_buy_to_work() -> None:
    v = run("You will purchase your starter kit.")
    assert v.score == 65
    assert v.band == "high"


def test_hard_floors_reach_80() -> None:
    assert run("Western Union agent wanted.").score == 80
    assert run("Share the OTP code.").score >= 80


def test_score_is_clamped() -> None:
    v = run(
        "Western Union. Deposit USDT. Send your social security number. Pay a registration fee. "
        "No interview. Telegram. WhatsApp. a@gmail.com. Earn $90,000 per week.",
        company="",
    )
    assert v.score == 100
    assert v.band == "high"


def test_bands() -> None:
    assert run("hello").band == "low"
    assert run("Registration fee applies.").band == "medium"


def test_deterministic() -> None:
    desc = "Pay a registration fee. Message us on Telegram. No interview."
    assert run(desc) == run(desc)


def test_evidence_is_short_and_not_the_full_text() -> None:
    filler = "lorem ipsum dolor sit amet " * 200
    v = run(
        filler + " registration fee " + filler + " telegram " + filler + " Earn $90,000 per week",
        url="https://x.example/p",
    )
    assert v.signals
    for s in v.signals:
        assert 0 < len(s.evidence) <= 80
    assert all(s.code and isinstance(s.weight, int) for s in v.signals)


def test_empty_inputs() -> None:
    v = score_scam("", "", "", None, None)
    assert codes(v) == {"company_missing"}
    assert v.score == 39


# ---- speed -------------------------------------------------------------------------------------


def test_scores_10k_jobs_fast() -> None:
    para = (
        "We are looking for an engineer to join our platform team. You will build services in "
        "Python and Go, review code, and work with product managers. 5+ years experience, "
        "salary $120,000 per year, remote friendly. Contact jobs@acme.com for questions. "
    )
    jobs = [(para * 8)[:3000] + f" ref {i}" for i in range(10_000)]
    start = time.perf_counter()
    for i, desc in enumerate(jobs):
        score_scam("Engineer", "Acme", desc, GH if i % 2 else None, None)
    elapsed = time.perf_counter() - start
    assert elapsed < 10, f"{elapsed:.1f}s for 10k jobs"
