"""matching/facts.py: blanks the posting fills (work mode, location, salary) are kept only when the
quote is in the posting and holds the value; a kept fact can only tighten the filter."""

import asyncio
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_matching import FakeAI, db, job  # noqa: F401

from linkit_all.core.models import Job, JobState, Tier
from linkit_all.core.search import SearchConfig
from linkit_all.matching.facts import JobFacts, checked, missing
from linkit_all.matching.reasons import job_reason
from linkit_all.matching.score import score_jobs

POSTING = (
    "We build payment APIs. This is a fully on-site role in our Berlin office. "
    "Salary: €40,000 - €50,000 per year. Not a remote position."
)
ONSITE = {"value": "onsite", "quote": "fully on-site role"}
BERLIN = {"value": "Berlin", "quote": "on-site role in our Berlin office"}
SALARY = {"min": 40000, "max": 50000, "currency": "EUR", "interval": "year",
          "quote": "€40,000 - €50,000 per year"}  # fmt: skip


def blank(**kw: Any) -> Job:
    return job(**{"location": "", "description": POSTING, **kw})


def test_checked_keeps_facts_the_quote_holds() -> None:
    facts = JobFacts.model_validate({"work_mode": ONSITE, "location": BERLIN, "salary": SALARY})
    got = checked(blank(), facts)
    assert got["work_mode"]["value"] == "onsite" and got["location"]["value"] == "Berlin"
    assert (got["salary"]["max"], got["salary"]["currency"]) == (50000, "EUR")


@pytest.mark.parametrize(
    ("field", "fact"),
    [
        ("work_mode", {"value": "onsite", "quote": "on-site role in Paris"}),  # not in posting
        ("work_mode", {"value": "remote", "quote": "Not a remote position"}),  # negated
        ("work_mode", {"value": "remote", "quote": "We build payment APIs"}),  # says nothing
        ("location", {"value": "Munich", "quote": "on-site role in our Berlin office"}),
        ("salary", {**SALARY, "max": 60000}),  # a number the quote does not hold
        ("salary", {**SALARY, "currency": "USD"}),  # a currency it does not name
        ("salary", {**SALARY, "interval": "month"}),
        ("salary", {**SALARY, "quote": "€40,000"}),  # too little to hold it all
    ],
)
def test_checked_drops_what_the_quote_does_not_hold(field: str, fact: dict[str, Any]) -> None:
    assert checked(blank(), JobFacts.model_validate({field: fact})) == {}


def test_only_blanks_are_filled() -> None:
    known = blank(location="Berlin, DE", data={"remote": "hybrid", "salary_max": 1})
    assert missing(known) == []
    facts = JobFacts.model_validate({"work_mode": ONSITE, "location": BERLIN, "salary": SALARY})
    assert checked(known, facts) == {}


def test_salary_number_forms() -> None:
    posting = "Pay 60k-75k USD per year, or 4.500 EUR a month for interns."
    j = job(location="", description=posting)
    ok = {"min": 60000, "max": 75000, "currency": "USD", "interval": "year",
          "quote": "60k-75k USD per year"}  # fmt: skip
    assert checked(j, JobFacts.model_validate({"salary": ok}))
    eu = {"max": 4500, "currency": "EUR", "interval": "month", "quote": "4.500 EUR a month"}
    assert checked(j, JobFacts.model_validate({"salary": eu}))


def test_a_checked_fact_that_breaks_a_rule_stops_the_job(db: sessionmaker[Session]) -> None:  # noqa: F811
    with db.begin() as s:
        s.add(blank(title="Backend Engineer", state=JobState.ranked, data={"rank": 0.9}))
        s.add(blank(title="Hand Pick", url="https://x/hand", state=JobState.ranked,
                    data={"rank": 0.8, "manual": True}))  # fmt: skip
    cfg = SearchConfig.model_validate(
        {"filters": {"work_modes": ["remote"]}, "matching": {"auto_apply_low": True}}
    )
    facts = {"facts": {"work_mode": ONSITE, "location": BERLIN}}
    ai = FakeAI({"Backend Engineer": 9, "Hand Pick": 9},
                extra={"Backend Engineer": facts, "Hand Pick": facts})  # fmt: skip
    asyncio.run(score_jobs(db, cfg, ai))
    assert "Missing facts: work_mode, location, salary" in ai.prompts[0]
    assert ai.prompts[0].count("Missing facts:") == 1  # none asked for the hand-added job
    asyncio.run(score_jobs(db, cfg, ai))  # the low opt-in requeue leaves it alone too
    with db() as s:
        jobs = {j.title: j for j in s.scalars(select(Job))}
    stopped = jobs["Backend Engineer"]
    assert (stopped.state, stopped.tier, stopped.location) == (
        JobState.below_threshold, Tier.low, "Berlin")  # fmt: skip
    assert stopped.data["remote"] == "onsite" and stopped.data["facts"]["work_mode"]
    reason = job_reason(stopped)
    assert reason is not None and reason[1] == "work_mode"
    assert jobs["Hand Pick"].state == JobState.queued_apply  # the user picked it: no hard rules
