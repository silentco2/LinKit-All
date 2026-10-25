"""Offline scam scorer for job postings (English + Arabic). No AI, no network, no database.

Signals and weights adapted from Hackathon-HireProof (ISC) and fake-job-detector (MIT).
Patterns are re-written for this project; word lists were adapted, not pasted.

Scoring: base 25 plus the signed weight of every signal that fires (each category once), with
floors for the worst categories, clamped to 0-100. Bands: < 35 low, < 65 medium, else high.
"""

# ruff: noqa: E501, RUF001  (regex tables, Arabic and look-alike letters on purpose)

import contextlib
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import TypedDict
from urllib.parse import urlsplit

from linkit_all.matching.trust import Signal, Verdict
from linkit_all.matching.trust.normalize import Clauses, fold_arabic, fold_light, light

BASE_SCORE = 25
TRUSTED_ATS_BONUS = -8
MEDIUM_FROM, HIGH_FROM = 35, 65
_MAX_CHARS = 30_000  # scanned prefix of title + description; scam wording sits near the top
_EVIDENCE_MAX = 80


class SalaryLike(TypedDict, total=False):
    """Salary as stored in `jobs.data` (keys `salary_min`, ... are accepted too)."""

    min: float | None
    max: float | None
    currency: str | None
    interval: str | None  # year, month, week, hour...


# ---- pattern helpers --------------------------------------------------------------------------


_LEAD = "(?<![a-z])"
_WORDS = r"(?:\w+\s+)"  # one filler word


def _terms(*phrases: str) -> str:
    """Literal phrases (spaces match any whitespace), guarded at the end by a word edge."""
    body = "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in phrases)
    return rf"(?:{body})(?![a-z0-9])"


def _any_in(needles: tuple[str, ...], text: str) -> bool:
    return any(n in text for n in needles)


class _Matcher:
    """Patterns plus optional gates. A gate is a tuple of substrings, at least one of which must be
    in the folded text before its pattern is tried: a plain `in` check is far cheaper than a regex
    scan with many alternatives, and nearly every real posting trips none of them."""

    def __init__(self, *items: str | tuple[str, ...]) -> None:
        self.entries: list[tuple[tuple[str, ...], re.Pattern[str]]] = []
        gate: tuple[str, ...] = ()
        for item in items:
            if isinstance(item, tuple):
                gate = tuple(fold_arabic(g) for g in item)
            else:
                # A leading lookbehind defeats the regex engine's literal-prefix scan, so the left
                # word edge is dropped here and enforced in `_first_hit` instead.
                self.entries.append((gate, re.compile(item.removeprefix(_LEAD))))
                gate = ()

    def finditer(self, text: str) -> Iterator[re.Match[str]]:
        seen: dict[tuple[str, ...], bool] = {}
        ascii_only = text.isascii()
        for gate, pattern in self.entries:
            if gate:
                if ascii_only and not gate[0].isascii():
                    continue  # Arabic entries cannot match an ASCII-only text
                open_ = seen.get(gate)
                if open_ is None:
                    open_ = seen[gate] = _any_in(gate, text)
                if not open_:
                    continue
            yield from pattern.finditer(text)


def _ar(pattern: str) -> str:
    """Arabic pattern source written in natural spelling, folded like the text it will match."""
    return fold_arabic(pattern)


# ---- rule definitions -------------------------------------------------------------------------

