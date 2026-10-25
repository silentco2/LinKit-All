"""Staffy's job board (jobs.wearestaffy.com), a recruiting agency's own site: the listing and every
position page are plain server-rendered HTML. A single-company plugin, not an ATS. Logic adapted
from freehire (MIT)."""

from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.common import CHUNK, hydrate, page_text, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import links

LIST = "https://jobs.wearestaffy.com/vacantes"


def work_mode(text: str) -> Remote | None:
    """The metadata line is Spanish prose ("Hibrido - 2 veces por semana"), so match its start."""
    t = text.strip().lower()
    return (
        "remote"
        if t.startswith("remoto")
        else "hybrid"
        if t.startswith(("hibrido", "híbrido"))
        else None
    )


def parse_position(html: str, url: str) -> JobStub | None:
    tree = LexborHTMLParser(html)
    article = tree.css_first(".position-content")
    h1 = article.css_first("h1") if article else None
    spans = [" ".join(s.text(deep=True).split()) for s in tree.css(".metadata span")]
    if article is None or h1 is None or len(spans) < 3:  # [location, work arrangement, seniority]
        return None
    body, after_meta = [], False
    for child in article.iter():  # the article is flat: prose follows the metadata block
        if "metadata" in (child.attributes.get("class") or "").split():
            after_meta = True
        elif after_meta and child.tag in ("h2", "p", "ul"):
            body.append(child.html or "")
    return JobStub(
        source="staffy",
        ats="staffy",
        url=url,
        title=" ".join(h1.text(deep=True).split()),
        company="Staffy",
        location=spans[0],
        description=strip_html("".join(body)),
        apply_url=url,
        remote=work_mode(spans[1]),
        extra={"id": url.rstrip("/").rsplit("/", 1)[-1]},
    )


class Staffy(Source):
    name = "staffy"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "staffy:vacantes", board=LIST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        listing = await page_text(http, LIST)
        if listing is None:
            raise ValueError(f"staffy: {LIST} could not be read")
        urls = links(listing, LIST, lambda href: "/positions/" in href)

        async def build(url: str) -> JobStub | None:
            html = await page_text(http, url)
            return parse_position(html, url) if html else None

        async for page in hydrate(urls, start_page, build, CHUNK):
            yield page
