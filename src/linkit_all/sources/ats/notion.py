"""Careers boards published as public Notion pages ({workspace}.notion.site/...{page id}). The
board is "workspace/pageid". The official Notion API cannot read a stranger's public page, so
this reads the keyless endpoints the published page itself calls (undocumented, so every shape
is checked and a change fails loudly). Two board shapes: a database (one posting per row, the
view's own filter applied, a "Location" column read) or a page whose child pages are the
postings. A posting's address is its bare page id, which survives title edits; its date is the
page's creation time. Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator, Iterable
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug

CHUNK_LIMIT = 100
ROW_LIMIT = 200
MAX_DEPTH = 3
_DB = {"collection_view_page", "collection_view"}
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def as_uuid(hex32: str) -> str:
    h = hex32.replace("-", "").lower()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def unwrap(rec: Any) -> dict[str, Any] | None:
    """A record's block, in either wrapping: {role, value} or {spaceId, value: {role, value}}."""
    value = rec.get("value") if isinstance(rec, dict) else None
    if isinstance(value, dict) and isinstance(value.get("value"), dict) and "role" in value:
        value = value["value"]
    return value if isinstance(value, dict) else None


def rich_text(prop: Any) -> str:
    if not isinstance(prop, list):
        return ""
    return "".join(
        s[0] for s in prop if isinstance(s, list) and s and isinstance(s[0], str)
    ).strip()


def mentioned(prop: Any) -> Iterable[str]:
    """Page ids linked inline ("‣") in a rich-text property."""
    for seg in prop if isinstance(prop, list) else []:
        for a in (
            seg[1] if isinstance(seg, list) and len(seg) > 1 and isinstance(seg[1], list) else []
        ):
            if isinstance(a, list) and len(a) > 1 and a[0] == "p" and isinstance(a[1], str):
                yield a[1]


