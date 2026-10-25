"""Telegram's own jobs page (telegram.org/jobs): one hand-maintained page, each role an <h3> title
followed by its description. A single-company plugin, not an ATS. Logic adapted from freehire
(MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page, strip_html
from linkit_all.sources.http import Http

PAGE = "https://telegram.org/jobs"


def parse_page(html: str) -> list[JobStub]:
    content = LexborHTMLParser(html).css_first("#dev_page_content")
    if content is None:
        return []
    roles: list[tuple[str, list[str]]] = []
    for node in content.iter(include_text=True):
        if node.tag == "h3":  # opens a role; everything up to the next <h3> is its body
            roles.append((" ".join(node.text(deep=True).split()), []))
        elif roles:
            roles[-1][1].append(node.html or "")
    stubs = []
    for title, body in roles:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        if title and slug:
            # The page gives no per-role address; a query keeps each role's URL distinct
            # (a #fragment is dropped when URLs are normalized, which would merge them all).
            url = f"{PAGE}?role={slug}"
            stubs.append(
                JobStub(
                    source="telegramcareers",
                    ats="telegramcareers",
                    url=url,
                    title=title,
                    company="Telegram",
                    description=strip_html("".join(body)),
                    apply_url=url,
                    extra={"id": slug},
                )
            )
    return stubs


class TelegramCareers(Source):
    name = "telegramcareers"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "telegramcareers:jobs", board=PAGE)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        yield parse_page((await get_page(http, PAGE)).text)
