"""LinkedIn posts -> stubs: age labels, email/link finders, filters, ATS routing, batched AI."""

import asyncio
from datetime import datetime, timedelta
from typing import Any, cast

import pytest

from linkit_all.providers.base import LLMProvider, UsageLimitError
from linkit_all.sources.base import JobStub
from linkit_all.sources.linkedin_posts.extract import (
    AI_BATCH,
    ExtractedJob,
    ExtractedPost,
    ExtractedPosts,
    posts_to_stubs,
)
from linkit_all.sources.linkedin_posts.post import (
    RawPost,
    find_emails,
    find_links,
    keep_recent,
    posted_at,
)

NOW = datetime(2026, 10, 25, 12, 0)
HIRING = "We're hiring a Data Engineer. Send your CV to hr@acme.com"


def mk(n: int = 1, text: str = HIRING, **kw: Any) -> RawPost:
    base: dict[str, Any] = {
        "urn": f"urn:li:activity:{n}",
        "url": f"https://www.linkedin.com/feed/update/urn:li:activity:{n}/",
        "author": "Sara",
        "author_url": "https://www.linkedin.com/in/sara",
        "headline": "HR at Acme",
        "posted_text": "3d",
        "text": text,
        "links": (),
        "emails": find_emails(text),
        "scraped_at": NOW,
    }
    return RawPost(**{**base, **kw})


class FakeProvider:
    def __init__(self, jobs: dict[int, list[ExtractedJob]] | None = None) -> None:
        self.calls: list[str] = []
        self.jobs = jobs or {}

    async def complete(self, prompt: str, schema: type[ExtractedPosts]) -> ExtractedPosts:
        self.calls.append(prompt)
        count = prompt.count("=== post id ")
        return ExtractedPosts(
            posts=[ExtractedPost(id=i, jobs=self.jobs.get(i, [])) for i in range(count)]
        )


def run(posts: list[RawPost], provider: FakeProvider | None) -> list[JobStub]:
    return asyncio.run(posts_to_stubs(posts, cast(LLMProvider | None, provider)))


@pytest.mark.parametrize(
    ("label", "delta"),
    [
        ("3h", timedelta(hours=3)),
        ("2d", timedelta(days=2)),
        ("1w", timedelta(weeks=1)),
        ("1mo", timedelta(days=30)),
        ("3 days ago", timedelta(days=3)),
        ("5m", timedelta(minutes=5)),
        ("2d • Edited", timedelta(days=2)),
        ("منذ 3 أيام", timedelta(days=3)),
        ("٣ي", timedelta(days=3)),
        ("منذ ٢ أسبوع", timedelta(weeks=2)),
        ("٥س", timedelta(hours=5)),
        ("منذ 1 شهر", timedelta(days=30)),
    ],
)
def test_posted_at(label: str, delta: timedelta) -> None:
    assert posted_at(mk(posted_text=label)) == NOW - delta


def test_posted_at_unreadable() -> None:
    assert posted_at(mk(posted_text="")) is None
    assert posted_at(mk(posted_text="soon")) is None
    assert posted_at(mk(posted_text="Feb 30")) is None


@pytest.mark.parametrize(
    ("label", "at"),
    [
        ("Oct 22", datetime(2026, 10, 22)),
        ("Oct 22 • Edited", datetime(2026, 10, 22)),
        ("22 Oct", datetime(2026, 10, 22)),
        ("22 Dec", datetime(2025, 12, 22)),  # not "22 days"; a future date is last year's
        ("Dec 3, 2024", datetime(2024, 12, 3)),
        ("٢٢ أكتوبر", datetime(2026, 10, 22)),
        ("Yesterday", NOW - timedelta(days=1)),
        ("أمس", NOW - timedelta(days=1)),
    ],
)
def test_posted_at_absolute_labels(label: str, at: datetime) -> None:
    assert posted_at(mk(posted_text=label)) == at


def test_keep_recent_only_filters_past_the_threshold() -> None:
    labels = ["2d", "Oct 18", "Oct 10", "soon"]  # 3 / 7 / 15 days old, unreadable
    posts = [mk(i, posted_text=labels[i % 4]) for i in range(8)]
    assert keep_recent(posts, "week", after=8) == posts  # not more than `after`: untouched
    kept = keep_recent(posts, "week", after=7)
    assert [p.posted_text for p in kept] == ["2d", "Oct 18", "soon"] * 2
    assert [p.posted_text for p in keep_recent(posts, "day", after=7)] == ["soon"] * 2


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
    provider = FakeProvider()
    assert run(posts, provider) == []
    assert provider.calls == []


