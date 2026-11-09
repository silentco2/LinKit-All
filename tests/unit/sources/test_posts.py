# ruff: noqa: RUF001
"""Reading job posts by script: title, email, company, link, place."""

import pytest

from linkit_all.sources.posts import (
    PostRules,
    company_of,
    contact_email,
    find_links,
    heading,
    is_seeker,
    job_link,
)


@pytest.mark.parametrize(
    ("text", "title"),
    [
        ("Backend dev needed in Cairo, send your CV to hr@acme.com", "Backend dev needed in Cairo"),
        ("#вакансия #python\n🔥 Python-разработчик 🔥\nМосква", "Python-разработчик"),
        ("We are growing!\nPosition: Senior QA\nCairo", "Senior QA"),
        ("Должность: Аналитик данных", "Аналитик данных"),
        ("tl;dr: C++ dev at TON, remote worldwide", "C++ dev at TON, remote worldwide"),
        ("مطلوب مهندس برمجيات", "مهندس برمجيات"),
        ("C# developer", "C# developer"),
        ("Contact Center Agent\nCairo", "Contact Center Agent"),
        ("hr@acme.com", ""),
    ],
)
def test_heading(text: str, title: str) -> None:
    assert heading(text) == title


def test_heading_prefers_a_line_with_the_users_title_word() -> None:
    assert (
        heading("Acme is growing\nSenior Data Analyst\nCairo", ("analyst",))
        == "Senior Data Analyst"
    )


def test_contact_email_skips_the_channels_ad_contact() -> None:
    assert contact_email("По вопросам рекламы: ads@chan.ru\nРезюме: hr@acme.com") == "hr@acme.com"
    assert contact_email("Advertising: ads@chan.ru") == ""


@pytest.mark.parametrize(
    ("text", "email", "company"),
    [
        ("x", "hr@acme.com", "Acme"),
        ("x", "hr@jobs.acme.co.uk", "Acme"),
        ("x", "someone@gmail.com", "Unknown"),
        ("x", "", "Unknown"),
        ("Company: Vodafone Egypt\nx", "hr@acme.com", "Vodafone Egypt"),
    ],
)
def test_company_of(text: str, email: str, company: str) -> None:
    assert company_of(text, email) == company


def test_find_links_bare_domain_needs_a_path_and_a_real_tld() -> None:
    assert find_links("Apply at acme.com/careers/42.") == ("https://acme.com/careers/42",)
    assert find_links("Node.js/React and acme.com") == ()
    assert find_links("mail hr@acme.com/x") == ()


def test_job_link_skips_social_and_home_pages() -> None:
    links = ("https://t.me/chan", "https://acme.com/", "https://www.youtube.com/watch?v=1",
             "https://www.linkedin.com/in/sara", "https://acme.com/careers/42")  # fmt: skip
    assert job_link(links) == "https://acme.com/careers/42"
    assert job_link(("https://www.linkedin.com/jobs/view/7",)) != ""
    assert job_link(links[:4]) == ""


def test_place_matches_city_country_and_arabic() -> None:
    rules = PostRules(places=("cairo, egypt", "alexandria, egypt", "saudi arabia", "remote"))
    assert rules.place("Backend dev in Cairo") == "cairo, egypt"
    assert rules.place("Backend dev in Alexandria, Egypt") == "alexandria, egypt"
    assert rules.place("Job in Egypt") == "cairo, egypt"
    assert rules.place("مطلوب مهندس في القاهرة") == "cairo, egypt"
    assert rules.place("وظيفة في السعودية") == "saudi arabia"
    assert rules.place("Fully remote") == "remote"
    assert rules.place("Moscow office") == ""


def test_worth_reading_uses_the_users_filters() -> None:
    rules = PostRules(title_words=("python",), places=("cairo, egypt",))
    assert rules.worth_reading("Python dev in Cairo")
    assert not rules.worth_reading("Python dev in Moscow")
    assert not rules.worth_reading("Java dev in Cairo")
    assert PostRules().worth_reading("anything")


def test_seekers_in_russian() -> None:
    assert is_seeker("Ищу работу python разработчиком")
    assert not is_seeker("Ищем python разработчика")