_FEE_KINDS = (
    "training|registration|activation|processing|application|membership|placement|onboarding"
    "|handling|admin|administrative|upfront|up front|setup|set up|joining|enrollment|enrolment"
    "|verification|uniform|starter|refundable|security|equipment"
)
_FEE = _Matcher(
    ("fee", "charge", "cost", "deposit"),
    rf"(?<![a-z])(?:{_FEE_KINDS})\s+(?:fees?|charges?|costs?|deposits?)(?![a-z])",
    ("fee", "deposit"),
    r"(?<![a-z])(?:pay|paying|send|sending|transfer|deposit)\s+(?:us\s+)?(?:a\s+|an\s+|the\s+|your\s+)?"
    r"(?:small\s+|nominal\s+|one time\s+|one-time\s+|refundable\s+|initial\s+|upfront\s+)*"
    r"(?:fees?|deposit)(?![a-z])",
    ("pay",),
    r"(?<![a-z])you\s+(?:must|have to|need to|will need to|will have to|are required to|should)\s+pay(?![a-z])",
    ("pay",),
    r"(?<![a-z])pay(?:ment)?\s+(?:before|to)\s+(?:start|starting|begin|beginning|work|working"
    r"|get started|receive|receiving|access|unlock|apply|join)(?![a-z])",
    ("payment", "money", "fee", "deposit"),
    r"(?<![a-z])(?:ask|asks|asking|request|requests|requesting|require|requires|requiring)\s+"
    r"(?:you\s+)?(?:for\s+)?(?:any\s+|a\s+|an\s+)?(?:upfront\s+|advance\s+)?(?:payments?|money|fees?|deposits?)(?![a-z])",
    ("charge",),
    r"(?<![a-z])charge\s+(?:you|applicants|candidates)\s+(?:a\s+|any\s+)?(?:fees?|money)(?![a-z])",
    ("advance", "upfront"),
    _terms(
        "upfront payment", "advance payment", "advance fee", "pay in advance", "payment in advance"
    ),
    ("رسوم",),
    _ar(
        r"رسوم\s+(?:ال)?(?:تسجيل|تدريب|اشتراك|تفعيل|ملف|اداري[هة]|انضمام|دور[هة]|تامين|خدم[هة]|شحن|مقدم[هة]|مسترد[هة])"
    ),
    ("دفع", "ادفع", "سداد", "تسديد", "تحويل", "ايداع"),
    _ar(
        r"(?:دفع|ادفع|سداد|تسديد|تحويل|ايداع)\s+"
        + _WORDS
        + r"{0,2}(?:رسوم|مبلغ|مصاريف|عربون|تامين)"
    ),
    ("عربون", "مصاريف", "مبلغ", "دفع"),
    _ar(
        r"عربون|مصاريف\s+(?:اداري[هة]|تسجيل|تدريب|شحن)|مبلغ\s+(?:تامين|مقدم|رمزي|الاشتراك|التسجيل)|دفع\s+مقدم"
    ),
)

_MULE = _Matcher(
    (
        "check",
        "cheque",
        "wire",
        "transfer",
        "forward",
        "reship",
        "re ship",
        "relabel",
        "re label",
        "package",
        "parcel",
        "process",
        "shopper",
        "western",
        "moneygram",
        "money gram",
        "keep",
        "send",
        "evaluate",
        "deposit",
    ),
    _terms(
        "deposit the check",
        "deposit this check",
        "deposit the cheque",
        "cash the check",
        "cash this check",
        "wire the remaining",
        "wire the balance",
        "wire the funds",
        "wire back",
        "transfer the remaining",
        "transfer the balance",
        "forward the payment",
        "forward the funds",
        "send the balance",
        "send back the difference",
        "keep your commission and",
        "reshipping",
        "reship",
        "re ship",
        "forward packages",
        "forward parcels",
        "relabel packages",
        "re label packages",
        "package forwarding",
        "parcel forwarding",
        "process payments on our behalf",
        "money transfer agent",
        "payment processing agent",
        "mystery shopper",
        "secret shopper",
        "western union",
        "moneygram",
        "money gram",
        "deposit into your account",
        "keep the difference",
        "evaluate a money transfer",
        "evaluate western union",
        "payment forwarding agent",
    ),
    ("package", "parcel"),
    r"(?<![a-z])(?:receive|get)\s+(?:\w+\s+){0,3}(?:packages?|parcels?)\s+(?:\w+\s+){0,4}(?:forward|reship|send)",
    ("ويسترن", "جرام", "شيك"),
    _ar(r"ويسترن\s*يونيون|(?:ماني|موني)\s*جرام|ايداع\s+(?:ال)?شيك|صرف\s+(?:ال)?شيك"),
    ("طرود", "شيكات", "حوالات"),
    _ar(r"استلام\s+(?:ال)?(?:طرود|شيكات|حوالات)\s+(?:و|ثم)"),
    ("شحن", "تحويل"),
    _ar(r"اعاد[هة]\s+شحن|تحويل\s+(?:ال)?(?:مبلغ|اموال)\s+(?:الي|ل)"),
)

