"""Company name -> its job boards, by asking our ATS plugins' public APIs.

`find_boards("Stripe")` turns the name into a few slug guesses ("stripe"), runs the first page
of each plugin's own `search` for them, and keeps the boards that answer with at least one job.
Nothing is saved here: the CLI (`linkit find-board`) and the Sources "Add" box show the result
and the user decides. A name no plugin answers for is returned as not found, for the user to
look up by hand (paste the careers page instead).

Logic adapted from career-ops (MIT).
"""

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from loguru import logger

from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http, make_client
from linkit_all.sources.labels import PLATFORMS

# Plugins whose board slug is one word taken from the company name, most common first.
PROBE_ORDER = ("greenhouse", "ashby", "lever", "workable", "smartrecruiters", "recruitee",
               "bamboohr", "breezy", "pinpoint", "rippling", "join")  # fmt: skip
_LEGAL = re.compile(r"\b(inc|llc|ltd|gmbh|corp|co|plc|ag|sa|bv)\.?$", re.I)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# Tests swap this for a fake transport (httpx.MockTransport); None = the real network.
_TRANSPORT: httpx.AsyncBaseTransport | None = None


@dataclass(frozen=True)
class Found:
    ats: str
    slug: str
    name: str  # the company as the board itself names it
    jobs: int  # jobs on the first page

    @property
    def value(self) -> str:
        """The `sources.companies` entry for this board."""
        return f"{self.ats}:{self.slug}"

    @property
    def label(self) -> str:
        return board_label(self.ats, self.name)


def board_label(ats: str, name: str) -> str:
    """("greenhouse", "Stripe") -> "Stripe · Greenhouse", the form `company_labels` holds."""
    return f"{name} · {PLATFORMS.get(ats, ats.title())}"


def slug_guesses(name: str) -> list[str]:
    """Slugs to try: "Scale AI, Inc." -> ["scale-ai", "scaleai"] (hyphenated, run together)."""
    words = re.sub(r"[^a-z0-9]+", " ", _LEGAL.sub("", name.strip().lower())).split()
    return [s for s in dict.fromkeys(("-".join(words), "".join(words))) if _SLUG.match(s)]


async def _probe(http: Http, src: Source, slug: str) -> Found | None:
    """The board `slug` on `src`, if it exists and lists a job. Any failure reads as "no"."""
    pages = src.search(http, Task(src.name, f"{src.name}:{slug}", board=slug), 0)
    try:
        stubs = await anext(pages, list[JobStub]())
    except Exception as e:  # 404 for a missing board; a plugin's parse error on an odd answer
        logger.debug("find-board {}:{} -> {}: {}", src.name, slug, type(e).__name__, e)
        return None
    finally:
        await pages.aclose()  # type: ignore[attr-defined]
    return Found(src.name, slug, stubs[0].company, len(stubs)) if stubs else None


async def find_boards(
    http: Http, registry: dict[str, Source], name: str, ats: Sequence[str] = PROBE_ORDER
) -> list[Found]:
    """Boards for one company name, in `ats` order; per ATS the first slug guess that answers."""

    async def one(src: Source) -> Found | None:
        for slug in slug_guesses(name):
            if found := await _probe(http, src, slug):
                return found
        return None

    hits = await asyncio.gather(*(one(registry[a]) for a in ats if a in registry))
    return [h for h in hits if h]


async def resolve(
    registry: dict[str, Source], names: Sequence[str]
) -> tuple[dict[str, list[Found]], list[str]]:
    """({name: its boards}, names with no board: for the user to follow up by hand). One try
    per request: a person is waiting, and a throttled ATS simply reads as "not found"."""
    found: dict[str, list[Found]] = {}
    missing: list[str] = []
    async with make_client(transport=_TRANSPORT) as client:
        http = Http(client, attempts=1)
        for name in names:
            if boards := await find_boards(http, registry, name):
                found[name] = boards
            else:
                missing.append(name)
    return found, missing
