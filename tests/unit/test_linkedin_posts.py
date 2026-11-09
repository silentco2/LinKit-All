"""LinkedIn posts -> stubs by script: email/link finders, filters, ATS routing."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import httpx

from linkit_all.sources.base import JobStub
from linkit_all.sources.careers import Careers
from linkit_all.sources.http import Http
from linkit_all.sources.linkedin_posts.extract import posts_to_stubs
from linkit_all.sources.linkedin_posts.post import RawPost, find_emails, find_links
from linkit_all.sources.posts import PostRules

NOW = datetime(2026, 10, 25, 12, 0)
HIRING = "We're hiring a Data Engineer. Send your CV to hr@acme.com"


def mk(n: int = 1, text: str = HIRING, **kw: Any) -> RawPost:
    base: dict[str, Any] = {
        "urn": f"urn:li:activity:{n}",
        "url": f"https://www.linkedin.com/feed/update/urn:li:activity:{n}/",
        "author": "Sara",
        "author_url": "https://www.linkedin.com/in/sara",
        "headline": "HR at Acme",
        "posted_at": NOW - timedelta(days=3),
        "text": text,
        "links": (),
        "emails": find_emails(text),
        "scraped_at": NOW,
    }
    return RawPost(**{**base, **kw})


def run(posts: list[RawPost], rules: PostRules | None = None) -> list[JobStub]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(404)))
    http = Http(client, default_rate=1000, attempts=1)
    return asyncio.run(posts_to_stubs(posts, http, Careers(), rules or PostRules()))


def test_find_emails() -> None:
    text = "Mail Jobs@Acme.COM, or (hr.team@acme.co.uk). Logo logo@2x.png, a@b.jpg. jobs@acme.com"
    assert find_emails(text) == ("jobs@acme.com", "hr.team@acme.co.uk")
    assert find_emails("ارسل السيرة الذاتية إلى cv@acme.com.") == ("cv@acme.com",)


def test_find_links() -> None:
    text = "Apply: https://boards.greenhouse.io/acme/jobs/1, or www.acme.com/jobs. lnkd.in/abc)"
    assert find_links(text) == (
        "https://boards.greenhouse.io/acme/jobs/1",
        "https://www.acme.com/jobs",
        "https://lnkd.in/abc",
    )


def test_seekers_and_non_hiring_dropped() -> None:
    posts = [
        mk(1, "#OpenToWork I'm looking for a new role in data. Hiring managers, DM me."),
        mk(2, "أبحث عن عمل في مجال المبيعات"),
        mk(3, "Great keynote today about leadership and culture."),
    ]
    assert run(posts) == []


def test_ats_link() -> None:
    link = "https://boards.greenhouse.io/acme/jobs/4012345"
    post = mk(1, f"Backend Engineer at Acme\nApply {link}", links=(link,))
    [stub] = run([post])
    assert stub.ats == "greenhouse" and stub.apply_url == link and stub.url == post.url
    assert stub.source == "linkedin_posts" and stub.posted_at == NOW - timedelta(days=3)
    assert stub.extra["urn"] == post.urn and stub.extra["apply_method"] == "link"


def test_email_post_becomes_a_mailto_job() -> None:
    [stub] = run([mk(1, "Data Engineer needed, send your CV to HR@acme.com")])
    assert stub.apply_url == "mailto:hr@acme.com" and stub.title == "Data Engineer needed"
    assert stub.company == "Acme" and stub.ats is None
    assert stub.extra["apply_email"] == "hr@acme.com" and stub.extra["apply_method"] == "email"


def test_other_link_goes_to_the_form_and_dm_only_is_dropped() -> None:
    [stub] = run([mk(1, "We are hiring a Data Engineer. Apply at acme.com/careers/42")])
    assert stub.apply_url == "https://acme.com/careers/42"
    assert stub.extra["apply_method"] == "link" and stub.extra["apply_email"] is None
    assert run([mk(2, "We are hiring a Data Engineer. DM me for details")]) == []


def test_same_post_twice_gives_one_job() -> None:
    assert len(run([mk(1), mk(1)])) == 1
