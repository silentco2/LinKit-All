"""Apply routing: ban-risk hosts and the model's Apply/Dismiss choices (CLAUDE.md §5.5)."""

from pathlib import Path

from linkit_all.apply.agent import Control, FieldMap, clean_map
from linkit_all.apply.runner import assisted

HOSTS = ["linkedin.com", "indeed.com", "glassdoor.com"]


def test_ban_risk_sites_match_on_any_country_domain() -> None:
    for url in (
        "https://www.linkedin.com/jobs/view/1",
        "https://eg.linkedin.com/jobs/view/1",
        "https://uk.indeed.com/viewjob?jk=1",
        "https://www.glassdoor.co.uk/job-listing/j?jl=1",
    ):
        assert assisted(url, HOSTS), url
    for url in ("https://boards.greenhouse.io/acme/jobs/1", "https://linkedinjobs.example", None):
        assert not assisted(url, HOSTS), url


def test_apply_may_be_a_link_dismiss_must_be_another_button() -> None:
    controls = [
        Control("a0", "link", "Apply now", href="https://acme.test/apply"),
        Control("a1", "button", "Close"),
        Control("a2", "text", "Search jobs"),
    ]
    got = clean_map(
        FieldMap(page_kind="listing", apply_button="a0", dismiss_button="a1", fields=[]), controls
    )
    assert (got.apply_button, got.dismiss_button) == ("a0", "a1")
    bad = clean_map(FieldMap(page_kind="listing", apply_button="a2", dismiss_button="a0"), controls)
    assert (bad.apply_button, bad.dismiss_button) == (None, None)  # a text box, a link


def test_linkedin_public_page_says_easy_apply_or_employer_site() -> None:
    from pathlib import Path

    from linkit_all.sources.jobspy_sites import linkedin_apply

    pages = Path(__file__).parents[1] / "fixtures" / "linkedin"
    assert linkedin_apply((pages / "offsite.html").read_text("utf-8")) == "offsite"
    assert linkedin_apply((pages / "easy_apply.html").read_text("utf-8")) == "easy_apply"
    assert linkedin_apply((pages / "simple_onsite.html").read_text("utf-8")) == "easy_apply"
    assert linkedin_apply("<html>no apply button</html>") is None


def test_parking_a_linkedin_job_reads_its_apply_kind(tmp_path: Path) -> None:
    import asyncio
    from pathlib import Path

    import httpx

    from linkit_all.apply.runner import Applier
    from linkit_all.core.config import Settings
    from linkit_all.core.db import init_db
    from linkit_all.core.models import ActionItem, Job, JobState
    from linkit_all.core.search import SearchConfig
    from linkit_all.sources.http import Http

    page = (Path(__file__).parents[1] / "fixtures/linkedin/offsite.html").read_text("utf-8")
    url = "https://www.linkedin.com/jobs/view/1"
    db = init_db(tmp_path / "db.sqlite")
    with db.begin() as s:
        s.add(Job(source="linkedin", url=url, title="t", company="c", location="", description="",
                  dedupe_hash="1", state=JobState.tailored, data={"apply_url": url}))  # fmt: skip

    async def go() -> None:
        transport = httpx.MockTransport(lambda req: httpx.Response(200, text=page))
        async with httpx.AsyncClient(transport=transport) as client:
            a = Applier(db, Settings(data_dir=tmp_path), SearchConfig(), None, lambda t: None,  # type: ignore[arg-type]
                        http=Http(client))  # fmt: skip
            await a._park_in_browser(1, url)

    asyncio.run(go())
    with db() as s:
        assert s.query(ActionItem).one().code == "apply_in_browser_offsite"
        assert s.get_one(Job, 1).data["linkedin_apply"] == "offsite"
