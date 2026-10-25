"""LinkedIn hiring posts -> job stubs. No scraping here.

Job-seeker posts and posts that do not read as hiring are dropped. A post linking to a known ATS
becomes a stub for that ATS (no AI). The others go to the AI in batches of AI_BATCH posts per
call, when a provider is available; what it returns is checked against the post (an email or
link that is not written in the post is dropped) and jobs that cannot be applied to from the
post (DM or comment only) are dropped. The stub's url is the post (a `#n` suffix when one post
yields several jobs), which is the dedupe key; the apply target is `apply_url` (a link, or
`mailto:<address>`).
"""

# ruff: noqa: RUF001  (Arabic hiring words are the point here)
import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from linkit_all.providers.base import LLMProvider, ProviderError, UsageLimitError, render
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, remote_from_text
from linkit_all.sources.linkedin_posts.post import RawPost, find_emails, find_links, posted_at
from linkit_all.sources.telegram import EXCERPT, fold, looks_like_vacancy

SOURCE = "linkedin_posts"
AI_BATCH = 10  # posts per AI call
DESCRIPTION = 4000  # characters of a post kept as the job description

_SEEKER = re.compile(
    fold(
        "|".join(
            (
                r"#opentowork|#open_to_work|open to work|open for work|open to new opportunit",
                r"(?:i am|i'm|im) (?:currently )?(?:actively )?(?:looking|searching|seeking) "
                r"(?:for )?(?:a |an )?(?:new )?(?:job|role|position|opportunit|work|employment)",
                r"(?:looking|searching|seeking) for (?:a |my )(?:new )?(?:job|role|position|"
                r"opportunit)",
                r"ابحث عن (?:عمل|وظيفة|فرصة|شغل)|أبحث عن (?:عمل|وظيفة|فرصة|شغل)",
                r"ابحث عن فرص",
            )
        )
    )
)
_HIRING = re.compile(
    fold(
        "|".join(
            (
                r"we(?:'|’)?re hiring|we are hiring|now hiring|is hiring|are hiring|hiring",
                r"join our team|send (?:your |an? )?(?:cv|resume|résumé)|apply (?:via|here|now|at)",
                r"نبحث عن|مطلوب|فرصة عمل|فرص عمل",
                r"ارسل (?:ال)?سيرة الذاتية|ارسال (?:ال)?سيرة الذاتية",
                r"تعلن عن|وظيفة شاغرة|وظائف شاغرة",
            )
        )
    )
)


def is_seeker(text: str) -> bool:
    return _SEEKER.search(fold(text.replace("’", "'"))) is not None


def is_hiring(text: str) -> bool:
    folded = fold(text.replace("’", "'"))
    return _HIRING.search(folded) is not None or looks_like_vacancy(text)


