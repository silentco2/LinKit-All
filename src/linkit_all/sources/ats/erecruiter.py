"""eRecruiter (skk.erecruiter.pl, Poland) "Strona Kariera" boards: a JSONP list of offer rows, then
one Offer.aspx page per offer for the text. Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlsplit

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import fetch_all, get_page, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug

BASE = "https://skk.erecruiter.pl"
MAX_PAGES = 500
_DROP = ("JobTitle", "WorkPlace", "Clause")  # header (read separately) and the consent text


def parse_rows(body: str) -> tuple[list[dict[str, str]], int, int]:
    """Offer rows from the `({"htm": "<tr>..."});` body, then the total and page size that the
    hidden marker row reports (0 when absent)."""
    text = body.strip().rstrip(";").strip()
    text = text.removeprefix("(").removesuffix(")")
    if not text:
        return [], 0, 0
    tree = LexborHTMLParser("<table>" + json.loads(text).get("htm", "") + "</table>")
    rows, total, size = [], 0, 0
    for tr in tree.css("tr"):
        attrs = {k.lower(): v or "" for k, v in tr.attributes.items()}
        if attrs.get("skkresult") != "offer":
            if attrs.get("tr", "").isdigit():
                total, size = int(attrs["tr"]), int(attrs.get("ps") or 0)
            continue
        if not attrs.get("offerid"):
            continue
        cells = tr.css("td")
        name = tr.css_first("td.skk_positionName")
        rows.append(
            {
                "oid": attrs["offerid"],
                "ejoid": attrs.get("externaljobofferid", ""),
                "ejorid": attrs.get("externaljobofferregionid", ""),
                "comid": attrs.get("comid", ""),
                "title": " ".join(name.text().split()) if name else "",
                "city": " ".join(cells[-1].text().split()) if cells else "",
            }
        )
    return rows, total, size


def offer_url(cfg: str, row: dict[str, str]) -> str:
    return (
        f"{BASE}/Offer.aspx?oid={row['oid']}&cfg={cfg}"
        f"&ejoId={row['ejoid']}&ejorId={row['ejorid']}&comId={row['comid']}"
    )


def parse_offer(html: str) -> tuple[str, str, str]:
    """(title, location, description) of an Offer.aspx page; empty strings for what is missing."""
    tree = LexborHTMLParser(html)

    def text(i: str) -> str:
        n = tree.css_first(f"#{i}")
        return " ".join(n.text().split()) if n else ""

    title = text("JobTitle")
    place = text("WorkPlace")  # "Miejsce pracy: Łódź" (or "Workplace: ..."): keep the value
    place = place.partition(":")[2].strip() if ":" in place else place
    offer = tree.css_first("#offCont")
    if offer is not None:
        for i in _DROP:
            for n in offer.css(f"#{i}"):
                n.decompose()
        markup = offer.html or ""
    else:  # a template without the standard container
        markup = "".join(
            sec.html or "" for i in ("t1", "Opportunities", "CompanyDescription")
            if (sec := tree.css_first(f"#{i}")) is not None
        )  # fmt: skip
    return title, place, strip_html(markup)


def offer_stub(html: str, url: str, row: dict[str, str], board: str) -> JobStub | None:
    title, place, description = parse_offer(html)
    title, place = title or row["title"], place or row["city"]
    if not title or not description:  # a dead or closed offer
        return None
    company = board.partition("/")[2]
    return JobStub(
        source="erecruiter",
        url=url,
        title=title,
        company=name_from_slug(company) if company else "Unknown",
        location=place,
        description=description,
        ats="erecruiter",
        apply_url=url,
        remote=remote_from_text(place),
        extra={"board": board, "id": row["oid"]},
    )


class ERecruiter(Source):
    """The board is the company's 32-hex `cfg` token, from the `Code.ashx?cfg=` widget script on
    its careers page. Add `/<company-name>` (`<cfg>/acme`) to name the employer, which the feed
    does not."""

    name = "erecruiter"
    kind = "ats"
    url_patterns = (re.compile(r"erecruiter\.pl/\w+\.ashx\?cfg=([0-9a-f]{32})", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        cfg = task.board.partition("/")[0]
        if not re.fullmatch(r"[0-9a-fA-F]{32}", cfg):
            raise ValueError(f"erecruiter: board {task.board!r} must start with a 32-hex cfg token")
        for page in range(start_page + 1, MAX_PAGES + 1):
            body = (await get_page(http, f"{BASE}/GetHtml.ashx?cfg={cfg}&grid=rows&pn={page}")).text
            rows, total, size = parse_rows(body)
            if not rows:
                return
            by_url = {offer_url(cfg, r): r for r in rows}

            yield await fetch_all(
                http,
                list(by_url),
                lambda h, u, m=by_url: offer_stub(h, u, m[u], task.board),  # type: ignore[misc]
            )
            if total and size and page * size >= total:  # the marker says this was the last page
                return

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if "oid" not in parse_qs(urlsplit(stub.url).query):
            return stub
        _, _, description = parse_offer((await get_page(http, stub.url)).text)
        return stub.model_copy(update={"description": description}) if description else stub