_CRYPTO = _Matcher(
    (
        "usdt",
        "usdc",
        "btc",
        "bnb",
        "trx",
        "crypto",
        "bitcoin",
        "ethereum",
        "tether",
        "wallet",
        "trading",
        " eth",
    ),
    r"(?<![a-z])(?:deposit|fund|load|top up|recharge|send|transfer|pay|preload)\s+(?:\w+\s+){0,4}"
    r"(?:usdt|usdc|btc|eth|bnb|trx|crypto|bitcoin|ethereum|tether|wallet|trading platform|trading account)(?![a-z])",
    ("wallet", "trading", "crypto", "usdt"),
    _terms(
        "company wallet",
        "company trading",
        "crypto deposit",
        "deposit into the platform",
        "trading platform to activate",
        "usdt deposit",
        "usdt trc20",
        "fund your wallet",
    ),
    ("usdt", "تيثر", "بيتكوين", "بتكوين", "عمل", "كريبتو", "محفظ"),
    _ar(
        r"(?:ايداع|تحويل|شحن|ارسال|دفع)\s+" + _WORDS + r"{0,3}"
        r"(?:usdt|تيثر|بيتكوين|بتكوين|عملات?\s+رقمي[هة]|عمل[هة]\s+رقمي[هة]|كريبتو|محفظ[هة])"
    ),
)

_BUY = _Matcher(
    ("gift", "prepaid", "steam", "itunes", "google", "starter", "assembly", "sample"),
    r"(?<![a-z])(?:buy|purchase|order|pay for)\s+(?:\w+\s+){0,3}(?:gift\s*cards?|prepaid\s+(?:cards?|vouchers?)"
    r"|steam\s+cards?|itunes|google\s+play\s+cards?|starter\s+(?:kit|pack)|assembly\s+kit|sample\s+kit)",
    ("buy", "purchase", "order", "pay"),
    r"(?<![a-z])(?:you|applicants?|candidates?)\s+(?:will\s+|must\s+|need\s+to\s+|have\s+to\s+|should\s+)?"
    r"(?:buy|purchase|order|pay\s+for)\s+(?:\w+\s+){0,3}(?:materials?|kits?|samples?|supplies|inventory|products?)",
    ("your",),
    r"(?<![a-z])(?:buy|purchase)\s+your\s+own\s+(?:materials?|kit|supplies|inventory|samples?|products?)",
    ("reimburs",),
    r"(?<![a-z])(?:buy|purchase)\s+(?:\w+\s+){0,4}(?:and\s+)?(?:we\s+will\s+|will\s+be\s+)?reimburs",
    ("buy", "purchase", "inventory"),
    _terms("buy equipment first", "purchase the starter", "inventory purchase", "buy inventory"),
    ("شراء", "اشتر"),
    _ar(
        r"(?:شراء|اشتر[يى]?|اشتري)\s+" + _WORDS + r"{0,3}"
        r"(?:بطاق(?:ات|ه)\s+(?:هدايا|شحن|ايتونز|جوجل|اهداء)|ادوات|معدات|مواد|منتجات|حقيب[هة]|باق[هة]\s+بداي[هة])"
    ),
)

