"""Huntflow career sites ({board}.huntflow.io): a Nuxt app whose vacancy data is a devalue-encoded
_payload.json (a flat array whose object and array members are indices into it). The list holds
no description, so the body comes from each vacancy's own payload. Logic adapted from freehire
(MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f13 import name_from_slug
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

LIST = "https://{board}.huntflow.io/_payload.json"
DETAIL = "https://{board}.huntflow.io/vacancy/{slug}/_payload.json"
VACANCY = "https://{board}.huntflow.io/vacancy/{slug}"
_URL = re.compile(r"//([\w-]+)\.huntflow\.io/vacancy/([^/?#]+)", re.I)


def unflatten(raw: list[Any]) -> Any:
    """Resolve a devalue array: an object's values and an array's elements that are integers are
    indices into `raw`; other values are literal. A string-headed array is a type wrapper
    (e.g. ["ShallowReactive", 3]) and resolves to the value it wraps."""
    memo: dict[int, Any] = {}

    def hydrate(i: int) -> Any:
        if not 0 <= i < len(raw):
            return None
        if i in memo:
            return memo[i]
        memo[i] = None  # a reference cycle resolves to null instead of recursing forever
        tok = raw[i]
        out: Any = tok
        if isinstance(tok, dict):
            out = {k: ref(v) for k, v in tok.items()}
        elif isinstance(tok, list):
            if tok and isinstance(tok[0], str):
                out = ref(tok[1]) if len(tok) > 1 else None
            else:
                out = [ref(v) for v in tok]
        memo[i] = out
        return out

    def ref(v: Any) -> Any:
        return hydrate(v) if isinstance(v, int) and not isinstance(v, bool) else v

    return hydrate(0)


def find_vacancy(node: Any) -> dict[str, Any] | None:
    """The detail payload's vacancy: the object that has both a body and a position. Walking for
    it keeps this working when Nuxt nests the route state differently."""
    if isinstance(node, dict):
        if "body" in node and "position" in node:
            return node
        node = list(node.values())
    if isinstance(node, list):
        for v in node:
            if (found := find_vacancy(v)) is not None:
                return found
    return None


class Huntflow(Source):
    name = "huntflow"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.huntflow\.io", re.I),)
    parallel = 2  # public JSON payloads; Http paces per host

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one payload holds every vacancy
            return
        board = task.board
        data = unflatten(await http.get_json(LIST.format(board=board)))
        items = (((data or {}).get("data") or {}).get("vacancies") or {}).get("items") or []
        yield [
            JobStub(
                source=self.name,
                url=VACANCY.format(board=board, slug=it["slug"]),
                title=(it.get("position") or "").strip(),
                company=name_from_slug(board),
                location=(it.get("city") or "").strip(),
                ats=self.name,
                apply_url=VACANCY.format(board=board, slug=it["slug"]),
                extra={"board": board, "id": str(it.get("id")), "slug": it["slug"]},
            )
            for it in items
            if it.get("slug") and not it.get("archived_at")  # archived = closed
        ]

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m or stub.description:
            return stub
        vac = find_vacancy(unflatten(await http.get_json(DETAIL.format(board=m[1], slug=m[2]))))
        if vac is None:
            return stub
        keys = ("intro", "body", "requirements", "conditions")
        body = "".join(str(vac.get(k) or "") for k in keys)
        if vac.get("money"):  # no salary field here: keep the money line in the text
            body = f"<p>{vac['money']}</p>{body}"
        return stub.model_copy(
            update={
                "description": html_to_text(body),
                "location": str(vac.get("city") or stub.location).strip(),
            }
        )
