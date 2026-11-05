"""The salary rule across currencies: one monthly expectation, opt-in skip, FX conversion."""

import json
from pathlib import Path
from typing import Any

import pytest

from linkit_all.core import fx
from linkit_all.core.config import Settings
from linkit_all.core.models import Job, utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.matching.reasons import filter_reason
from linkit_all.matching.rules import expectation_of, rule_violation


@pytest.fixture(autouse=True)
def fixed_rates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """1 USD = 50 EGP = 0.5 EUR, newer than the shipped table, so results do not drift."""
    table = {"base": "USD", "date": "2999-01-01", "rates": {"USD": 1, "EGP": 50, "EUR": 0.5}}
    (tmp_path / "fx.json").write_text(json.dumps(table))
    monkeypatch.setattr(fx, "get_settings", lambda: Settings(data_dir=tmp_path))


def cfg(**filters: Any) -> SearchConfig:
    return SearchConfig.model_validate({"filters": {"salary_currency": "EGP", **filters}})


def check(
    c: SearchConfig, expect: tuple[float, str] | None = (60000, "EGP"), **data: Any
) -> str | None:
    job = Job(source="t", url="https://x/1", title="Backend Engineer", company="Acme",
              location="Cairo", description="", dedupe_hash="h", data=data)  # fmt: skip
    return rule_violation(job, c, utcnow(), expect)


YEARLY_USD = {
    "salary_max": 12000,
    "salary_interval": "year",
    "salary_currency": "USD",
}  # 50,000 EGP/mo


def test_yearly_usd_posting_below_a_monthly_egp_expectation_is_skipped() -> None:
    reason = check(cfg(skip_below_expectation=True), **YEARLY_USD)
    assert reason == "salary up to 50,000 EGP/month is below your floor"
    assert (
        filter_reason(Job(title="t", company="c", location=""), (reason or "", None, {}))[1]
        == "salary"
    )


def test_expectation_met_passes() -> None:
    assert check(cfg(skip_below_expectation=True), (40000, "EGP"), **YEARLY_USD) is None
    assert check(cfg(skip_below_expectation=True), (50000, "EGP"), **YEARLY_USD) is None


def test_expectation_in_another_currency() -> None:
    eur = {"salary_max": 1200, "salary_interval": "year", "salary_currency": "EGP"}  # 1 EUR/mo
    assert check(cfg(skip_below_expectation=True), (2, "EUR"), **eur) is not None
    assert check(cfg(skip_below_expectation=True), (1, "EUR"), **eur) is None


def test_off_by_default() -> None:
    assert check(cfg(), **YEARLY_USD) is None


def test_explicit_floor_wins_over_the_expectation() -> None:
    c = cfg(skip_below_expectation=True, salary_floor_monthly=30000)
    assert check(c, **YEARLY_USD) is None  # 50,000 clears 30,000; the 60,000 expectation is ignored
    assert check(cfg(salary_floor_monthly=80000), **YEARLY_USD) is not None  # floor works alone too


def test_unconvertible_or_unstated_pay_is_never_filtered() -> None:
    c = cfg(skip_below_expectation=True)
    assert check(c, salary_max=1, salary_interval="month", salary_currency="XYZ") is None
    assert check(c, salary_max=1, salary_interval="month") is None  # no currency
    assert check(c, salary_interval="month", salary_currency="EGP") is None  # no amount
    assert check(c, None, **YEARLY_USD) is None  # no expectation saved


def test_same_currency_and_pay_periods() -> None:
    c = cfg(skip_below_expectation=True)
    assert "10,000 EGP/month" in (
        check(c, salary_max=10000, salary_interval="month", salary_currency="EGP") or ""
    )
    assert (
        check(c, salary_max=50, salary_interval="hour", salary_currency="EGP") is not None
    )  # 8,800
    assert check(c, salary_max=70000, salary_interval="month", salary_currency="egp") is None


def test_expectation_of_answers() -> None:
    c = cfg()
    assert expectation_of({"salary_expectation": "30,000", "salary_currency": "usd"}, c) == (
        30000,
        "USD",
    )
    assert expectation_of({"salary_expectation": "30k"}, c) == (30000, "EGP")  # filter currency
    assert expectation_of({"salary_expectation": "EGP 12500.5/month"}, c) == (12500.5, "EGP")
    assert expectation_of({"salary_expectation": ""}, c) is None
    assert expectation_of({"salary_expectation": "negotiable"}, c) is None
    assert expectation_of({}, c) is None