class ExtractedJob(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    remote: Literal["remote", "hybrid", "onsite"] | None = None
    apply_method: Literal["email", "form", "link", "none"] = "none"
    apply_email: str = ""
    apply_link: str = ""
    seniority: str | None = None


class ExtractedPost(BaseModel):
    id: int  # our number in the batch; replies with other ids are ignored
    jobs: list[ExtractedJob] = []


class ExtractedPosts(BaseModel):
    posts: list[ExtractedPost]


def _ats_link(post: RawPost) -> tuple[str, str, str] | None:
    """(ats, board slug, url) of the first link in the post that a known ATS hosts."""
    for url in (*post.links, *find_links(post.text)):
        if (found := detect(url)) is not None:
            return found[0], found[1], url
    return None


def _norm(url: str) -> str:
    return url.strip().rstrip("/.,;:!?)").lower()


def _verbatim(post: RawPost, email: str, link: str) -> tuple[str, str]:
    """The email and link the model gave, each '' unless the post really contains it."""
    emails = {e.lower() for e in (*post.emails, *find_emails(post.text))}
    links = {_norm(u) for u in (*post.links, *find_links(post.text))}
    email = email.strip().lower().removeprefix("mailto:")
    link = link.strip()
    return (
        email if email in emails else "",
        link if _norm(link) in links else "",
    )


def _linked(post: RawPost, ats: str, board: str, link: str) -> JobStub:
    first = next((ln.strip() for ln in post.text.splitlines() if ln.strip()), post.headline)
    return JobStub(
        source=SOURCE,
        url=post.url,
        title=first[:120],
        company=board.split("/")[0].replace("-", " ").replace("_", " ").title(),
        description=post.text[:DESCRIPTION],
        posted_at=posted_at(post),
        ats=ats,
        apply_url=link,
        remote=remote_from_text(first),
        extra=_extra(post, "link", None),
    )


def _extra(post: RawPost, method: str, email: str | None) -> dict[str, object]:
    return {
        "urn": post.urn,
        "author": post.author,
        "author_url": post.author_url,
        "headline": post.headline,
        "apply_method": method,
        "apply_email": email,
    }


def _stubs_of(post: RawPost, found: ExtractedPost) -> list[JobStub]:
    ready: list[tuple[ExtractedJob, str, str, str]] = []  # job, method, email, link
    for job in found.jobs:
        if not job.title.strip() or job.apply_method == "none":
            continue
        email, link = _verbatim(post, job.apply_email, job.apply_link)
        if job.apply_method == "email" and email:
            ready.append((job, "email", email, ""))
        elif link:
            ready.append((job, "link" if job.apply_method == "link" else "form", "", link))
        elif email:
            ready.append((job, "email", email, ""))
    stubs = []
    for n, (job, method, email, link) in enumerate(ready, 1):
        ats = detect(link) if link else None
        stubs.append(
            JobStub(
                source=SOURCE,
                url=post.url + (f"#{n}" if len(ready) > 1 else ""),
                title=job.title.strip(),
                company=job.company.strip() or "Unknown",
                location=job.location.strip(),
                description=post.text[:DESCRIPTION],
                posted_at=posted_at(post),
                ats=ats[0] if ats else None,
                apply_url=f"mailto:{email}" if method == "email" else link,
                remote=job.remote or remote_from_text(job.title, job.location),
                extra=_extra(post, method, email or None)
                | ({"seniority": job.seniority} if job.seniority else {}),
            )
        )
    return stubs


async def _extract(provider: LLMProvider, posts: list[RawPost]) -> list[JobStub]:
    """One AI call for a batch; ids are ours, any other id in the reply is dropped."""
    sent = [
        {"id": n, "author": p.author, "headline": p.headline, "text": p.text[:EXCERPT]}
        for n, p in enumerate(posts)
    ]
    try:
        result = await provider.complete(
            render("extract_linkedin_post.j2", posts=sent), ExtractedPosts
        )
    except UsageLimitError:
        raise  # pause the run cleanly instead of silently degrading
    except ProviderError:
        return []
    stubs: list[JobStub] = []
    seen: set[int] = set()
    for found in result.posts:
        if not 0 <= found.id < len(posts) or found.id in seen:
            continue
        seen.add(found.id)
        stubs += _stubs_of(posts[found.id], found)
    return stubs


async def posts_to_stubs(posts: Sequence[RawPost], provider: LLMProvider | None) -> list[JobStub]:
    """Job stubs for the hiring posts among `posts`. Without a provider only posts that link to
    an ATS yield jobs (nothing is guessed)."""
    stubs: list[JobStub] = []
    ask: list[RawPost] = []
    seen: set[str] = set()
    for post in posts:
        if post.urn in seen or is_seeker(post.text):
            continue
        seen.add(post.urn)
        if link := _ats_link(post):
            stubs.append(_linked(post, *link))
        elif is_hiring(post.text):
            ask.append(post)
    if provider is not None:
        for start in range(0, len(ask), AI_BATCH):
            stubs += await _extract(provider, ask[start : start + AI_BATCH])
    return stubs
