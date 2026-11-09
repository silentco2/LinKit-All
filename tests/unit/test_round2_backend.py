"""UX round 2 backend: home address, new sensitive answers, places, posted-within hours, one
browser setting, LinkedIn keywords, adding a source, and CV values filling empty fields."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_api import SAME_ORIGIN, client, mem_keyring  # noqa: F401
from test_infer_api import cv_bytes
from test_linkedin_google import cfg as linkedin_cfg

from linkit_all.apply.answers import (
    ApplicationAnswers,
    Context,
    Question,
    canonical_country,
    resolve_static,
    sensitive_category,
)
from linkit_all.core.infer import CvFacts, Experience, infer, international_phone
from linkit_all.core.models import Job
from linkit_all.core.profile import ProfileFields
from linkit_all.core.search import SearchConfig, load_search
from linkit_all.matching.reasons import filter_reason
from linkit_all.matching.rules import rule_violation
from linkit_all.sources import registry
from linkit_all.sources.base import Task
from linkit_all.sources.jobspy_sites import JobSpySite

# --- sensitive answers -----------------------------------------------------------------

MILITARY = Question(
    "m", "Military service status", "select", True,
    ["Completed", "Postponed", "Exempted", "Not applicable"],
)  # fmt: skip
MILITARY_AR = Question(
    "m", "الموقف من التجنيد", "select", True, ["أدى الخدمة", "مؤجل", "معفى", "لا ينطبق"]
)
NATIONALITY = Question("n", "Nationality", "select", True, ["Egyptian", "Saudi", "Other"])
DOB = Question("d", "Date of birth", "date", True)
DOB_TEXT = Question("d2", "Date of birth (DD/MM/YYYY)", "text", True)
AGE = Question("a", "What is your age?", "number", True)
MARITAL = Question(
    "s", "Marital status", "select", True, ["Single", "Married", "Divorced", "Widowed"]
)


def ctx(job_location: str = "Cairo, Egypt", **answers: Any) -> Context:
    return Context(
        full_name="Jane Doe", email="j@x.io", phone="+20100", location="Cairo",
        answers=ApplicationAnswers(**answers), job_location=job_location,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("label", "category"),
    [
        ("Military service status", "military_status"),
        ("Military status", "military_status"),
        ("Military service situation", "military_status"),
        ("Military service", "military_status"),
        ("الموقف من التجنيد", "military_status"),
        ("الخدمة العسكرية", "military_status"),
        ("Are you a protected veteran?", "eeo_veteran"),
        ("Have you served in the military?", "eeo_veteran"),
        ("Nationality", "nationality"),
        ("الجنسية", "nationality"),
        ("Date of birth", "date_of_birth"),
        ("DOB", "date_of_birth"),
        ("تاريخ الميلاد", "date_of_birth"),
        ("How old are you?", "date_of_birth"),
        ("Marital status", "marital_status"),
        ("الحالة الاجتماعية", "marital_status"),
        ("Pronouns", "eeo_other"),
        # these still belong to authorization, not to nationality
        ("Are you authorized to work in the country of your citizenship?", "work_authorization"),
    ],
)
def test_new_sensitive_categories(label: str, category: str) -> None:
    assert sensitive_category(Question("q", label, "text")) == category


def test_egyptian_military_question_is_not_a_veteran_answer() -> None:
    # A saved US veteran answer must not leak into "Military service status".
    r = resolve_static([MILITARY], ctx(eeo_veteran="not_veteran"))
    assert r.answers == {} and [m.question.key for m in r.missing] == ["m"]
    assert r.missing[0].sensitive and not r.pending  # never reaches the AI
    r = resolve_static([MILITARY], ctx(military_status="postponed"))
    assert r.answers == {"m": "Postponed"}


@pytest.mark.parametrize(
    ("question", "status", "expected"),
    [
        (MILITARY, "completed", "Completed"),
        (MILITARY, "exempted", "Exempted"),
        (MILITARY, "not_applicable", "Not applicable"),
        (MILITARY_AR, "completed", "أدى الخدمة"),
        (MILITARY_AR, "postponed", "مؤجل"),
        (MILITARY_AR, "exempted", "معفى"),
        (MILITARY_AR, "not_applicable", "لا ينطبق"),
    ],
)
def test_military_status_picks_the_matching_option(
    question: Question, status: str, expected: str
) -> None:
    assert resolve_static([question], ctx(military_status=status)).answers == {"m": expected}


def test_military_status_decline_and_text_field() -> None:
    q = Question("m", "Military status", "select", True, ["Completed", "Prefer not to say"])
    assert resolve_static([q], ctx(military_status="decline")).answers == {"m": "Prefer not to say"}
    text = Question("m", "Military status", "text", True)
    assert resolve_static([text], ctx(military_status="exempted")).answers == {"m": "Exempted"}


def test_military_option_that_does_not_exist_is_asked() -> None:
    q = Question("m", "Military status", "select", True, ["Veteran", "Not a veteran"])
    r = resolve_static([q], ctx(military_status="completed"))
    assert r.answers == {} and r.missing[0].sensitive


def test_nationality_from_the_profile_only() -> None:
    assert resolve_static([NATIONALITY], ctx()).missing[0].sensitive
    assert resolve_static([NATIONALITY], ctx(nationality="Egypt")).answers == {"n": "Egyptian"}
    assert resolve_static([NATIONALITY], ctx(nationality="EG")).answers == {"n": "Egyptian"}
    text = Question("n", "Nationality", "text", True)
    assert resolve_static([text], ctx(nationality="EG")).answers == {"n": "Egypt"}
    nothing = ctx(nationality="Japan")  # no matching option: ask, never guess
    assert resolve_static([NATIONALITY], nothing).answers == {}


def test_date_of_birth_and_age() -> None:
    r = resolve_static([DOB, DOB_TEXT, AGE], ctx(date_of_birth="1995-03-07"))
    assert r.answers == {"d": "1995-03-07", "d2": "1995-03-07"}  # as stored
    assert [m.question.key for m in r.missing] == ["a"]  # an age question is always asked
    assert [m.question.key for m in resolve_static([DOB], ctx()).missing] == ["d"]
    with pytest.raises(ValueError, match="date"):
        ApplicationAnswers(date_of_birth="07/03/1995")


def test_marital_status() -> None:
    assert resolve_static([MARITAL], ctx(marital_status="married")).answers == {"s": "Married"}
    assert resolve_static([MARITAL], ctx()).missing[0].sensitive
    q = Question("s", "الحالة الاجتماعية", "select", True, ["أعزب", "متزوج", "مطلق"])
    assert resolve_static([q], ctx(marital_status="single")).answers == {"s": "أعزب"}


WHERE = "in the country where the job is located"
AUTH = Question("a", f"Are you legally authorized to work {WHERE}?", "yesno", True, ["Yes", "No"])
SPONSOR = Question("p", f"Will you require visa sponsorship {WHERE}?", "yesno", True, ["Yes", "No"])


@pytest.mark.parametrize(
    ("job", "needs", "authorized", "visa", "sponsor", "auth"),
    [
        ("Cairo, Egypt", None, ["EG"], ["AE"], "No", "Yes"),
        ("Dubai", None, ["EG"], ["AE"], "Yes", "No"),
        ("Dubai", None, ["EG"], [], None, None),  # unknown country: ask
        ("Remote", None, ["EG"], ["AE"], None, None),
        ("Dubai", False, ["EG"], ["AE"], "No", "No"),  # explicit need wins
        ("Dubai", True, ["EG"], [], "Yes", None),
        ("Cairo, Egypt", True, ["EG"], [], "No", "Yes"),  # authorized there: no sponsorship
        ("Paris, France", None, ["EG"], ["FR"], "Yes", "No"),  # ISO2 outside the old table
    ],
)
def test_sponsorship_and_authorization_use_places(
    job: str,
    needs: bool | None,
    authorized: list[str],
    visa: list[str],
    sponsor: str | None,
    auth: str | None,
) -> None:
    c = ctx(job, authorized_countries=authorized, visa_countries=visa, needs_sponsorship=needs)
    r = resolve_static([AUTH, SPONSOR], c)
    assert r.answers.get("p") == sponsor
    assert r.answers.get("a") == auth


def test_canonical_country_knows_iso2_codes() -> None:
    assert [canonical_country(x) for x in ("FR", "eg", "Cairo, Egypt", "Narnia")] == [
        "france", "egypt", "egypt", "narnia",
    ]  # fmt: skip


# --- profile ---------------------------------------------------------------------------


def test_home_address_derives_location_and_phone_is_international() -> None:
    p = ProfileFields(home_city="Cairo", home_country="eg", phone="+20 (100) 123-4567")
    assert (p.location, p.home_country, p.phone) == ("Cairo, Egypt", "EG", "+201001234567")
    assert ProfileFields(home_country="SA").location == "Saudi Arabia"
    assert ProfileFields(location="Anywhere", phone="0100 123").location == "Anywhere"
    assert ProfileFields(phone="0100 123").phone == "0100 123"  # no plus: kept as typed
    with pytest.raises(ValueError, match="2-letter"):
        ProfileFields(home_country="Egypt")


def test_profile_api_round_trip_and_locked_facts_survive(client: TestClient) -> None:  # noqa: F811
    body = {"full_name": "A B", "email": "a@b.co", "address": "1 Nile St", "postal_code": "11511",
            "home_city": "Giza", "home_country": "eg", "locked_facts": ["Acme Corp"]}  # fmt: skip
    got = client.put("/api/profile", json=body, headers=SAME_ORIGIN).json()
    assert (got["location"], got["address"], got["postal_code"]) == (
        "Giza, Egypt",
        "1 Nile St",
        "11511",
    )
    assert got["locked_facts"] == ["Acme Corp"]
    again = client.put(
        "/api/profile", json={"full_name": "A B", "email": "a@b.co"}, headers=SAME_ORIGIN
    )
    assert again.json()["locked_facts"] == ["Acme Corp"]  # the UI no longer sends them


# --- places ----------------------------------------------------------------------------


def save_profile(client: TestClient, **extra: Any) -> None:  # noqa: F811
    body = {"full_name": "A B", "email": "a@b.co", **extra}
    assert client.put("/api/profile", json=body, headers=SAME_ORIGIN).status_code == 200


def test_places_derive_filters_and_answers(client: TestClient) -> None:  # noqa: F811
    save_profile(client, home_country="EG", home_city="Cairo")
    places = [
        {"label": "Cairo, Egypt", "city": "Cairo", "country": "EG", "work": "allowed"},
        {"label": "Dubai", "city": "Dubai", "country": "ae", "work": "visa"},
    ]
    modes = ["hybrid", "onsite"]
    body = {
        "search": {"places": places, "remote": True, "locations": ["junk"]},
        "filters": {"work_modes": modes},
    }
    got = client.put("/api/search", json=body, headers=SAME_ORIGIN).json()
    assert got["search"]["locations"] == ["Cairo, Egypt", "Dubai"]
    assert got["filters"]["locations"] == ["cairo, egypt", "dubai"]
    assert got["filters"]["work_modes"] == modes and got["search"]["remote"] is False
    assert got["sources"]["jobspy_country"] == "egypt"
    answers = client.get("/api/profile/answers").json()
    assert answers["authorized_countries"] == ["EG"] and answers["visa_countries"] == ["AE"]
    assert answers["willing_to_relocate"] is True  # Dubai is outside Egypt

    body = {"search": {"places": places[:1]}, "filters": {"work_modes": ["remote"]}}
    got = client.put("/api/search", json=body, headers=SAME_ORIGIN).json()
    assert got["search"]["locations"] == ["Cairo, Egypt", "Remote"]
    assert got["filters"]["work_modes"] == ["remote"] and got["search"]["remote"] is True
    answers = client.get("/api/profile/answers").json()
    assert answers["visa_countries"] == [] and answers["willing_to_relocate"] is True  # kept

    cleared = client.put("/api/search", json={"search": {"places": []}}, headers=SAME_ORIGIN).json()
    assert cleared["search"]["locations"] == [""] and cleared["filters"]["locations"] == []
    assert client.get("/api/profile/answers").json()["authorized_countries"] == []


def test_relocation_stays_unset_when_all_places_are_home(client: TestClient) -> None:  # noqa: F811
    save_profile(client, home_country="EG")
    place = {"label": "Cairo", "country": "EG", "work": "allowed"}
    client.put("/api/search", json={"search": {"places": [place]}}, headers=SAME_ORIGIN)
    assert client.get("/api/profile/answers").json()["willing_to_relocate"] is None


def test_old_locations_show_as_places_without_saving(client: TestClient) -> None:  # noqa: F811
    save_profile(client, home_country="EG")
    old = {"search": {"locations": ["Cairo, Egypt", "Dubai", "Remote"]}}
    client.put("/api/search", json=old, headers=SAME_ORIGIN)
    got = client.get("/api/search").json()["search"]
    assert [(p["label"], p["country"], p["work"]) for p in got["places"]] == [
        ("Cairo, Egypt", "EG", "ask"),
        ("Dubai", "AE", "ask"),
    ]
    assert got["locations"] == ["Cairo, Egypt", "Dubai", "Remote"]
    saved = load_search(client.app.state.db)  # type: ignore[attr-defined]
    assert saved is not None and saved.search.places == []  # nothing was written
    assert client.get("/api/profile/answers").json()["authorized_countries"] == []


def test_saving_synthesized_places_writes_no_work_rights(client: TestClient) -> None:  # noqa: F811
    save_profile(client, home_country="EG")
    client.put(
        "/api/search",
        json={"search": {"locations": ["Cairo, Egypt", "Dubai"]}},
        headers=SAME_ORIGIN,
    )
    shown = client.get("/api/search").json()
    assert {p["work"] for p in shown["search"]["places"]} == {"ask"}
    got = client.put(
        "/api/search", json=shown, headers=SAME_ORIGIN
    ).json()  # any later edit saves them
    assert [p["work"] for p in got["search"]["places"]] == ["ask", "ask"]
    answers = client.get("/api/profile/answers").json()
    assert answers["authorized_countries"] == [] and answers["visa_countries"] == []
    assert answers["willing_to_relocate"] is None


def test_only_explicit_places_change_the_country_lists(client: TestClient) -> None:  # noqa: F811
    save_profile(client, home_country="EG")
    answers = client.get("/api/profile/answers").json() | {
        "authorized_countries": ["Germany", "EG"]
    }
    assert client.put("/api/profile/answers", json=answers, headers=SAME_ORIGIN).status_code == 200

    def put(places: list[dict[str, str]]) -> dict[str, Any]:
        body = {"search": {"places": places}}
        client.put("/api/search", json=body, headers=SAME_ORIGIN)
        return client.get("/api/profile/answers").json()  # type: ignore[no-any-return]

    ask = [{"label": "Cairo", "country": "EG"}, {"label": "Dubai", "country": "AE"}]
    got = put(ask)  # unanswered places add nothing and remove nothing
    assert got["authorized_countries"] == ["Germany", "EG"] and got["visa_countries"] == []
    got = put([{**ask[0], "work": "visa"}, {**ask[1], "work": "allowed"}])
    assert got["authorized_countries"] == ["Germany", "AE"] and got["visa_countries"] == ["EG"]
    got = put([{**ask[0], "work": "visa"}, ask[1]])  # Dubai back to unanswered: taken off again
    assert got["authorized_countries"] == ["Germany"] and got["visa_countries"] == ["EG"]
    got = put([])  # clearing keeps what no place ever decided
    assert got["authorized_countries"] == ["Germany"] and got["visa_countries"] == []


def test_work_right_is_per_country(client: TestClient) -> None:  # noqa: F811
    save_profile(client, home_country="EG")

    def put(*rows: tuple[str, str, str]) -> list[str]:
        places = [{"label": lab, "country": c, "work": w} for lab, c, w in rows]
        got = client.put("/api/search", json={"search": {"places": places}}, headers=SAME_ORIGIN)
        return [p["work"] for p in got.json()["search"]["places"]]

    # an answered row spreads to the "ask" rows of its country, never to another country
    assert put(("Saudi Arabia", "SA", "visa"), ("Riyadh", "SA", "ask"), ("Dubai", "AE", "ask")) == [
        "visa", "visa", "ask",
    ]  # fmt: skip
    answers = client.get("/api/profile/answers").json()
    assert answers["visa_countries"] == ["SA"] and answers["authorized_countries"] == []
    # explicit rows that disagree: the last one wins for the whole country
    assert put(("Riyadh", "SA", "allowed"), ("Jeddah", "SA", "visa")) == ["visa", "visa"]
    # nothing stated for a country: nothing is assumed
    assert put(("Riyadh", "SA", "ask"), ("Jeddah", "SA", "ask")) == ["ask", "ask"]
    answers = client.get("/api/profile/answers").json()
    assert answers["visa_countries"] == [] and answers["authorized_countries"] == []


def test_place_needs_label_and_iso2() -> None:
    with pytest.raises(ValueError, match="label"):
        SearchConfig.model_validate({"search": {"places": [{"label": " ", "work": "allowed"}]}})
    with pytest.raises(ValueError, match="2-letter"):
        SearchConfig.model_validate(
            {"search": {"places": [{"label": "x", "country": "Egypt", "work": "visa"}]}}
        )


# --- posted within ---------------------------------------------------------------------

NOW = datetime(2026, 10, 31, 12)
JOB = {"source": "x", "title": "Dev", "company": "Acme", "location": "Cairo", "dedupe_hash": "h",
       "data": {}}  # fmt: skip


def test_days_become_hours_and_hours_win() -> None:
    assert (
        SearchConfig.model_validate(
            {"search": {"posted_within_days": 3}}
        ).search.posted_within_hours
        == 72
    )
    both = {"search": {"posted_within_days": 3, "posted_within_hours": 6}}
    assert SearchConfig.model_validate(both).search.posted_within_hours == 6
    s = SearchConfig.model_validate({"search": {"posted_within_hours": 30}}).search
    assert s.posted_within_days == 2  # whole days, rounded up, for day-based sources
    assert SearchConfig().search.posted_within_hours == 336
    anytime = SearchConfig.model_validate({"search": {"posted_within_hours": None}}).search
    assert anytime.posted_within_hours is None and anytime.posted_within_days > 365
    assert "posted_within_days" not in SearchConfig().model_dump()["search"]


def test_too_old_rule_uses_hours() -> None:
    cfg = SearchConfig.model_validate({"search": {"posted_within_hours": 6}})
    fresh = Job(**JOB, posted_at=NOW - timedelta(hours=5))
    stale = Job(**JOB, posted_at=NOW - timedelta(hours=7))
    assert rule_violation(fresh, cfg, NOW) is None
    assert rule_violation(stale, cfg, NOW) == "posted more than 6 hours ago"
    anytime = SearchConfig.model_validate({"search": {"posted_within_hours": None}})
    assert rule_violation(Job(**JOB, posted_at=NOW - timedelta(days=900)), anytime, NOW) is None


def test_too_old_reason_has_hours() -> None:
    row = Job(**JOB, posted_at=NOW - timedelta(days=2))
    got = filter_reason(row, ("posted more than 36 hours ago", None, {}), NOW)
    assert got == ("Posted 2 days ago", "too_old", {"limit": 2, "hours": 36, "days": 2})
    old = filter_reason(Job(**JOB), ("posted more than 14 days ago", None, {}), NOW)
    assert old == ("Posted more than 14 days ago", "too_old", {"limit": 14, "hours": 336})


def test_jobspy_gets_hours_old() -> None:
    seen: list[dict[str, Any]] = []

    def fake(**kw: Any) -> list[dict[str, Any]]:
        seen.append(kw)
        return []

    class _Http: ...

    site = JobSpySite("indeed", fake)
    for hours, want in ((6, 6), (None, None)):
        cfg = SearchConfig.model_validate(
            {
                "search": {"queries": ["python"], "posted_within_hours": hours},
                "sources": {"jobspy": ["indeed"]},
            }
        )
        task = site.tasks(cfg)[0]
        assert isinstance(task, Task)

        async def run(t: Task = task) -> None:
            async for _ in site.search(_Http(), t, 0):  # type: ignore[arg-type]
                pass

        asyncio.run(run())
        assert seen[-1]["hours_old"] == want


# --- browser window, LinkedIn keywords --------------------------------------------------


def test_linkedin_uses_the_one_headless_setting_and_search_queries(tmp_path: Path) -> None:
    src = registry(data_dir=tmp_path)["linkedin_posts"]
    base = linkedin_cfg(linkedin_keywords=[], linkedin_headless=False)
    base.search.queries = ["python dev", "data analyst"]
    assert [t.query for t in src.tasks(base)] == ["python dev", "data analyst"]
    assert src._headless is False  # type: ignore[attr-defined]  # apply.headless default
    base.apply.headless = True
    src.tasks(base)
    assert src._headless is True  # type: ignore[attr-defined]
    old = linkedin_cfg(linkedin_keywords=["mine"])  # saved by older versions: ignored
    old.search.queries = ["python dev"]
    assert [t.query for t in src.tasks(old)] == ["python dev"]


# --- adding a source -------------------------------------------------------------------


def add(client: TestClient, value: str) -> Any:  # noqa: F811
    return client.post("/api/sources/add", json={"value": value}, headers=SAME_ORIGIN)


def test_add_telegram_channel(client: TestClient) -> None:  # noqa: F811
    r = add(client, "https://t.me/s/My_Jobs_Channel/12")
    assert r.status_code == 200
    body = r.json()
    assert (body["kind"], body["label"]) == ("telegram", "@My_Jobs_Channel")
    saved = client.get("/api/search").json()["sources"]
    assert saved["telegram_channels"][-1] == "My_Jobs_Channel" and "telegram" in saved["enabled"]
    assert body["config"]["telegram_channels"] == saved["telegram_channels"]
    assert add(client, "@my_jobs_channel").status_code == 422  # duplicate, any case
    assert add(client, "@ab").status_code == 422


def test_add_careers_and_ats_pages(client: TestClient) -> None:  # noqa: F811
    ats = add(client, "https://boards.greenhouse.io/stripe").json()
    assert (ats["kind"], ats["label"]) == ("ats", "Stripe · Greenhouse")
    shorthand = add(client, "lever:acme").json()
    assert (shorthand["kind"], shorthand["label"]) == ("ats", "Acme · Lever")
    careers = add(client, "careers.example.com/jobs").json()
    assert (careers["kind"], careers["label"]) == ("careers", "example.com · careers page")
    saved = client.get("/api/search").json()["sources"]["companies"]
    assert saved == [
        "https://boards.greenhouse.io/stripe", "lever:acme", "https://careers.example.com/jobs",
    ]  # fmt: skip
    assert add(client, "https://boards.greenhouse.io/stripe/").status_code == 422
    for garbage in ("hello", "", "  ", "two words.com", "me@x.com", "localhost:8080"):
        assert add(client, garbage).status_code == 422, garbage


# --- CV fills empty fields ------------------------------------------------------------


def upload(client: TestClient, tmp_path: Path) -> Any:  # noqa: F811
    r = client.post("/api/profile/cv", params={"filename": "sara.docx"},
                    content=cv_bytes(tmp_path), headers=SAME_ORIGIN)  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_fills_empty_non_sensitive_fields(client: TestClient, tmp_path: Path) -> None:  # noqa: F811
    out = upload(client, tmp_path)
    assert "profile.full_name" in out["filled"] and "answers.current_company" in out["filled"]
    p = client.get("/api/profile").json()
    assert (p["full_name"], p["email"]) == ("Sara Ahmed", "sara.ahmed@example.com")
    assert (p["home_city"], p["home_country"], p["location"]) == ("Cairo", "EG", "Cairo, Egypt")
    assert p["phone"] == "+201001234567" and "Python" in p["skills"]
    assert {"Acme Corp", "Backend Engineer"} <= set(p["locked_facts"])  # silent protection
    a = client.get("/api/profile/answers").json()
    assert a["current_company"] == "Acme Corp"
    assert a["linkedin"].endswith("sara-ahmed") and a["years_experience"] >= 5
    for sensitive in (
        "authorized_countries",
        "needs_sponsorship",
        "nationality",
        "date_of_birth",
        "military_status",
        "marital_status",
        "visa_countries",
        "salary_expectation",
    ):
        assert a[sensitive] in (None, "", [])  # fmt: skip


def test_upload_never_overwrites_a_value(client: TestClient, tmp_path: Path) -> None:  # noqa: F811
    save_profile(client, full_name="Keep Me", home_country="SA", locked_facts=["Mine"])
    client.put("/api/profile/answers", json={"current_company": "Mine Inc"}, headers=SAME_ORIGIN)
    upload(client, tmp_path)
    p = client.get("/api/profile").json()
    assert (p["full_name"], p["home_country"]) == ("Keep Me", "SA")
    assert p["email"] == "a@b.co" and p["home_city"] == "Cairo"  # only the empty ones filled
    assert p["locked_facts"][0] == "Mine" and "Acme Corp" in p["locked_facts"]
    assert client.get("/api/profile/answers").json()["current_company"] == "Mine Inc"


# --- infer: home place and international phone -------------------------------------------


def test_infer_home_city_country_and_phone() -> None:
    facts = CvFacts(full_name="Sara Ahmed", location="Cairo, Egypt", phone="01001234567",
                    experiences=[Experience(title="Dev", company="Acme", current=True)])  # fmt: skip
    v = infer(facts, datetime(2026, 10, 31).date())
    assert [v[k].value for k in ("profile.home_city", "profile.home_country", "profile.phone")] == [
        "Cairo", "EG", "+201001234567",
    ]  # fmt: skip
    from_phone = infer(CvFacts(phone="+966501234567"), datetime(2026, 1, 1).date())
    assert from_phone["profile.home_country"].value == "SA"
    assert from_phone["profile.home_country"].check and "profile.home_city" not in from_phone
    country_only = infer(CvFacts(location="Egypt"), datetime(2026, 1, 1).date())
    assert "profile.home_city" not in country_only


def test_international_phone() -> None:
    assert international_phone("+20 100 123 4567") == "+201001234567"
    assert international_phone("0020 100 123 4567") == "+201001234567"
    assert international_phone("0100 123 4567", "EG") == "+201001234567"
    assert international_phone("0100 123 4567") == "01001234567"  # no country: digits only
    assert international_phone("") == ""


# --- home address fills forms ----------------------------------------------------------


def home(**kw: Any) -> Context:
    c = ctx(**kw.pop("answers", {}))
    c.address, c.postal_code, c.home_city, c.home_country = (
        "1 Nile St",
        "11511",
        "Giza",
        kw.pop("country", "EG"),
    )
    return c


@pytest.mark.parametrize(
    ("label", "name", "expected"),
    [
        ("Street address", "", "1 Nile St"),
        ("Address Line 1", "", "1 Nile St"),
        ("Address", "address1", "1 Nile St"),
        ("العنوان", "", "1 Nile St"),
        ("ZIP / Postal code", "", "11511"),
        ("Postcode", "", "11511"),
        ("Zip", "zipcode", "11511"),
        ("الرمز البريدي", "", "11511"),
        ("City", "", "Giza"),
        ("Country", "", "Egypt"),
    ],
)
def test_home_fields_fill_standard_questions(label: str, name: str, expected: str) -> None:
    q = Question("q", label, "text", True, name=name)
    assert resolve_static([q], home()).answers == {"q": expected}


def test_address_line_two_and_email_address_are_not_the_address() -> None:
    line2 = Question("q", "Address Line 2", "text", False)
    mail = Question("e", "Email address", "email", True)
    r = resolve_static([line2, mail], home())
    assert r.answers == {"e": "j@x.io"} and [x.key for x in r.pending] == ["q"]


def test_country_is_a_name_fitted_to_options_with_fallbacks() -> None:
    q = Question("q", "Country", "select", True, ["Egypt", "France", "United States"])
    assert resolve_static([q], home()).answers == {"q": "Egypt"}
    fr = Question("q", "Country", "select", True, ["Egypt", "France"])
    assert resolve_static([fr], home(country="FR")).answers == {"q": "France"}
    # no home country: answers.country, then the location text
    c = ctx(country="Qatar")
    assert resolve_static([Question("q", "Country", "text", True)], c).answers == {"q": "Qatar"}
    assert resolve_static([Question("q", "Country", "text", True)], ctx()).pending == []
    c = ctx()
    c.location = "Cairo, Egypt"
    assert resolve_static([Question("q", "Country", "text", True)], c).answers == {"q": "Egypt"}


def test_home_city_beats_answers_city_and_empty_home_falls_back() -> None:
    q = Question("q", "City", "text", True)
    assert resolve_static([q], home(answers={"city": "Elsewhere"})).answers == {"q": "Giza"}
    assert resolve_static([q], ctx(city="Elsewhere")).answers == {"q": "Elsewhere"}
    assert resolve_static([q], ctx()).answers == {"q": "Cairo"}  # the old location fallback
    empty = Question("q", "Postal code", "text", False)
    assert resolve_static([empty], ctx()).answers == {}  # no value: never invented here