_CRED = _Matcher(
    ("social",),
    r"(?<![a-z])social\s+security\s+(?:number|no)(?![a-z])",
    ("ssn",),
    r"(?<![a-z])ssn(?![a-z])",
    ("bank",),
    r"(?<![a-z])(?:bank|banking)\s+(?:login|log in|credentials|password|username)(?![a-z])",
    ("banking",),
    r"(?<![a-z])(?:online|internet|mobile)\s+banking\s+(?:username|password|login|credentials|details)(?![a-z])",
    ("pin",),
    r"(?<![a-z])(?:debit\s+card|card|atm)\s+pin(?![a-z])",
    ("otp", "one time", "verification"),
    r"(?<![a-z])(?:send|share|provide|give|forward|reply with)\s+(?:\w+\s+){0,2}(?:otp|one time (?:password|code|pin)"
    r"|verification code)(?![a-z])",
    ("selfie",),
    r"(?<![a-z])selfie\s+(?:holding|with)\s+(?:your\s+)?(?:id|passport|licen[sc]e)(?![a-z])",
    ("holding",),
    r"(?<![a-z])photo\s+of\s+you\s+holding\s+(?:your\s+)?id(?![a-z])",
    ("passport", "identity", "licen", "ssn", "social", " id"),
    r"(?<![a-z])(?:send|email|upload|share|submit)\s+(?:us\s+)?(?:a\s+|your\s+)?(?:clear\s+)?"
    r"(?:photo|picture|scan|copy|image)\s+of\s+(?:your\s+)?(?:national\s+id|id\s+card|identity\s+card|passport"
    r"|drivers?\s+licen[sc]e|ssn|social\s+security)(?![a-z])",
    ("cvv", "card"),
    r"(?<![a-z])(?:full\s+card\s+number|cvv)(?![a-z])",
    ("ارسل", "ارسال", "رسل", "ابعت", "شارك", "قدم", "زودنا"),
    _ar(
        r"(?:ارسل|ارسال|رسل|ابعت|شارك|قدم|زودنا\s+ب)\s+"
        + _WORDS
        + r"{0,3}(?:صور[هة]|نسخ[هة]|رقم)\s+(?:من\s+)?(?:ال)?"
        r"(?:بطاق[هة]|هوي[هة]|جواز|ضمان|حساب\s+(?:ال)?بنك|رخص[هة])"
    ),
    ("رمز", "كلم", "سري", "بيانات"),
    _ar(
        r"رمز\s+(?:ال)?تحقق|كلم[هة]\s+(?:ال)?(?:مرور|سر)\s+(?:ال)?بنك|(?:ال)?رقم\s+(?:ال)?سري|بيانات\s+(?:ال)?حساب\s+(?:ال)?بنك"
    ),
)

_NO_INTERVIEW = _Matcher(
    ("interview",),
    r"(?<![a-z])no\s+interviews?(?![a-z])",
    ("interview",),
    r"(?<![a-z])without\s+(?:an?\s+|any\s+|the\s+)?interviews?(?![a-z])",
    ("interview",),
    r"(?<![a-z])skip\s+(?:the\s+)?interviews?(?![a-z])",
    ("interview",),
    r"(?<![a-z])interview\s*-?\s*free(?![a-z])",
    ("exam", "screening", "assessment", "vetting"),
    r"(?<![a-z])no\s+(?:exam|screening|assessment|vetting)(?![a-z])",
    ("hired", "hiring", "accepted", "approved"),
    r"(?<![a-z])(?:hired|hiring|accepted|approved)\s+(?:on the spot|instantly|immediately|same day)(?![a-z])",
    ("instant",),
    r"(?<![a-z])instant\s+(?:hire|hiring|approval|acceptance)(?![a-z])",
    ("مقابل", "اختبار", "امتحان"),
    _ar(
        r"(?:بدون|بلا|دون)\s+(?:اي\s+|ال?حاج[هة]\s+(?:ل|الي)\s*)?مقابل(?:ه|ات)|(?:بدون|بلا)\s+(?:اختبار|امتحان)"
    ),
    ("مقابل", "اختبار"),
    _ar(r"لا\s+(?:يوجد|توجد|تحتاج|يتطلب|تتطلب)\s+(?:الي\s+|ل)?(?:مقابل(?:ه|ات)|اختبار)"),
    ("قبول", "تعيين"),
    _ar(r"قبول\s+فوري|تعيين\s+فوري\s+بدون"),
)