class Notion(Source):
    name = "notion"
    kind = "ats"
    url_patterns = (
        re.compile(
            r"(?<![\w.-])([a-z0-9-]+)\.notion\.site/(?:[^\s\"'<>?#]*?[-/])?([0-9a-f]{32})(?![0-9a-f])",
            re.I,
        ),
    )

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one board, read in one go
            return
        workspace, _, page_hex = task.board.partition("/")
        origin, page_id = f"https://{workspace.lower()}.notion.site", as_uuid(page_hex)
        company = name_from_slug(workspace)
        chunk = await http.post_json(
            f"{origin}/api/v3/loadPageChunk",
            {
                "pageId": page_id,
                "limit": CHUNK_LIMIT,
                "cursor": {"stack": []},
                "chunkNumber": 0,
                "verticalColumns": False,
            },
        )
        blocks = ((chunk or {}).get("recordMap") or {}).get("block")
        if not isinstance(blocks, dict):
            raise ValueError("notion: loadPageChunk carries no recordMap.block")
        root = unwrap(blocks.get(page_id))
        if root is None:
            raise ValueError(f"notion: page {page_id} is not public or the id is wrong")
        content = [c for c in root.get("content") or [] if isinstance(c, str)]
        db = (
            root
            if root.get("type") in _DB
            else next(
                (b for c in content if (b := unwrap(blocks.get(c))) and b.get("type") in _DB), None
            )
        )
        if db is not None:
            stubs = await self._rows(http, origin, chunk, db, blocks, page_id, task.board, company)
        elif root.get("type") == "page":
            stubs = self._child_pages(blocks, content, origin, task.board, company)
        else:
            raise ValueError(f"notion: page {page_id} is a {root.get('type')!r} block")
        if stubs:
            yield stubs

    async def _rows(
        self,
        http: Http,
        origin: str,
        chunk: dict[str, Any],
        db: dict[str, Any],
        blocks: dict[str, Any],
        page_id: str,
        board: str,
        company: str,
    ) -> list[JobStub]:
        collection = db.get("collection_id") or (
            (db.get("format") or {}).get("collection_pointer") or {}
        ).get("id")
        views = [v for v in db.get("view_ids") or [] if isinstance(v, str)]
        space = db.get("space_id") or (blocks.get(page_id) or {}).get("spaceId")
        if not (isinstance(collection, str) and views and isinstance(space, str)):
            raise ValueError("notion: the database has no collection, view or space id")
        view = unwrap(((chunk.get("recordMap") or {}).get("collection_view") or {}).get(views[0]))
        if view is None:
            raise ValueError("notion: the database view is missing (its filter cannot be applied)")
        query = view.get("query2") or {}
        loader: dict[str, Any] = {
            "type": "reducer",
            "reducers": {"collection_group_results": {"type": "results", "limit": ROW_LIMIT}},
            "sort": query.get("sort") if isinstance(query.get("sort"), list) else [],
            "searchQuery": "",
            "userTimeZone": "UTC",
        }
        if isinstance(query.get("filter"), dict):
            loader["filter"] = query["filter"]
        result = await http.post_json(
            f"{origin}/api/v3/queryCollection?src=initial_load",
            {
                "source": {"type": "collection", "id": collection, "spaceId": space},
                "collectionView": {"id": views[0], "spaceId": space},
                "loader": loader,
            },
        )
        reducers = ((result or {}).get("result") or {}).get("reducerResults") or {}
        ids = (reducers.get("collection_group_results") or {}).get("blockIds")
        if not isinstance(ids, list):
            raise ValueError("notion: queryCollection carries no blockIds")
        record = result.get("recordMap") or {}
        schema = (unwrap((record.get("collection") or {}).get(collection)) or {}).get(
            "schema"
        ) or {}
        place_key = next(
            (
                k
                for k, v in schema.items()
                if re.fullmatch(r"locations?", str((v or {}).get("name", "")).strip(), re.I)
            ),
            None,
        )
        rows = record.get("block") or {}
        stubs = []
        for rid in ids:
            block = unwrap(rows.get(rid))
            where = (
                rich_text(((block or {}).get("properties") or {}).get(place_key))
                if place_key
                else ""
            )
            if stub := self.stub(block, origin, board, company, where):
                stubs.append(stub)
        return stubs

    def _child_pages(
        self, blocks: dict[str, Any], content: list[str], origin: str, board: str, company: str
    ) -> list[JobStub]:
        found: dict[str, JobStub] = {}

        def add(block: dict[str, Any] | None) -> None:
            if (
                block
                and block.get("type") == "page"
                and block.get("id") not in found
                and (stub := self.stub(block, origin, board, company, ""))
            ):
                found[str(block["id"])] = stub

        def walk(ids: list[str], depth: int) -> None:
            for bid in ids:
                block = unwrap(blocks.get(bid))
                if block is None or block.get("alive") is False:
                    continue
                if block.get("type") == "page":
                    add(block)
                elif block.get("type") == "alias":
                    pointer = ((block.get("format") or {}).get("alias_pointer") or {}).get("id")
                    add(unwrap(blocks.get(pointer)) if pointer else None)
                else:
                    for pid in mentioned((block.get("properties") or {}).get("title")):
                        add(unwrap(blocks.get(pid)))
                    if depth < MAX_DEPTH:
                        walk(
                            [c for c in block.get("content") or [] if isinstance(c, str)], depth + 1
                        )

        walk(content, 0)
        return list(found.values())

    @staticmethod
    def stub(
        block: dict[str, Any] | None, origin: str, board: str, company: str, where: str
    ) -> JobStub | None:
        if not block or block.get("alive") is False:
            return None
        title, bid = (
            rich_text((block.get("properties") or {}).get("title")),
            str(block.get("id") or ""),
        )
        if not title or not _UUID.match(bid):
            return None
        url = f"{origin}/{bid.replace('-', '')}"
        created = block.get("created_time")
        return JobStub(
            source="notion",
            url=url,
            title=title,
            company=company,
            location=where,
            posted_at=from_epoch_ms(created)
            if isinstance(created, int | float) and created > 0
            else None,
            ats="notion",
            apply_url=url,
            remote=remote_from_text(where, title),
            extra={"board": board, "id": bid.replace("-", "")},
        )
