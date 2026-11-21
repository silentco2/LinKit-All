"""Gradcracker (gradcracker.com): UK graduate jobs and placements in STEM. Its keyword search does
not filter, so the discipline listings matching the user's titles are read (by rules; no match
-> all disciplines) and our own filters narrow them. The card is the description (disciplines,
deadline, salary, location, degree, start): no request per job (maintainer 2026-11-20). The
first <article> on a listing is a hidden honeypot link for bots and is skipped. The job page
is the apply URL: its Apply button leads to the employer."""

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from aiolimiter import AsyncLimiter
from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.matching.trash import wanted_titles
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import fetch_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean

BASE = "https://www.gradcracker.com"
MAX_PAGES = 40  # all disciplines had 19 pages of 80 in 2026-11
INTERVAL = 1.0  # seconds between requests
# Discipline slug -> words in a wanted title that point to it (whole words, lower case).
DISCIPLINES = {
    "technology-it": ("software", "developer", "programmer", "data", "it", "cyber", "security",
                      "cloud", "devops", "web", "frontend", "backend", "full", "stack", "ai",
                      "machine", "ml", "network", "systems", "computer", "analyst", "qa", "test"),
    "electronic-electrical": ("electrical", "electronic", "electronics", "embedded", "hardware",
                              "power", "control", "instrumentation"),
    "mechanical-manufacturing": ("mechanical", "manufacturing", "production", "mechatronics",
                                 "robotics", "automotive"),
    "civil-building": ("civil", "structural", "building", "construction", "geotechnical",
                       "transport", "highways", "surveyor"),
    "chemical-process": ("chemical", "process", "petroleum", "materials"),
    "aerospace": ("aerospace", "aeronautical", "avionics", "space"),
    "maths-business": ("maths", "mathematics", "actuarial", "finance", "business", "economics",
                       "statistician", "quantitative"),
    "science": ("science", "scientist", "chemist", "physicist", "biology", "biologist",
                "physics", "chemistry", "lab", "research"),
}  # fmt: skip
_FIELDS = ("Deadline", "Salary", "Location", "Degree required", "Starting")


@dataclass
class Card:
    id: str
    url: str
    title: str
    company: str
    disciplines: str
    fields: dict[str, str]


def disciplines(titles: list[str]) -> list[str]:
    """The discipline slugs the wanted titles point to; ["all-disciplines"] when none does."""
    words = {w for t in titles for w in re.findall(r"[a-z]+", t.lower())}
    found = [slug for slug, keys in DISCIPLINES.items() if words & set(keys)]
    return found or ["all-disciplines"]


def parse_cards(page: str) -> list[Card]:
    """The job cards of a listing page; the honeypot article (no data-search-result) is not one."""
    out = []
    for node in LexborHTMLParser(page).css("article[data-search-result]"):
        link = node.css_first("h2 a[href]")
        logo = node.css_first("figure img[alt]")
        if link is None:
            continue
        href = (link.attributes.get("href") or "").strip()
        h3 = node.css_first("h3")
        fields = {}
        for row in node.css("dl > div"):
            dt, dd = row.css_first("dt"), row.css_first("dd")
            if dt is not None and dd is not None and clean(dt.text()) in _FIELDS:
                fields[clean(dt.text())] = clean(dd.text())
        card = Card(
            id=(node.attributes.get("data-search-result") or "").strip(),
            url=href if href.startswith(f"{BASE}/hub/") else "",
            title=clean(link.text()),
            company=clean(logo.attributes.get("alt") if logo is not None else "") or "Unknown",
            disciplines=clean(h3.text()).rstrip(".") if h3 is not None else "",
            fields=fields,
        )
        if card.id and card.url and card.title:
            out.append(card)
    return out


class Gradcracker(Source):
    name = "gradcracker"
    kind = "board"
    label = "Gradcracker"
    region = "United Kingdom"

    def __init__(self) -> None:
        self._pace = AsyncLimiter(1, INTERVAL)

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        s = cfg.search
        return [
            Task(self.name, f"{self.name}:{slug}", board=slug, limit=s.max_results_per_query * 4,
                 posted_within_days=s.posted_within_days)
            for slug in disciplines(wanted_titles(cfg))
        ]  # fmt: skip

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen: set[str] = set()
        count = 0
        for page in range(start_page + 1, MAX_PAGES + 1):
            url = f"{BASE}/search/{task.board}/graduate-jobs" + (f"?page={page}" * (page > 1))
            async with self._pace:
                html = await fetch_html(http, url)
            cards = [c for c in parse_cards(html or "") if c.id not in seen]
            if not cards:
                return  # past the last page the listing repeats or is empty
            seen.update(c.id for c in cards)
            stubs = [self.stub(c) for c in cards[: task.limit - count]]
            count += len(stubs)
            yield stubs
            if count >= task.limit:
                return

    def stub(self, c: Card) -> JobStub:
        where = c.fields.get("Location", "")
        lines = [c.title, f"Disciplines: {c.disciplines}" if c.disciplines else ""]
        lines += [f"{k}: {v}" for k, v in c.fields.items()]
        return JobStub(
            source=self.name, url=c.url, title=c.title, company=c.company,
            location=re.sub(r"\s*\((?:hybrid|remote)\)\s*$", "", where, flags=re.I),
            description="\n".join(x for x in lines if x), apply_url=c.url,
            remote=remote_from_text(where), extra={"id": c.id},
        )  # fmt: skip