_TELEGRAM = _Matcher(
    r"(?<![a-z])(?:telegram|tele\s+gram)(?![a-z])",
    r"(?<![a-z])t\.me(?![a-z])",
    ("جرام", "غرام"),
    _ar(r"(?:تيلي|تلي|تل)[جغ]رام"),
)
_WHATSAPP = _Matcher(
    r"(?<![a-z])(?:whats\s*app|whatsap|watsapp|wa\.me|wapp)(?![a-z])",
    ("واتس", "وتساب"),
    _ar(r"واتس\s*اب|وتساب|واتسب|واتس(?!\w)"),
)
_CHAT_UNAMBIGUOUS = _Matcher(
    ("chat", "weixin", "viber", "wickr", "threema", "kik", "kakao", "linktr"),
    r"(?<![a-z])(?:we\s*chat|weixin|viber|wickr|threema|snap\s*chat|kik|kakao\s*talk|linktr\.?ee)(?![a-z])",
    ("فايبر", "شات"),
    _ar(r"فايبر|وي\s*شات|سناب\s*شات"),
)
_CHAT_AMBIGUOUS = _Matcher(
    ("discord", "skype", "hangouts", "chat", "messenger", "dm"),
    r"(?<![a-z])(?:discord|skype|hangouts|google\s+chat|messenger|instagram\s+dm|ig\s+dm)(?![a-z])",
    ("signal",),
    r"(?<![a-z])signal\s+(?:app|messenger|number|group|id)(?![a-z])",
    ("signal",),
    r"(?<![a-z])(?:on|via|through|using|by)\s+signal(?![a-z])",
    ("line",),
    r"(?<![a-z])line\s+(?:id|app|chat|account)(?![a-z])",
    ("line",),
    r"(?<![a-z])(?:on|via|through|using)\s+line(?![a-z])",
    ("ديسكورد", "سكايب"),
    _ar(r"ديسكورد|سكايب"),
)
_PIVOT_VERB = re.compile(
    r"(?<![a-z])(?:message|messages|msg|contact|add|dm|dms|reach|apply|applying|chat|ping|connect|join"
    r"|inbox|pm|text|write|reply|send)(?![a-z])"
    + "|"
    + _ar(r"(?<!\w)(?:راسل\w*|تواصل\w*|اضف\w*|ارسل\w*|كلم\w*|اتصل\w*|سجل\w*|انضم\w*)")
)

_FREE_DOMAINS = frozenset(
    {"gmail.com", "outlook.com", "live.com", "icloud.com", "proton.me", "protonmail.com", "aol.com"}
)
_DOMAIN = re.compile(r"[a-z0-9.-]+")
_FREE_MAIL_OBFUSCATED = re.compile(
    r"[\w.+-]+\s*(?:\(at\)|\[at\])\s*(?:gmail|yahoo|outlook|hotmail|icloud|protonmail|aol)"
    r"\s*(?:\.|\(dot\)|\[dot\])\s*(?:com|me)"
)


def _free_mail(text: str) -> str | None:
    """Evidence ("*@gmail.com") when the text holds a free-mail address, else None. Only the domain
    is echoed, never the address."""
    pos = text.find("@")
    while pos >= 0:
        m = _DOMAIN.match(text, pos + 1)
        domain = m.group().rstrip(".-") if m else ""
        if domain in _FREE_DOMAINS or domain.startswith(("yahoo.", "hotmail.")):
            return f"*@{domain}"
        pos = text.find("@", pos + 1)
    if ("(at)" in text or "[at]" in text) and (m := _FREE_MAIL_OBFUSCATED.search(text)):
        return _snip(m.group()[-20:])
    return None


_MLM = _Matcher(
    (
        "boss",
        "unlimited",
        "marketing",
        "mlm",
        "residual",
        "freedom",
        "passive",
        "rich",
        "sleep",
        "money",
    ),
    _terms(
        "be your own boss",
        "unlimited earning",
        "unlimited earnings",
        "unlimited income",
        "unlimited potential",
        "network marketing",
        "mlm",
        "residual income",
        "financial freedom",
        "passive income",
        "get rich",
        "earn while you sleep",
        "quick money",
        "easy money",
    ),
    ("earn",),
    r"(?<![a-z])earn\s+(?:up\s+to\s+)?[$€£]?\s*\d[\d,]*\s*k?\s*(?:usd|dollars?|eur|gbp)?\s*(?:/|per|a|each|every)\s*day(?![a-z])",
    ("day",),
    r"[$€£]\s*\d[\d,]*\s*k?\s*(?:/|per|a|each|every)\s*day(?![a-z])",
    ("رئيس", "محدود", "ثراء", "ربح", "دخل", "حري"),
    _ar(
        r"كن\s+رئيس\s+نفسك|ارباح\s+غير\s+محدود[هة]|دخل\s+غير\s+محدود|ثراء\s+سريع|ربح\s+سريع|دخل\s+سلبي|حري[هة]\s+مالي[هة]"
    ),
    ("يوميا",),
    _ar(
        r"(?:اربح|ربح|تكسب|تربح|دخل)\s+"
        + _WORDS
        + r"{0,2}\d[\d,]*\s*(?:دولار|ريال|جنيه|درهم|دينار)?\s*يوميا"
    ),
)

