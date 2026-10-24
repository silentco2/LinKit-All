"""Cornerstone OnDemand career sites ({tenant}.csod.com): the home shell embeds a read token.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from linkit_all.sources.ats._f12 import get_page, name_from_slug
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

HOME = "https://{board}.csod.com/ux/ats/careersite/1/home?c={board}"
PAGE_SIZE = 100
MAX_SITES = 40  # a tenant may run several career sites and nothing lists them; most use site 1
_CLOUD = re.compile(r'"endpoints"\s*:\s*\{[^}]*"cloud"\s*:\s*"(https?://[^"]+)"')
_TOKEN = re.compile(r'"token"\s*:\s*"(eyJ[^"]+)"')
_CULTURE_ID = re.compile(r'"cultureID"\s*:\s*(\d+)', re.I)
_CULTURE_NAME = re.compile(r'"cultureName"\s*:\s*"([^"]+)"', re.I)


class Cornerstone(Source):
    """The board is the tenant subdomain: `nintendoeurope` for nintendoeurope.csod.com."""

    name = "cornerstone"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.csod\.com", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board
        home = (await get_page(http, HOME.format(board=board))).text
        cloud, token = _CLOUD.search(home), _TOKEN.search(home)
        if not cloud or not token:
            raise ValueError(f"cornerstone: no API endpoint or token on the {board} home page")
        culture_id, culture_name = _CULTURE_ID.search(home), _CULTURE_NAME.search(home)
        api = cloud[1].rstrip("/") + "/rec-job-search/external/jobs"
        headers = {"Authorization": f"Bearer {token[1]}"}
        cid = int(culture_id[1]) if culture_id else 1
        cname = culture_name[1] if culture_name else "en-US"
        seen: set[int] = set()
        yielded = 0
        # ponytail: probes every site id on each run, ~40 requests per board; remember which
        # ids answered if that gets slow. A resumed run skips the pages already stored.
        for site in range(1, MAX_SITES + 1):
            try:
                reqs = await self._site(http, api, headers, site, cid, cname)
            except Exception:
                if site == 1:
                    raise
                continue  # a later site failing costs that site, not the board
            fresh = [r for r in reqs if r.get("requisitionId") and r["requisitionId"] not in seen]
            seen.update(r["requisitionId"] for r in fresh)
            if not fresh:
                continue
            yielded += 1
            if yielded > start_page:
                yield [self.stub(r, board, site) for r in fresh]

    async def _site(
        self, http: Http, api: str, headers: dict[str, str], site: int, cid: int, cname: str
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for number in range(1, 101):
            body = {
                "careerSiteId": site,
                "careerSitePageId": site,
                "pageNumber": number,
                "pageSize": PAGE_SIZE,
                "cultureId": cid,
                "cultureName": cname,
                "searchText": "",
                "states": [],
                "countryCodes": [],
                "cities": [],
                "customFieldCheckboxKeys": [],
                "customFieldDropdowns": [],
                "customFieldRadios": [],
            }
            try:
                data = (await http.post_json(api, body, headers=headers))["data"]
            except Exception:
                if number == 1:
                    raise
                break  # a later page failing ends the site with what it has
            out += data.get("requisitions") or []
            if not data.get("requisitions") or len(out) >= data.get("totalCount", 0):
                break
        return out

    @staticmethod
    def stub(r: dict[str, Any], board: str, site: int) -> JobStub:
        loc = (r.get("locations") or [{}])[0]
        location = ", ".join(p for p in (loc.get("city"), loc.get("country")) if p and p.strip())
        url = (
            f"https://{board}.csod.com/ux/ats/careersite/{site}/home/requisition/"
            f"{r['requisitionId']}?c={board}"
        )
        try:
            posted = datetime.strptime(r.get("postingEffectiveDate") or "", "%m/%d/%Y")
        except ValueError:
            posted = None
        return JobStub(
            source="cornerstone",
            url=url,
            title=(r.get("displayJobTitle") or "").strip(),
            company=name_from_slug(board),
            location=location,
            description=html_to_text(r.get("externalDescription") or ""),
            posted_at=posted,
            ats="cornerstone",
            apply_url=url,
            extra={"board": board, "id": r["requisitionId"], "site": site},
        )
