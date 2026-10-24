"""MokaHR (Moka), a Chinese multi-tenant ATS: every tenant careers site calls one keyless JSON
listing whose rows carry the whole posting with its HTML body. app.mokahr.com wraps the answer in
AES-CBC with the key sent in the same response (hire-r1.mokahr.com answers plain JSON); that is the
site's own transport encoding, read here exactly as its page does. Logic adapted from freehire
(MIT)."""

import base64
import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from linkit_all.sources.ats._f13 import name_from_slug
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

PATH = "/api/outer/ats-apply/website/jobs/v2"
PAGE_SIZE = 50  # the listing's ceiling: 51 and above answer code 102
MAX_PAGES = 100
IV = b"de7c21ed8d6f50fe"  # published in every tenant page's init-data; the same on all of them
_BOARD = re.compile(r"^(?:(r1)/)?([A-Za-z0-9_-]+)/([1-9][0-9]*)$")
CHINA = timezone(timedelta(hours=8))  # tenants write zone-less timestamps in China time
# The row names a district only; the first four digits of its city code give the city in English.
CITIES = {
    "1101": "Beijing", "3101": "Shanghai", "1201": "Tianjin", "5001": "Chongqing",
    "3301": "Hangzhou", "4403": "Shenzhen", "4401": "Guangzhou", "5101": "Chengdu",
    "3502": "Xiamen", "3201": "Nanjing", "4201": "Wuhan", "6101": "Xi'an", "3205": "Suzhou",
    "8100": "Hong Kong",
}  # fmt: skip


def decrypt(envelope: dict[str, Any]) -> Any:
    """Open `{"data": base64 ciphertext, "necromancer": 16-byte key}`: AES-128-CBC, PKCS#7."""
    key = str(envelope["necromancer"]).encode()
    raw = base64.b64decode(envelope["data"])
    dec = Cipher(algorithms.AES(key), modes.CBC(IV)).decryptor()
    unpad = padding.PKCS7(128).unpadder()
    try:
        plain = unpad.update(dec.update(raw) + dec.finalize()) + unpad.finalize()
    except ValueError as exc:  # bad padding: the IV or the scheme changed
        raise ValueError("mokahr: could not decrypt the listing (the site changed)") from exc
    return json.loads(plain)


def _place(loc: dict[str, Any]) -> str:
    code = str(loc.get("cityId") or "")
    city = CITIES.get(code[:4]) if len(code) == 6 else None
    return city or ", ".join(x for x in (loc.get("cityName"), loc.get("provinceName")) if x)


def _opened(value: str | None) -> datetime | None:
    try:
        dt = datetime.strptime(value or "", "%Y-%m-%dT%H:%M").replace(tzinfo=CHINA)
    except ValueError:
        return None
    return dt.astimezone(UTC).replace(tzinfo=None)


class MokaHR(Source):
    """The board is `<orgId>/<siteId>` (`high-flyer/140576`); `r1/<orgId>/<siteId>` for the
    international deployment on hire-r1.mokahr.com."""

    name = "mokahr"
    kind = "ats"
    url_patterns = (
        re.compile(r"app\.mokahr\.com/(?:social-recruitment|apply)/([\w-]+)/(\d+)", re.I),
        re.compile(r"hire-(r1)\.mokahr\.com/(?:social-recruitment|apply)/([\w-]+)/(\d+)", re.I),
    )

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        m = _BOARD.match(task.board.strip())
        if not m:
            raise ValueError(f"mokahr: board {task.board!r} is not <orgId>/<siteId>")
        region, org, site = m.groups()
        host = "hire-r1.mokahr.com" if region else "app.mokahr.com"
        company = name_from_slug(org)
        for page in range(start_page, MAX_PAGES):
            body = {
                "siteId": int(site),
                "orgId": org,
                "locale": "zh-CN",
                "limit": PAGE_SIZE,
                "offset": page * PAGE_SIZE,
            }
            data = await http.post_json(f"https://{host}{PATH}", body)
            if isinstance(data.get("data"), str):  # a string is the ciphertext of the whole body
                data = decrypt(data)
            jobs = (data.get("data") or {}).get("jobs")
            if not data.get("success") or jobs is None:
                raise ValueError(f"mokahr: {task.board}: code {data.get('code')} {data.get('msg')}")
            row_url = f"https://{host}/social-recruitment/{org}/{site}"
            yield [s for j in jobs if (s := self.stub(j, row_url, task.board, company))]
            if len(jobs) < PAGE_SIZE:  # no total is given: a short page is the end
                return

    @staticmethod
    def stub(j: dict[str, Any], site_url: str, board: str, company: str) -> JobStub | None:
        title = " ".join(str(j.get("title") or "").split())
        text = strip_html(j.get("jobDescription") or "")
        if j.get("status") != "open" or not j.get("id") or not title or not text:
            return None  # a paused posting is listed but takes no applications
        url = f"{site_url}#/job/{j['id']}"
        places = dict.fromkeys(p for loc in j.get("locations") or [] if (p := _place(loc)))
        return JobStub(
            source="mokahr",
            url=url,
            title=title,
            company=company,
            location="; ".join(places),
            description=text,
            posted_at=_opened(j.get("openedAt")),
            ats="mokahr",
            apply_url=url,
            extra={
                "board": board,
                "id": str(j["id"]),
                "employment": j.get("commitment"),
                "function": (j.get("zhineng") or {}).get("name"),
            },
        )