# Weekly pay quotes are parsed on the light() text, where digits are still digits.
_CUR = r"usd|dollars?|eur|euros?|gbp|pounds?|aed|sar|egp|dirhams?|riyals?|دولار|يورو|جنيه|درهم|ريال|دينار"
_WEEK = r"(?:/|per\s+|a\s+|each\s+|every\s+|in\s+(?:the\s+)?|كل\s+|في\s+(?:ال)?)?(?:week(?:ly)?|wk)(?![a-z])|اسبوع\w*"
_WEEKLY = re.compile(
    rf"(?P<sym>[$€£]\s*)?(?P<amt>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k(?![a-z]))?\s*(?P<cur>{_CUR})?\s*(?:{_WEEK})"
    rf"|weekly\s+(?:pay|salary|income|earnings?|payout|payment)s?\s*(?:of|:|-|is)?\s*(?P<sym2>[$€£]\s*)?"
    rf"(?P<amt2>\d[\d,]*(?:\.\d+)?)\s*(?P<k2>k(?![a-z]))?\s*(?P<cur2>{_CUR})?"
)
_JUNIOR_TITLE = re.compile(
    r"(?<![a-z])(?:intern|internship|entry|junior|jr|trainee|graduate|apprentice)(?![a-z])"
    r"|متدرب|مبتدئ|مبتدي|تدريب|حديث\s+التخرج|خريج"
)
_WEEKLY_INTERVALS = {"week", "weekly", "wk", "w"}
_IMPLAUSIBLE_ANY, _IMPLAUSIBLE_JUNIOR = 60_000.0, 3_000.0


@dataclass(frozen=True)
class _Rule:
    code: str
    weight: int
    pattern: _Matcher
    negatable: bool = False
    needs_pivot: bool = False


_RULES = (
    _Rule("upfront_fee", 26, _FEE, negatable=True),
    _Rule("money_mule", 34, _MULE, negatable=True),
    _Rule("crypto_deposit", 32, _CRYPTO, negatable=True),
    _Rule("buy_to_work", 26, _BUY, negatable=True),
    _Rule("credential_harvest", 30, _CRED, negatable=True),
    _Rule("no_interview", 18, _NO_INTERVIEW),
    _Rule("off_platform_telegram", 20, _TELEGRAM, negatable=True),
    _Rule("off_platform_whatsapp", 17, _WHATSAPP, negatable=True),
)
_CHAT_RULES = (
    _Rule("off_platform_chat", 15, _CHAT_UNAMBIGUOUS, negatable=True),
    _Rule("off_platform_chat", 15, _CHAT_AMBIGUOUS, negatable=True, needs_pivot=True),
)
_MLM_RULE = _Rule("mlm_language", 15, _MLM)

_HARD_FLOOR = {"money_mule", "crypto_deposit", "credential_harvest"}
_OFF_PLATFORM = {"off_platform_telegram", "off_platform_whatsapp", "off_platform_chat"}

# ---- apply-URL trust --------------------------------------------------------------------------

# Major boards and ATS vendors (HireProof's list plus common ones); the rest come from our own
# ATS plugins via `_trusted_roots()`.
_STATIC_TRUSTED = frozenset(
    {
        "linkedin.com",
        "indeed.com",
        "jobstreet.com",
        "glassdoor.com",
        "greenhouse.io",
        "lever.co",
        "ashbyhq.com",
        "smartrecruiters.com",
        "workdayjobs.com",
        "myworkdayjobs.com",
        "workable.com",
        "recruitee.com",
        "breezy.hr",
        "bamboohr.com",
        "icims.com",
        "jobvite.com",
        "taleo.net",
        "successfactors.com",
        "successfactors.eu",
        "teamtailor.com",
        "personio.de",
        "personio.com",
        "oraclecloud.com",
        "paylocity.com",
        "ultipro.com",
        "dayforcehcm.com",
        "adp.com",
    }
)
# Job boards the sources layer fetches from: not a mismatch, but no trust bonus either.
_KNOWN_BOARDS = frozenset(
    {
        "wuzzuf.net",
        "bayt.com",
        "forasna.com",
        "naukrigulf.com",
        "ziprecruiter.com",
        "monster.com",
        "careerbuilder.com",
        "simplyhired.com",
        "talent.com",
    }
)
_HOST_IN_PATTERN = re.compile(r"((?:[a-z0-9-]+\.)+[a-z]{2,})")
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac"}


