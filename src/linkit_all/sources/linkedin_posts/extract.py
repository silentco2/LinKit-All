"""LinkedIn hiring posts -> job stubs. No fetching here.

Job-seeker posts and posts that do not read as hiring are dropped. A post linking to a known ATS
becomes a stub for that ATS. The others are read by script (`posts`, no AI): an email makes it an
email application, a link goes to the careers scraper, and a post with neither (DM or comment
only) is dropped. The stub's url is the post, which is the dedupe key; the apply target is
`apply_url` (a link, or `mailto:<address>`).
"""

# ruff: noqa: RUF001  (Arabic hiring words are the point here)
import re
from collections.abc import Callable, Sequence

from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, remote_from_text
from linkit_all.sources.careers import Careers
from linkit_all.sources.http import Http
from linkit_all.sources.linkedin_posts.post import RawPost, find_links
from linkit_all.sources.posts import PostJob, PostRules, fold, is_seeker, post_stub
from linkit_all.sources.telegram import looks_like_vacancy

SOURCE = "linkedin_posts"
DESCRIPTION = 4000  # characters of a post kept as the job description

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


def is_hiring(text: str) -> bool:
    folded = fold(text.replace("’", "'"))
    return _HIRING.search(folded) is not None or looks_like_vacancy(text)


def _ats_link(post: RawPost) -> tuple[str, str, str] | None:
    """(ats, board slug, url) of the first link in the post that a known ATS hosts."""
    for url in (*post.links, *find_links(post.text)):
        if (found := detect(url)) is not None:
            return found[0], found[1], url
    return None


def _linked(post: RawPost, ats: str, board: str, link: str) -> JobStub:
    first = next((ln.strip() for ln in post.text.splitlines() if ln.strip()), post.headline)
    return JobStub(
        source=SOURCE,
        url=post.url,
        title=first[:120],
        company=board.split("/")[0].replace("-", " ").replace("_", " ").title(),
        description=post.text[:DESCRIPTION],
        posted_at=post.posted_at,
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


async def posts_to_stubs(
    posts: Sequence[RawPost],
    http: Http,
    reader: Careers,
    rules: PostRules,
    known: Callable[[str], bool] = lambda _url: False,
) -> list[JobStub]:
    """Job stubs for the hiring posts among `posts`."""
    stubs: list[JobStub] = []
    seen: set[str] = set()
    for post in posts:
        if post.urn in seen or is_seeker(post.text):
            continue
        seen.add(post.urn)
        if link := _ats_link(post):
            stubs.append(_linked(post, *link))
        elif is_hiring(post.text):
            links = tuple(dict.fromkeys((*post.links, *find_links(post.text))))
            job = PostJob(SOURCE, post.url, post.text, links, post.posted_at, {})
            stub = await post_stub(http, reader, job, rules, fetch=not known(post.url))
            if stub is not None:
                mailed = (stub.apply_url or "").startswith("mailto:")
                email = (stub.apply_url or "").removeprefix("mailto:") if mailed else None
                extra = _extra(post, "email" if mailed else "link", email)
                stubs.append(stub.model_copy(update={"extra": extra}))
    return stubs
