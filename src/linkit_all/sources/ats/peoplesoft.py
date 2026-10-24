"""Oracle PeopleSoft HCM Fluid Candidate Gateway, the careers site a PeopleSoft customer serves from
its own host (universities, cities, labs): a search page whose "load more" is a form postback in
the session its first GET opened, and a page per posting. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from linkit_all.sources.ats._f12 import get_page, name_from_host
from linkit_all.sources.ats._f16 import page_text
from linkit_all.sources.ats._f17 import hydrate, post_form, text_of
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

COMPONENT = "/c/HRS_HRAM_FL.HRS_CG_SEARCH_FL.GBL"
LOAD_MORE = "HRS_AGNT_RSLT_I$hdown$0"  # the "load more" action of the result grid
MAX_POSTBACKS = 200
CHUNK = 10  # posting pages fetched together per page of stubs
_ROW = re.compile(r"^HRS_AGNT_RSLT_I\$0_row_(\d+)$")
_GROUPING = re.compile(r"(\d)[\s\u00a0.,](\d{3})\b")  # "1,234" / "1 234" / "1.234"
_OF = re.compile(r"\bof\s+(\d+)", re.I)


@dataclass(frozen=True)
class Row:
    id: str
    title: str
    location: str
    opened: str


@dataclass
class Page:
    total: int  # the row count the page states, -1 when it states none
    rows: list[Row]
    action: str
    fields: dict[str, str]


def count(text: str) -> int | None:
    """The row count in "68 rows", "1 of 96", "Ligne 1 sur 96" or "1,234 rows"."""
    text = _GROUPING.sub(r"\1\2", text)
    if m := _OF.search(text):
        return int(m[1])
    nums = re.findall(r"\d+", text)
    return int(nums[-1]) if nums else None


def _index(tree: LexborHTMLParser) -> dict[str, str]:
    """element id -> collapsed text; the first element of an id wins. (PeopleSoft ids carry `$`,
    which CSS selectors do not take.)"""
    found: dict[str, str] = {}
    for node in tree.css("[id]"):
        found.setdefault(node.attributes["id"] or "", text_of(node))
    return found


def form_fields(form: LexborNode) -> dict[str, str]:
    """The values a browser would post for the form's inputs (checked boxes only)."""
    out: dict[str, str] = {}
    for node in form.css("input, textarea, select"):
        name = node.attributes.get("name")
        if not name:
            continue
        if node.tag == "input":
            kind = (node.attributes.get("type") or "").lower()
            if kind in ("checkbox", "radio") and "checked" not in node.attributes:
                continue
            out[name] = node.attributes.get("value") or ""
        elif node.tag == "textarea":
            out[name] = node.text(deep=True)
        else:
            for option in node.css("option"):
                if "selected" in option.attributes:
                    out[name] = option.attributes.get("value") or ""
    return out


def parse_page(html: str) -> Page:
    tree = LexborHTMLParser(html)
    form = tree.css_first('form[name="win0"]')
    if form is None:
        raise ValueError("peoplesoft: the page is not a PeopleSoft search page (no win0 form)")
    text = _index(tree)
    rows = []
    for node in tree.css("[id]"):
        m = _ROW.match(node.attributes["id"] or "")
        if not m:
            continue
        i = m[1]
        row = Row(
            text.get(f"HRS_APP_JBSCH_I_HRS_JOB_OPENING_ID${i}", ""),
            text.get(f"SCH_JOB_TITLE${i}", ""),
            text.get(f"LOCATION${i}", ""),
            text.get(f"SCH_OPENED${i}", ""),
        )
        if row.id and row.title:
            rows.append(row)
    total = count(text.get("win0divHRS_AGNT_RSLT_Irowcnt$0", ""))
    action = form.attributes.get("action") or ""
    return Page(-1 if total is None else total, rows, action, form_fields(form))