def _root(host: str) -> str:
    """Registrable-ish domain: last two labels, three when the second-level label is generic."""
    labels = [x for x in host.lower().strip(".").split(".") if x]
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


@lru_cache(maxsize=1)
def _trusted_roots() -> frozenset[str]:
    roots = set(_STATIC_TRUSTED)
    with contextlib.suppress(Exception):  # the static list is a safe fallback
        from linkit_all.sources import registry  # late: plugins import many modules

        for src in registry().values():
            if src.kind != "ats":
                continue
            blobs = [p.pattern.replace("\\", "") for p in src.url_patterns]
            blobs += [h.replace("*", "") for h in src.cdx_hosts]
            for blob in blobs:
                for m in _HOST_IN_PATTERN.finditer(blob.lower()):
                    roots.add(_root(m.group(1)))
    return frozenset(roots)


_COMPANY_NOISE = re.compile(
    r"\b(?:inc|llc|ltd|limited|co|corp|corporation|company|group|gmbh|plc|sa|ag|holdings?|the|international)\b"
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _COMPANY_NOISE.sub(" ", text.casefold()))


def _host(url: str) -> str:
    try:
        parts = urlsplit(url.strip() if "//" in url else f"//{url.strip()}")
        return (parts.hostname or "").lower()
    except ValueError:
        return ""


def _host_matches_company(host: str, company: str, hint: str | None) -> bool | None:
    """True/False, or None when there is nothing to compare against."""
    root = _root(host)
    if hint:
        hint_root = _root(_host(hint) or hint.lower())
        if root == hint_root:
            return True
    slug = _slug(company)
    if not slug and not hint:
        return None
    label = root.split(".")[0]
    names = {slug, *(_slug(w) for w in company.casefold().split())} if slug else set()
    for name in names:
        if len(name) >= 4 and (
            name in host.replace("-", "").replace(".", "") or (label in name and len(label) >= 4)
        ):
            return True
    return False


# ---- scanning ---------------------------------------------------------------------------------


def _snip(text: str) -> str:
    return " ".join(text.split())[:_EVIDENCE_MAX]