def test_ats_link_needs_no_ai() -> None:
    link = "https://boards.greenhouse.io/acme/jobs/4012345"
    post = mk(1, f"Backend Engineer at Acme\nApply {link}", links=(link,))
    [stub] = run([post], None)
    assert stub.ats == "greenhouse"
    assert stub.apply_url == link
    assert stub.url == post.url
    assert stub.source == "linkedin_posts"
    assert stub.posted_at == NOW - timedelta(days=3)
    assert stub.extra["urn"] == post.urn
    assert stub.extra["apply_method"] == "link"


def test_no_provider_means_no_guessing() -> None:
    assert run([mk(1)], None) == []


def test_email_job_gets_mailto() -> None:
    job = ExtractedJob(
        title="Data Engineer", company="Acme", apply_method="email", apply_email="HR@acme.com"
    )
    post = mk(1)
    [stub] = run([post], FakeProvider({0: [job]}))
    assert stub.apply_url == "mailto:hr@acme.com"
    assert stub.extra["apply_email"] == "hr@acme.com"
    assert stub.extra["apply_method"] == "email"
    assert stub.url == post.url  # single job: no suffix
    assert stub.ats is None


def test_invented_email_and_link_dropped() -> None:
    fake_mail = ExtractedJob(title="A", apply_method="email", apply_email="ceo@evil.com")
    fake_link = ExtractedJob(title="B", apply_method="form", apply_link="https://evil.com/apply")
    real_link = ExtractedJob(title="C", apply_method="form", apply_link="https://acme.com/apply/")
    post = mk(1, "We are hiring. Apply via https://acme.com/apply or hr@acme.com")
    stubs = run([post], FakeProvider({0: [fake_mail, fake_link, real_link]}))
    assert [s.title for s in stubs] == ["C"]
    assert stubs[0].apply_url == "https://acme.com/apply/"
    assert stubs[0].extra["apply_method"] == "form"


def test_wrong_method_falls_back_to_what_is_real() -> None:
    job = ExtractedJob(
        title="A", apply_method="email", apply_email="x@evil.com", apply_link="https://acme.com/j"
    )
    post = mk(1, "We are hiring, see https://acme.com/j")
    [stub] = run([post], FakeProvider({0: [job]}))
    assert stub.apply_url == "https://acme.com/j"
    assert stub.extra["apply_method"] == "form"


def test_none_and_untitled_dropped_multi_job_suffix() -> None:
    jobs = [
        ExtractedJob(title="Dev", apply_method="email", apply_email="hr@acme.com"),
        ExtractedJob(title="DM role", apply_method="none"),
        ExtractedJob(title="QA", company="Acme", apply_method="email", apply_email="hr@acme.com"),
        ExtractedJob(title="", apply_method="email", apply_email="hr@acme.com"),
    ]
    post = mk(1)
    stubs = run([post], FakeProvider({0: jobs}))
    assert [s.url for s in stubs] == [post.url + "#1", post.url + "#2"]
    assert [s.title for s in stubs] == ["Dev", "QA"]
    assert stubs[0].company == "Unknown"


def test_batches_of_ten() -> None:
    posts = [mk(n) for n in range(1, 26)]
    provider = FakeProvider()
    run(posts, provider)
    assert AI_BATCH == 10
    assert [c.count("=== post id ") for c in provider.calls] == [10, 10, 5]
    assert "Headline: HR at Acme" in provider.calls[0]


def test_duplicate_urn_asked_once() -> None:
    provider = FakeProvider()
    run([mk(1), mk(1)], provider)
    assert provider.calls[0].count("=== post id ") == 1


def test_usage_limit_propagates() -> None:
    class Limited:
        async def complete(self, prompt: str, schema: Any) -> Any:
            raise UsageLimitError("limit")

    with pytest.raises(UsageLimitError):
        asyncio.run(posts_to_stubs([mk(1)], cast(LLMProvider, Limited())))
