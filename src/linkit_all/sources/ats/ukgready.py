"""UKG Ready career sites (formerly Kronos Workforce Ready, hosted on saashr.com and friends): the
career page's own keyless REST API lists the requisitions and serves each body. A different product
from UKG Pro Recruiting (see ukg.py). Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import GONE, hydrate
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug
from linkit_all.sources.text import html_to_text

SIZE = 200  # the API's maximum; 250 is refused
CHUNK = 20  # postings per yielded page: their detail requests run together
_API = "https://{host}/ta/rest/ui/recruitment/companies/%7C{tenant}"  # "|tenant" is UKG's selector
_JOB = "https://{host}/ta/{tenant}.careers?ShowJob={id}"
_PERIODS = {"YEAR": "year", "MONTH": "month", "HOUR": "hour"}  # WEEK has no equivalent downstream
_HOSTS = (
    r"(?:saashr\.com|entertimeonline\.com|yourpayrollhr\.com|workforceready\.[a-z.]+|mykronos\.com)"
)


def split_board(board: str) -> tuple[str, str]:
    """ "host/tenant" -> its parts. The host selects the environment a tenant lives in, so it has
    to travel with the board; tenants are case-insensitive, so they are lower-cased."""
    host, _, tenant = board.strip("/").partition("/")
    if not host or not tenant or "/" in tenant:
        raise ValueError(f'ukgready: board {board!r} must be "<host>/<tenant>"')
    return host.lower(), tenant.lower()


def states_pay(p: dict[str, Any]) -> bool:
    return (p.get("base_pay_frequency") or "").upper() in _PERIODS and bool(
        p.get("base_pay_from") or p.get("base_pay_to")
    )


class UKGReady(Source):
    """The board is `<host>/<tenant>`, e.g. `secure4.saashr.com/6162397`."""

    name = "ukgready"
    kind = "ats"
    url_patterns = (re.compile(rf"([\w.-]+\.{_HOSTS})/ta/(\w+)\.careers", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host, tenant = split_board(task.board)
        api = _API.format(host=host, tenant=tenant)
        postings: list[dict[str, Any]] = []
        page = 1  # `offset` is a 1-based page number, not a row offset
        while True:
            try:
                data = await http.get_json(f"{api}/job-requisitions?offset={page}&size={SIZE}")
            except GONE:
                if page == 1:
                    raise
                break  # a later page failing ends the listing with what was gathered
            rows = data.get("job_requisitions") or []
            postings += [r for r in rows if r.get("id")]
            if not rows or len(postings) >= (data.get("_paging") or {}).get("total", 0):
                break
            page += 1
        currency = await self.currency(http, host, tenant, postings)
        board = f"{host}/{tenant}"

        async def build(p: dict[str, Any]) -> JobStub | None:
            try:
                detail = await http.get_json(f"{api}/job-requisitions/{p['id']}")
            except GONE:
                return None  # never store the listing's truncated preview as the description
            return self.stub(p, detail, board, currency)

        async for stubs in hydrate(postings, start_page, build, CHUNK):
            yield stubs

    @staticmethod
    async def currency(http: Http, host: str, tenant: str, postings: list[dict[str, Any]]) -> str:
        """The tenant's pay currency, asked for only when some posting states pay."""
        if not any(states_pay(p) for p in postings):
            return ""
        url = f"https://{host}/ta/rest/ui/bootstrap/companies/%7C{tenant}/format-settings"
        try:
            return str(((await http.get_json(url)).get("locale") or {}).get("currency_code") or "")
        except GONE:
            return ""

    @staticmethod
    def stub(p: dict[str, Any], detail: dict[str, Any], board: str, currency: str) -> JobStub:
        host, tenant = split_board(board)
        loc = p.get("location") or {}
        place = (loc.get("city"), loc.get("state"), loc.get("country"))
        location = ", ".join(x for x in place if x)
        period = _PERIODS.get((p.get("base_pay_frequency") or "").upper())
        # An amount is only stated with its period and currency; either missing drops it.
        paid = states_pay(p) and bool(currency)
        url = _JOB.format(host=host, tenant=tenant, id=p["id"])
        body = (detail.get("job_description") or "") + (detail.get("job_requirement") or "")
        return JobStub(
            source="ukgready",
            url=url,
            title=" ".join((p.get("job_title") or "").split()),
            company=name_from_slug(tenant),
            location=location,
            description=html_to_text(body),
            ats="ukgready",
            apply_url=url,
            remote="remote" if p.get("is_remote_job") else remote_from_text(location),
            salary_min=(p.get("base_pay_from") or None) if paid else None,
            salary_max=(p.get("base_pay_to") or None) if paid else None,
            salary_currency=currency if paid else None,
            salary_interval=period if paid else None,
            extra={
                "board": board,
                "id": str(p["id"]),
                "employment": (p.get("employee_type") or {}).get("name"),
            },
        )
