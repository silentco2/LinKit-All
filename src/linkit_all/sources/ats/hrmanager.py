"""HR-Manager (hr-manager.net), the Danish ATS: its public job-portal API lists a customer's
postings with their advertisement HTML in one call. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from linkit_all.sources.ats._f12 import name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://api.hr-manager.net/jobportal.svc/{board}/positionlist/json/"
TAKE = 2000  # without `take` the API answers 25 rows; one request must cover the whole customer
_ALIAS = re.compile(r"^[A-Za-z0-9_-]+$")
_DATE = re.compile(r"^/Date\((-?\d+)(?:[+-]\d{4})?\)/$")  # .NET JSON date, epoch milliseconds


def _date(value: str | None) -> datetime | None:
    m = _DATE.match(value or "")
    # A non-positive epoch is .NET's DateTime.MinValue: "never set".
    if not m or int(m[1]) <= 0:
        return None
    return datetime.fromtimestamp(int(m[1]) / 1000, UTC).replace(tzinfo=None)


class HrManager(Source):
    """The board is the customer alias in the portal API, e.g. `energinet`. A posting URL
    carries only the customer's numeric cid, which the API does not accept, so only the API
    and embed URLs are recognised."""

    name = "hrmanager"
    kind = "ats"
    url_patterns = (re.compile(r"hr-manager\.net/jobportal\.svc/([\w-]+)", re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        board = task.board
        if not _ALIAS.match(board):
            raise ValueError(f"hrmanager: {board!r} is not a customer alias")
        r = await http.get_json(API.format(board=board), params={"incads": 1, "take": TAKE})
        status = (r.get("TransactionStatus") or {}).get("StatusCode")
        if status != 0:
            desc = " ".join(str((r.get("TransactionStatus") or {}).get("Description", "")).split())
            raise ValueError(f"hrmanager: {board!r}: status {status} ({desc})")
        if (r.get("CustomerAlias") or "").lower() != board.lower():
            raise ValueError(
                f"hrmanager: {board!r}: listing names customer {r.get('CustomerAlias')!r}"
            )
        items = r.get("Items") or []
        if (r.get("PositionCountSearch") or 0) > TAKE or len(items) != r.get("PositionCountList"):
            raise ValueError(
                f"hrmanager: {board!r}: read {len(items)} rows, more than one request holds"
            )
        company = r.get("CustomerName") or name_from_slug(board)
        yield [
            s
            for it in items
            if it.get("ProjectType") != "OpenApplication" and (s := self.stub(it, board, company))
        ]

    @staticmethod
    def stub(it: dict[str, Any], board: str, company: str) -> JobStub | None:
        title = " ".join((it.get("Name") or "").split())
        url = it.get("AdvertisementUrl")
        if not it.get("Id") or not title or not url:
            return None
        # Every posting carries one advertisement; the first with a body is read.
        body = next(
            (
                (ad.get("Introduction") or "") + ad["Content"]
                for ad in it.get("Advertisements") or []
                if (ad.get("Content") or "").strip()
            ),
            "",
        )
        names = [n.get("Name", "").strip() for n in it.get("PositionLocationMultiSelection") or []]
        dept = it.get("Department") or {}
        location = (
            (it.get("WorkPlace") or "").strip()
            or "; ".join(dict.fromkeys(n for n in names if n))
            or (dept.get("City") or "").strip()
        )
        return JobStub(
            source="hrmanager",
            url=url,
            title=title,
            company=company,
            location=location,
            description=html_to_text(body),
            posted_at=_date(it.get("Published")) or _date(it.get("Created")),
            ats="hrmanager",
            apply_url=url,
            remote=remote_from_text(location),
            extra={"board": board, "id": str(it["Id"])},
        )
