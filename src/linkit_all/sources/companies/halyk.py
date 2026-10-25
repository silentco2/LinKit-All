"""Halyk Bank's career site (halykbank.kz/about/career/vacancies): one server-rendered listing, then
one HTML page per vacancy; there is no API and no JobPosting markup. The number in
/vacancies-inner/N is a position in the current list, not an id (it shifts when the list does), so
each posting's page is read during the listing run, while the number still points at it. A
single-company plugin, not an ATS. Logic adapted from freehire (MIT)."""

import hashlib
import re
from collections.abc import AsyncIterator
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser, LexborNode

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page, hydrate, page_text, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import node_text, remote_ru

HOST = "halykbank.kz"
LIST = "https://{host}/about/career/vacancies"
CHUNK = 10
_PATH = re.compile(r"vacancies-inner/\d+(?:[/?#]|$)")


def identity(title: str, city: str) -> str:
    """A stable id: the path number is not one, title and city were unique across the live cards."""
    key = f"{' '.join(title.lower().split())}\n{' '.join(city.lower().split())}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def cards(html: str, base: str) -> list[tuple[str, str, str]]:
    """(url, title, city) of each vacancy card of the listing."""
    found: list[tuple[str, str, str]] = []
    for a in LexborHTMLParser(html).css("a[href]"):
        href = a.attributes.get("href") or ""
        title = node_text(a.css_first(".text-lg.font-bold"))
        if _PATH.search(href) and title:
            found.append((urljoin(base, href), title, node_text(a.css_first(".flex-x"))))
    return found


def body(html: str) -> str:
    items: list[LexborNode] = LexborHTMLParser(html).css(".vacanices-inner-cie-item")
    return strip_html("\n".join(n.html or "" for n in items))


class Halyk(Source):
    name = "halyk"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "halyk:vacancies", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        url = LIST.format(host=task.board)
        listed = cards((await get_page(http, url)).text, url)
        if not listed:  # an empty bank never happens; a changed layout does
            raise ValueError("halyk: the listing links no vacancies, the markup changed?")

        async def build(card: tuple[str, str, str]) -> JobStub | None:
            link, title, city = card
            html = await page_text(http, link)  # gone or unreadable: leave this one out
            text = body(html) if html else ""
            return (
                JobStub(
                    source=self.name,
                    url=link,
                    title=title,
                    company="Halyk Bank",
                    location=city,
                    description=text,
                    ats=self.name,
                    apply_url=link,
                    remote=remote_ru(title, city),
                    extra={"id": identity(title, city)},
                )
                if text
                else None
            )

        async for stubs in hydrate(listed, start_page, build, CHUNK):
            yield stubs
