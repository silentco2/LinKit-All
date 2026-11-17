"""Closed-posting wording (sources/liveness.py, A6)."""

import pytest

from linkit_all.sources.liveness import closed_text, workday_listing


@pytest.mark.parametrize(
    "text",
    [
        "404 - Page not found",
        "This job is no longer accepting applications.",
        "Sorry, this position has been filled.",
        "The job you are trying to apply for has been filled",
        "This posting has expired.",
        "Applications are now closed for this role.",
        f"Cette offre n{chr(0x2019)}est plus disponible.",  # typographic apostrophe
        "Le poste a été pourvu",
        "Diese Stelle ist nicht mehr verfügbar",
        "Die Stelle ist bereits besetzt.",
        "Esta oferta ya no está disponible",
        "هذه الوظيفة لم تعد متاحة",
    ],
)
def test_closed_wording_matches(text: str) -> None:
    assert closed_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "Your application form has been filled out, please review it.",
        "Make sure every field is filled out before you submit.",
        "We are hiring! Apply now for this open position.",
        "Senior Engineer - Berlin - Full time",
        "",
    ],
)
def test_open_pages_do_not_match(text: str) -> None:
    assert not closed_text(text)


def test_workday_apply_link_falls_back_to_the_listing() -> None:
    url = "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Berlin/Engineer_R123/apply?utm_source=li"
    assert (
        workday_listing(url)
        == "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Berlin/Engineer_R123"
    )
    assert workday_listing(url.split("?")[0] + "/applyManually") == (
        "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Berlin/Engineer_R123"
    )
    assert workday_listing("https://acme.wd5.myworkdayjobs.com/External/job/X_R1") is None
    assert workday_listing("https://boards.greenhouse.io/acme/jobs/1/apply") is None
