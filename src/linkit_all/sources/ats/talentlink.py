"""Lumesse TalentLink (Cornerstone) career sites of the "FO widget" generation. The board is the
career page's address ({tenant}.recruitmentplatform.com/.../index.html, or a page on the
employer's own domain given as "talentlink:https://..."). The page names the API host and the
site id; the widget then calls that API with the fixed guest login every visitor's browser
sends. Postings come 100 a page, newest first, description sections inline. Which numbered
list fields hold the location is told only by the tenant's search criteria.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin, urlsplit

from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, mode, name_from_host, safe_date, text_of

PAGE = 100
MAX_PAGES = 200
_FO_HOST = re.compile(r'data-(?:lumesse|talentlink)-fo-host="(?:https://)?([^"/]+)')
_SITE = re.compile(r'data-(?:lumesse-site|talentlink-fo-site)-tech-id="([A-Z0-9]{10,40})"')
_ALLOWED = re.compile(
    r"^[a-z0-9][a-z0-9-]*\.(?:recruitmentplatform|lumessetalentlink|sabatalentlink)\.com$"
)
# Names tenants give the list that holds a place, in the languages seen.
_PLACE_LIST = re.compile(
    r"locat|countr|city|county|region|destination|based at|office|standort|\bland\b|\bort\b|pays"
    r"|ville|lieu|sede|ubicaci|pa[ií]s|ciudad|citt[aà]|miasto|lokalizac",
    re.I,
)


def place_fields(criteria: Any) -> tuple[set[str], dict[str, list[str]]]:
    """(the SLOVLIST fields that hold a place, {place label: labels it is bound to}). A city
    can be bound to its country in another list; the bound label is added to the location."""
    fields: set[str] = set()
    bound: dict[str, list[str]] = {}
    lists = {
        k: v["items"]
        for k, v in (criteria if isinstance(criteria, dict) else {}).items()
        if isinstance(v, dict) and isinstance(v.get("items"), list)
    }
    labels = {
        it.get("value"): clean(it["label"])
        for items in lists.values()
        for it in items
        if isinstance(it, dict) and isinstance(it.get("label"), str)
    }
    for key, items in lists.items():
        m = re.fullmatch(r"LOV(\d+)", key)
        if not m or not _PLACE_LIST.search(str(criteria[key].get("lovName") or "")):
            continue
        fields.add(f"SLOVLIST{m[1]}")
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("bindTo"), list) and it.get("label"):
                targets = [labels[v] for v in it["bindTo"] if labels.get(v)]
                if targets:
                    bound[clean(it["label"]).lower()] = targets
    return fields, bound


class TalentLink(Source):
    name = "talentlink"
    kind = "ats"
    url_patterns = (
        re.compile(
            r"(?<![\w.-])([a-z0-9][a-z0-9-]*\.recruitmentplatform\.com/(?:[\w-]+/)*[\w-]+\.html?)",
            re.I,
        ),
    )

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        page_url = task.board if task.board.startswith("http") else f"https://{task.board}"
        html = (await get_page(http, page_url)).text
        host, site = _FO_HOST.search(html), _SITE.search(html)
        if not host or not site or not _ALLOWED.match(host[1].lower()):
            raise ValueError("talentlink: the page names no TalentLink API host and site id")
        api = f"https://{host[1].lower()}/fo/rest"
        # The widget's own guest login, the same for every visitor; not a secret.
        headers = {
            "Accept": "application/json",
            "username": f"{site[1]}:guest:FO",
            "password": "guest",
        }
        config = await http.get_json(f"{api}/config", headers=headers)
        detail = urljoin(
            page_url, str((config.get("navigationPages") or {}).get("jobDescriptionURL") or "")
        )
        fields, bound = place_fields(await http.get_json(f"{api}/jobs/criteria", headers=headers))
        company = name_from_host(urlsplit(page_url).hostname or "")
        for page in range(start_page, MAX_PAGES):
            params = {
                "firstResult": page * PAGE,
                "maxResults": PAGE,
                "sortBy": "DPOSTINGSTART",
                "sortOrder": "desc",
            }
            data = await http.post_json(
                f"{api}/jobs", {"searchCriteria": {}}, params=params, headers=headers
            )
            rows = data.get("jobs") if isinstance(data, dict) else None
            if not isinstance(rows, list):  # an empty board answers without `jobs`
                return
            stubs = [
                s
                for r in rows
                if isinstance(r, dict)
                and (s := self.stub(r, task.board, company, detail, fields, bound))
            ]
            if stubs:
                yield stubs
            if len(rows) < PAGE:
                return

    @staticmethod
    def stub(
        r: dict[str, Any],
        board: str,
        company: str,
        detail: str,
        fields: set[str],
        bound: dict[str, list[str]],
    ) -> JobStub | None:
        f: dict[str, Any] = r["jobFields"] if isinstance(r.get("jobFields"), dict) else {}
        jid, title = str(r.get("id") or f.get("id") or ""), clean(f.get("jobTitle"))
        if not jid.isdigit() or not title:
            return None
        places = [
            clean(v) for k, v in f.items() if k in fields and isinstance(v, str) and v.strip()
        ]
        places += [t for p in list(places) for t in bound.get(p.lower(), [])]
        work = mode(str(f.get("WorkMode") or ""))
        parts = []
        for c in r.get("customFields") or []:
            body = text_of(c.get("content")) if isinstance(c, dict) else ""
            if body:
                parts.append(f"{clean(c.get('title'))}\n{body}" if clean(c.get("title")) else body)
        url = f"{detail}?jobId={jid}"
        return JobStub(
            source="talentlink",
            url=url,
            title=title,
            company=company,
            location="; ".join(dict.fromkeys(places)),
            description="\n\n".join(parts),
            posted_at=safe_date(f.get("DPOSTINGSTART")),
            ats="talentlink",
            apply_url=str(f.get("applicationUrl") or url),
            remote=work,
            extra={"board": board, "id": jid, "req": f.get("jobNumber")},
        )
