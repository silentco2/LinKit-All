"""Homerun public Atom feed (feed.homerun.co/{board}); the board is the careers subdomain of
{board}.homerun.co. One request returns every open job, body inline. An unknown board answers
with a redirect to Homerun's 404 host, read here as "no such board".
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from lxml import etree

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import body_text, clean, name_from_slug, safe_date

FEED = "https://feed.homerun.co/{board}"
_RESERVED = "www|app|feed|help|static|cdn|api|developers|blog|404"
# Hardened: no entity resolution, no network; a feed is third-party text.
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=True)


def _child(node: etree._Element, *path: str) -> str:
    """Text of the first descendant reached by the local tag names in `path`."""
    for tag in path:
        found = next(
            (c for c in node if isinstance(c.tag, str) and etree.QName(c).localname == tag), None
        )
        if found is None:
            return ""
        node = found
    return "".join(str(t) for t in node.itertext()).strip()


class Homerun(Source):
    name = "homerun"
    kind = "ats"
    url_patterns = (
        re.compile(r"feed\.homerun\.co/([a-z0-9][a-z0-9-]*)", re.I),
        re.compile(rf"(?<![\w.-])(?!(?:{_RESERVED})\.)([a-z0-9][a-z0-9-]*)\.homerun\.co", re.I),
    )
    cdx_hosts = ("*.homerun.co",)
    parallel = 4

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one feed holds the whole board
            return
        resp = await http.get(FEED.format(board=task.board.lower()))
        moved = resp.headers.get("location", "")
        if "404.homerun.co" in (resp.url.host, urlsplit(moved).hostname) or resp.status_code == 404:
            raise Unsupported(f"homerun: no board named {task.board}")
        resp.raise_for_status()
        stubs = self.parse(resp.text, task.board)
        if stubs:
            yield stubs

    @staticmethod
    def parse(xml: str, board: str) -> list[JobStub]:
        root = etree.fromstring(xml.encode("utf-8"), _PARSER)
        if root is None:
            return []
        stubs = []
        for entry in root.iter("{*}entry"):
            links = [
                c for c in entry if isinstance(c.tag, str) and etree.QName(c).localname == "link"
            ]
            link = next(
                (x for x in links if x.get("rel") == "alternate"), links[0] if links else None
            )
            url = (link.get("href") or "").strip() if link is not None else ""
            title = clean(_child(entry, "title"))
            if not title or not url.startswith("https://"):
                continue
            where = clean(_child(entry, "location", "name"))
            stubs.append(
                JobStub(
                    source="homerun",
                    url=url,
                    title=title,
                    company=clean(_child(entry, "author", "name")) or name_from_slug(board),
                    location=where,
                    description=body_text(_child(entry, "description")),
                    posted_at=safe_date(_child(entry, "updated")),
                    ats="homerun",
                    apply_url=url,
                    remote=remote_from_text(where),
                    extra={
                        "board": board,
                        "id": _child(entry, "id"),
                        "salary_text": _child(entry, "salary_indication"),
                    },
                )
            )
        return stubs
