"""Hurma career sites ({board}.hurma.work): a Vue app over a paged JSON API. The list has no
description, so the body comes from each vacancy's own record. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug
from linkit_all.sources.text import html_to_text

PER_PAGE = 100
MAX_PAGES = 50
LIST = "https://{board}.hurma.work/api/v1/public-vacancies?page={page}&per_page=" + str(PER_PAGE)
DETAIL = "https://{board}.hurma.work/api/v1/public-vacancies/{id}"
# The header the site's own Vue app sends; without it the Laravel API answers an empty message.
XHR = {"X-Requested-With": "XMLHttpRequest"}
_URL = re.compile(r"//([\w-]+)\.hurma\.work/public-vacancies/(\d+)", re.I)
_TAG = re.compile(r"^#\d+\s+")  # Hurma prefixes every name with its "#<id> "
_SECTIONS = (
    ("description", ""),
    ("demand", "Requirements"),
    ("responsibility", "Responsibilities"),
    ("working_conditions", "Working conditions"),
    ("addition", ""),
)


def description(d: dict[str, Any]) -> str:
    """The vacancy's HTML sections as one text, the named ones under a heading."""
    html = ""
    for key, heading in _SECTIONS:
        if str(d.get(key) or "").strip():
            html += (f"<h3>{heading}</h3>" if heading else "") + str(d[key])
    return html_to_text(html)


class Hurma(Source):
    """The board is the employer's subdomain: `scrumlaunch` for scrumlaunch.hurma.work."""

    name = "hurma"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.hurma\.work", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = await http.get_json(LIST.format(board=board, page=page), headers=XHR)
            rows = data.get("data") or []
            stubs = []
            for it in rows:
                m = _URL.search(it.get("public_url") or "")
                if not m:  # no native id: it would collide on the dedup key
                    continue
                where, kinds = it.get("residence") or "", it.get("work_types") or ""
                stubs.append(
                    JobStub(
                        source=self.name,
                        url=it["public_url"],
                        title=_TAG.sub("", it.get("name") or "").strip(),
                        company=name_from_slug(board),
                        location=where,
                        ats=self.name,
                        apply_url=it["public_url"],
                        remote=remote_from_text(where, kinds),
                        extra={"board": board, "id": m[2], "employment": kinds},
                    )
                )
            yield stubs
            last = (data.get("meta") or {}).get("last_page")
            if (last and page >= last) or (not last and len(rows) < PER_PAGE):
                return

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m or stub.description:
            return stub
        d = (await http.get_json(DETAIL.format(board=m[1], id=m[2]), headers=XHR)).get("data") or {}
        return stub.model_copy(
            update={
                "description": description(d),
                "location": d.get("residence") or stub.location,
                "remote": stub.remote or remote_from_text(d.get("residence"), d.get("work_types")),
            }
        )