def parse_posting(html: str, row: Row) -> tuple[str, str, str, str] | None:
    """(title, location, description, full/part time) of a posting page; None when the page is not
    the posting of `row` (the search page an expired opening lands on, another opening)."""
    tree = LexborHTMLParser(html)
    text = _index(tree)
    if text.get("HRS_SCH_WRK2_HRS_JOB_OPENING_ID") != row.id:
        return None
    parts = []
    for i in range(100):
        body = tree.css_first(f'[id="HRS_SCH_PSTDSC_DESCRLONG${i}"]')
        if body is None:
            break
        if label := text.get(f"HRS_SCH_WRK_DESCR100${i}lbl"):
            parts.append(f"<h3>{label}</h3>")
        parts.append(body.html or "")
    description = html_to_text("".join(parts))
    if not description:
        return None
    return (
        text.get("HRS_SCH_WRK2_POSTING_TITLE") or row.title,
        row.location or text.get("HRS_SCH_WRK_HRS_DESCRLONG", ""),
        description,
        text.get("HRS_SCH_WRK_HRS_FULL_PART_TIME", ""),
    )


def opened(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y")
    except ValueError:
        return None


class PeopleSoft(Source):
    """The board is `<host>/<site>/<portal>/<node>`: `careers.dc.gov/erecruit/EMPLOYEE/HRMS`.
    Each customer runs it on its own host, so there is no URL pattern."""

    name = "peoplesoft"
    kind = "ats"

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        parts = task.board.strip("/ ").split("/")
        if len(parts) != 4 or any(not p or re.search(r"[?#:@\s]", p) for p in parts):
            raise ValueError(
                f"peoplesoft: board {task.board!r} is not <host>/<site>/<portal>/<node>"
            )
        host = parts[0].lower()
        component = f"https://{host}/psc/{'/'.join(parts[1:])}{COMPONENT}"
        search_url = f"{component}?Page=HRS_APP_SCHJOB_FL&Action=U&FOCUS=Applicant&SiteId=1"
        rows = await self.rows(http, search_url, host)
        company, read = name_from_host(host), 0

        async def build(row: Row) -> JobStub | None:
            nonlocal read
            url = (
                f"{component}?Page=HRS_APP_JBPST_FL&Action=U&FOCUS=Applicant&SiteId=1"
                f"&JobOpeningId={quote(row.id)}&PostingSeq=1"
            )
            html = await page_text(http, url)
            got = parse_posting(html, row) if html else None
            if got is None:
                return None
            read += 1
            title, location, description, schedule = got
            return JobStub(
                source="peoplesoft",
                url=url,
                title=title,
                company=company,
                location=location,
                description=description,
                posted_at=opened(row.opened),
                ats="peoplesoft",
                apply_url=url,
                remote=remote_from_text(location),
                extra={"board": task.board, "id": row.id, "schedule": schedule},
            )

        async for page in hydrate(rows, start_page, build, CHUNK):
            yield page
        if rows and start_page == 0 and not read:
            raise ValueError(
                f"peoplesoft: listed {len(rows)} postings and read none of their pages"
            )

    @staticmethod
    async def rows(http: Http, search_url: str, host: str) -> list[Row]:
        """Every listed row: the first page, then "load more" postbacks until the row count the
        page states is reached. A walk that stalls or ends short is an error, not a partial
        board."""
        page = parse_page((await get_page(http, search_url)).text)
        for n in range(MAX_POSTBACKS):
            if page.total < 0 or len(page.rows) >= page.total:
                break
            action = urlsplit(page.action)
            if action.scheme != "https" or (action.hostname or "").lower() != host:
                raise ValueError(f"peoplesoft: form posts to {page.action!r}, not to {host}")
            resp = await post_form(http, page.action, {**page.fields, "ICAction": LOAD_MORE})
            more = parse_page(resp.text)
            if len(more.rows) <= len(page.rows):
                raise ValueError(
                    f"peoplesoft: postback {n + 1} added no row ({len(more.rows)} of {page.total})"
                )
            page = more
        else:
            raise ValueError(
                f"peoplesoft: {len(page.rows)} of {page.total} rows after {MAX_POSTBACKS} postbacks"
            )
        if page.total < 0 and page.rows:
            raise ValueError(f"peoplesoft: {len(page.rows)} rows and no stated row count")
        return list({r.id: r for r in page.rows}.values())