def _context(text: str, start: int, end: int) -> str:
    """The match with a little surrounding text, kept within the evidence limit."""
    room = min(24, max(0, _EVIDENCE_MAX - (end - start)))
    return _snip(text[max(0, start - room // 2) : end + room // 2])


def _mid_word(text: str, pos: int) -> bool:
    if not pos:
        return False
    prev, cur = text[pos - 1], text[pos]
    return prev.isascii() and prev.isalnum() and cur.isascii() and cur.isalnum()


def _first_hit(rule: _Rule, variants: list[str], clauses: list[Clauses]) -> str | None:
    for text, cl in zip(variants, clauses, strict=True):
        for m in rule.pattern.finditer(text):
            if _mid_word(text, m.start()):
                continue  # "preregistration fee" is not "registration fee"
            if rule.negatable and cl.negated(m.start()):
                continue
            if rule.needs_pivot and not _PIVOT_VERB.search(cl.clause(m.start())):
                continue
            return _context(text, m.start(), m.end())
    return None


def _num(amt: str, k: str | None) -> float:
    value = float(amt.replace(",", ""))
    return value * 1000 if k else value


def _weekly_amount(light_text: str, salary: Mapping[str, object] | None) -> float | None:
    """Largest weekly pay figure quoted in the text or in the structured salary, if any."""
    best: float | None = None
    quoted = "week" in light_text or "wk" in light_text or "اسبوع" in light_text
    for m in _WEEKLY.finditer(light_text) if quoted else ():
        if m.group("amt"):
            if not (m.group("sym") or m.group("cur")):
                continue  # "20 hours per week" is not a pay quote
            value = _num(m.group("amt"), m.group("k"))
        else:
            if not (m.group("sym2") or m.group("cur2")):
                continue
            value = _num(m.group("amt2"), m.group("k2"))
        best = value if best is None else max(best, value)
    if salary:
        interval = str(salary.get("interval") or salary.get("salary_interval") or "").lower()
        if interval in _WEEKLY_INTERVALS:
            vals = [
                v
                for v in (
                    salary.get("max", salary.get("salary_max")),
                    salary.get("min", salary.get("salary_min")),
                )
                if isinstance(v, int | float)
            ]
            if vals:
                top = float(max(vals))
                best = top if best is None else max(best, top)
    return best


def _band(score: int) -> str:
    return "low" if score < MEDIUM_FROM else "medium" if score < HIGH_FROM else "high"


def score_scam(
    title: str,
    company: str,
    description: str,
    apply_url: str | None,
    salary: SalaryLike | None,
    company_domain_hint: str | None = None,
) -> Verdict:
    """Score one posting 0-100 for scam likelihood, with the signals that explain the score."""
    raw = f"{title}\n{description}"[:_MAX_CHARS]
    scan = f"{raw}\n{apply_url}" if apply_url else raw
    light_text = light(scan)
    variants = list(fold_light(light_text))
    clauses = [Clauses(v) for v in variants]
    found: dict[str, Signal] = {}

    def add(code: str, weight: int, evidence: str) -> None:
        if code not in found:
            found[code] = Signal(code, weight, _snip(evidence))

    for rule in (*_RULES, *_CHAT_RULES):
        if rule.code in found:
            continue
        if (ev := _first_hit(rule, variants, clauses)) is not None:
            add(rule.code, rule.weight, ev)
    if (ev := _first_hit(_MLM_RULE, variants, clauses)) is not None:
        add(_MLM_RULE.code, _MLM_RULE.weight, ev)

    for text in variants:
        if (mail := _free_mail(text)) is not None:
            add("free_email_contact", 12, mail)
            break

    weekly = _weekly_amount(light_text, salary)
    if weekly is not None:
        junior = _JUNIOR_TITLE.search(light(title)) is not None
        if weekly >= _IMPLAUSIBLE_ANY or (junior and weekly >= _IMPLAUSIBLE_JUNIOR):
            add(
                "implausible_pay",
                30,
                f"{weekly:,.0f} per week" + (" (junior title)" if junior else ""),
            )
        else:
            add("weekly_pay", 12, f"{weekly:,.0f} per week")

    if not re.sub(r"[\W_]+", "", company or ""):
        add("company_missing", 14, "no company name")

    trusted = False
    if (
        apply_url
        and not apply_url.strip().lower().startswith("mailto:")
        and (host := _host(apply_url))
    ):
        root = _root(host)
        if root in _trusted_roots():
            trusted = True
        elif (
            root not in _KNOWN_BOARDS
            and root != "linkedin.com"  # a LinkedIn post links out by design
            and _host_matches_company(host, company or "", company_domain_hint) is False
        ):
            add("apply_domain_mismatch", 20, host)

    codes = set(found)
    positive = {c for c, s in found.items() if s.weight > 0}
    floor = 0
    reason = ""
    if codes & _HARD_FLOOR:
        floor, reason = 80, "money mule, crypto or credential request"
    if "buy_to_work" in codes and floor < 65:
        floor, reason = 65, "applicant must buy goods first"
    if "upfront_fee" in codes and positive - {"upfront_fee"} and floor < 65:
        floor, reason = 65, "upfront fee plus another scam signal"
    if codes & _OFF_PLATFORM and "no_interview" in codes and floor < 65:
        floor, reason = 65, "off-platform contact and no interview"

    if trusted and not floor:
        found["trusted_ats"] = Signal(
            "trusted_ats", TRUSTED_ATS_BONUS, _snip(_root(_host(apply_url or "")))
        )

    total = BASE_SCORE + sum(s.weight for s in found.values())
    if floor and total < floor:
        found["score_floor"] = Signal("score_floor", floor - total, reason)
        total = floor
    score = max(0, min(100, total))
    return Verdict(score=score, signals=tuple(found.values()), band=_band(score))
