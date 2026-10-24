"""Deel's multi-tenant ATS (jobs.deel.com/<org>): a Next.js page that inlines its whole catalogue.
Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f12 import get_page, name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

BOARD = "https://jobs.deel.com/{board}"
JOB = "https://jobs.deel.com/{board}/job-details/{id}/overview"
# The page pushes its data as self.__next_f.push([1,"..."]) chunks: JS string literals that,
# joined, form the RSC "flight" stream holding the page's JSON.
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
# A text row is "<hex id>:T<hex byte length>,<content>"; a posting refers to it as "$<id>".
_TEXT_ROW = re.compile(rb"[^0-9a-f]([0-9a-f]+):T([0-9a-f]+),")


def decode_flight(page: str) -> str:
    chunks = _PUSH.findall(page)
    if not chunks:
        raise ValueError("deel: no Next.js flight payload on the page")
    return "".join(json.loads(c) for c in chunks)


def bracket_slice(text: str, key: str, open_: str, close: str) -> str | None:
    """The balanced open..close run after `key`, counting brackets outside string literals."""
    at = text.find(key)
    start = text.find(open_, at) if at >= 0 else -1
    if start < 0:
        return None
    depth, in_string, i = 0, False, start
    while i < len(text):
        c = text[i]
        if in_string:
            if c == "\\":
                i += 1
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    return None


def text_rows(flight: str) -> dict[str, str]:
    """The flight's text rows by id; each row's content is exactly its declared number of bytes."""
    raw = flight.encode()
    rows = {}
    for m in _TEXT_ROW.finditer(raw):
        start = m.end()
        rows[m[1].decode()] = raw[start : start + int(m[2], 16)].decode(errors="replace")
    return rows


class Deel(Source):
    """The board is the organisation's URL slug: `jobs.deel.com/<slug>`."""

    name = "deel"
    kind = "ats"
    url_patterns = (re.compile(r"jobs\.deel\.com/([\w-]+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one page holds every posting
            return
        flight = decode_flight((await get_page(http, BOARD.format(board=task.board))).text)
        raw = bracket_slice(flight, '"jobPostings":', "[", "]")
        if raw is None:
            raise ValueError(f"deel: no postings in the {task.board} page (markup changed?)")
        postings = [p for p in json.loads(raw) if p.get("id")]
        settings = bracket_slice(flight, '"careerPageSettings":', "{", "}")
        org = (json.loads(settings).get("preferredOrganizationName") if settings else "") or ""
        rows = text_rows(flight)
        refs = [p["richtextDescription"][1:] for p in postings if _is_ref(p)]
        if refs and not any(rows.get(r, "").strip() for r in refs):
            # Every description failed to resolve: the row format changed. Fail rather than
            # store a whole board of empty jobs.
            raise ValueError(
                f"deel: {len(refs)} description references on {task.board}, none resolved"
            )
        yield [self.stub(p, rows, org or name_from_slug(task.board), task.board) for p in postings]

    @staticmethod
    def stub(p: dict[str, Any], rows: dict[str, str], company: str, board: str) -> JobStub:
        desc = (
            rows.get(p["richtextDescription"][1:], "")
            if _is_ref(p)
            else p.get("richtextDescription")
        )
        places = [
            jl["location"]["name"]
            for jl in (p.get("job") or {}).get("jobLocations") or []
            if (jl.get("location") or {}).get("name")
        ]
        location = ", ".join(dict.fromkeys(places))
        url = JOB.format(board=board, id=p["id"])
        return JobStub(
            source="deel",
            url=url,
            title=(p.get("title") or "").strip(),
            company=company,
            location=location,
            description=html_to_text(desc or ""),
            posted_at=from_iso(p.get("createdAt")),
            ats="deel",
            apply_url=url,
            remote=remote_from_text(p.get("title"), location),
            extra={"board": board, "id": p["id"]},
        )


def _is_ref(p: dict[str, Any]) -> bool:
    return str(p.get("richtextDescription") or "").startswith("$")
