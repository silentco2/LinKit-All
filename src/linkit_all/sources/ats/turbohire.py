"""TurboHire careers sites ({board}.turbohire.co). The page is a client-side app; this makes
the same three keyless requests it makes for every visitor: the anonymous token (answered only
with the careers page's Origin and Referer), the tenant's org id, then every public posting in
one response, body inline. Only the public careers page (pageType 0) is ever asked for.
Logic adapted from career-ops (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, name_from_slug, safe_date

API = "https://thapi.azurewebsites.net/api"
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_NIL = "00000000-0000-0000-0000-000000000000"
_HIDDEN = "[REDACTED]"  # ClientName of a posting that hides its end employer


class TurboHire(Source):
    name = "turbohire"
    kind = "ats"
    url_patterns = (
        re.compile(r"(?<![\w.-])(?!(?:app|api|www)\.)([a-z0-9][a-z0-9-]*)\.turbohire\.co\b", re.I),
    )
    cdx_hosts = ("*.turbohire.co",)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one response holds the whole board
            return
        board = task.board.lower()
        origin = f"https://{board}.turbohire.co"
        got = await http.get_json(
            f"{API}/token/noauth", headers={"Origin": origin, "Referer": f"{origin}/"}
        )
        token = str((got or {}).get("access_token") or "").strip()
        if not token:
            raise ValueError("turbohire: the anonymous token request returned no token")
        auth = {"Authorization": f"Bearer {token}"}
        resp = await http.get(
            f"{API}/publicorganizations", params={"accountName": board}, headers=auth
        )
        if resp.status_code == 404:
            raise Unsupported(f"turbohire: no tenant named {board}")
        resp.raise_for_status()
        org = str((resp.json() or {}).get("OrgID") or "")
        if not _GUID.match(org) or org == _NIL:
            raise ValueError("turbohire: the organization lookup returned no org id")
        data = await http.post_json(
            f"{API}/careerpagev2/filteredjobs",
            {},
            params={"orgId": org, "pageType": 0},
            headers=auth,
        )
        rows = data.get("Result") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ValueError("turbohire: the response carries no Result array")
        stubs = [s for r in rows if isinstance(r, dict) and (s := self.stub(r, board))]
        stubs = list({s.url: s for s in stubs}.values())
        if stubs:
            yield stubs

    @staticmethod
    def location(raw: Any) -> str:
        """`Location` is a JSON array of sites (as text or already parsed), or plain text."""
        if isinstance(raw, str):
            text = raw.strip()
            try:
                raw = json.loads(text)
            except ValueError:
                return "" if text[:1] in ("[", "{") else clean(text)
        if not isinstance(raw, list):
            return ""
        places = (clean(s.get("Address")) for s in raw if isinstance(s, dict))
        return "; ".join(dict.fromkeys(p for p in places if p))

    @classmethod
    def stub(cls, r: dict[str, Any], board: str) -> JobStub | None:
        title, jid = clean(r.get("JobTitle")), str(r.get("JobIdObfuscated") or "").strip()
        if not title or not jid:
            return None
        url = f"https://{board}.turbohire.co/job/publicjobs/{quote(jid, safe='')}"
        client = clean(r.get("ClientName")) if r.get("ShowClientName") is True else ""
        where = cls.location(r.get("Location"))
        return JobStub(
            source="turbohire",
            url=url,
            title=title,
            company=client if client and client != _HIDDEN else name_from_slug(board),
            location=where,
            description=strip_html(r.get("JobDescV2") or ""),
            posted_at=safe_date(r.get("PublishedDate")),
            ats="turbohire",
            apply_url=url,
            remote=remote_from_text(where),
            extra={"board": board, "id": jid, "code": r.get("JobCode")},
        )
