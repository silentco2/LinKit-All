"""Official lists of employers that sponsor work visas: UK Home Office register of licensed
sponsors, Netherlands IND register of recognised sponsors, US USCIS H-1B employer data, Canada
employers with a positive LMIA. A job in a country where the user needs a visa, at an employer on
that country's list, gets a label and a small rank boost; it is never a promise of sponsorship
and never changes the AI score, the tier or a sponsorship answer.

Refresh (maintainer 2026-11-20): at run start, at most weekly, only the lists of the user's visa
countries. The requests carry no personal data; a failure keeps the old copy. Names are matched
exactly after `employer_key` (lower case, punctuation and legal suffixes dropped); trading names
("X Ltd t/a Y", "X DBA Y") count under both names. Rules only, no AI."""

import csv
import io
import json
import re
import zipfile
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import httpx
from loguru import logger
from lxml import etree

from linkit_all.core import geo

MAX_AGE = timedelta(days=7)
BOOST = 0.05  # added to the local rank (0..1) of a job whose employer is on the list
CA_QUARTERS = 4  # Canada publishes one file per quarter: combine a year (maintainer 2026-11-20)
_SUFFIXES = {
    "ltd", "limited", "plc", "llp", "lp", "llc", "inc", "incorporated", "corp", "corporation",
    "co", "company", "bv", "nv", "gmbh", "ag", "sa", "sas", "sarl", "srl", "spa", "pty",
    "ulc", "pc", "pllc", "the", "uk", "usa", "us", "canada", "netherlands", "nederland",
}  # fmt: skip
_ALSO = re.compile(r"\s+(?:t/a|trading as|dba|d/b/a)\s+", re.I)
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
# A downloaded file is data: no entities, no DTD, no network (XXE and entity-expansion safe).
_XML = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


def employer_key(name: str) -> str:
    """ "Acme (UK) Ltd." -> "acme"; "" when nothing but suffixes is left."""
    words = re.findall(r"[a-z0-9]+", re.sub(r"\b(\w)\.(?=\w\.)", r"\1", name.lower()))
    while words and words[-1] in _SUFFIXES:
        words.pop()
    while words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


def _keys(names: Iterable[str]) -> list[str]:
    out = set()
    for raw in names:
        for part in _ALSO.split(raw or ""):
            if key := employer_key(part):
                out.add(key)
    return sorted(out)


Fetch = Callable[[httpx.AsyncClient], Awaitable[tuple[str, list[str]]]]


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    r = await client.get(url, timeout=120)
    r.raise_for_status()
    return r


def _csv_column(text: str, column: str) -> list[str]:
    rows = csv.DictReader(io.StringIO(text))
    rows.fieldnames = [f.strip() for f in rows.fieldnames or []]
    return [(row.get(column) or "").strip() for row in rows]


async def _uk(client: httpx.AsyncClient) -> tuple[str, list[str]]:
    page = await _get(
        client, "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
    )
    m = re.search(r'href="(https://assets\.publishing\.service\.gov\.uk/[^"]+\.csv)"', page.text)
    if m is None:
        raise ValueError("no CSV link on the register page")
    data = await _get(client, m.group(1))
    return m.group(1), _csv_column(data.content.decode("utf-8-sig", "replace"), "Organisation Name")


async def _nl(client: httpx.AsyncClient) -> tuple[str, list[str]]:
    url = (
        "https://ind.nl/en/public-register-recognised-sponsors/"
        "public-register-regular-labour-and-highly-skilled-migrants"
    )
    page = await _get(client, url)
    cells = re.findall(r"<tr[^>]*>\s*<t[dh][^>]*>(.*?)</t[dh]>", page.text, re.S)
    names = [re.sub(r"<[^>]+>", "", c).replace("&amp;", "&").strip() for c in cells]
    return url, [n for n in names if n and n != "Organisation"]


async def _us(client: httpx.AsyncClient) -> tuple[str, list[str]]:
    hub = "https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub/h-1b-employer-data-hub-files"
    page = await _get(client, hub)
    files = sorted(
        set(re.findall(r'href="(/[^"]*h1b_datahubexport-(\d{4})\.csv)"', page.text)),
        key=lambda f: f[1],
    )
    if not files:
        raise ValueError("no H-1B data file listed")
    url = "https://www.uscis.gov" + files[-1][0]
    return url, _csv_column((await _get(client, url)).text, "Employer")


def xlsx_column(data: bytes, header: str) -> list[str]:
    """One column of the first sheet of an .xlsx, found by its header cell (no new dependency)."""
    book = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in book.namelist():
        for si in etree.fromstring(book.read("xl/sharedStrings.xml"), _XML).findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))

    def value(cell: etree._Element) -> str:
        v = cell.find("m:v", _NS)
        if v is None:
            t = cell.find("m:is/m:t", _NS)
            return (t.text or "") if t is not None else ""
        return shared[int(v.text or 0)] if cell.get("t") == "s" else (v.text or "")

    col, out = None, []
    sheet = etree.fromstring(book.read("xl/worksheets/sheet1.xml"), _XML)
    for row in sheet.iter(f"{{{_NS['m']}}}row"):
        cells = {re.sub(r"\d", "", c.get("r") or ""): value(c) for c in row.findall("m:c", _NS)}
        if col is None:
            col = next((k for k, v in cells.items() if v.strip() == header), None)
        elif cells.get(col, "").strip():
            out.append(cells[col].strip())
    return out


async def _ca(client: httpx.AsyncClient) -> tuple[str, list[str]]:
    api = "https://open.canada.ca/data/api/action/package_show?id=90fed587-1364-4f33-a9ee-208181dc0b97"
    res = (await _get(client, api)).json()["result"]["resources"]
    quarters = [
        (m.group(1), r["url"])
        for r in res
        if (m := re.search(r"_(\d{4}q\d)_pos_en\.xlsx$", r.get("url") or ""))
    ]
    if not quarters:
        raise ValueError("no positive LMIA file listed")
    # A year of employers: the newest CA_QUARTERS files by quarter ("2026q2"), not by address.
    newest = [url for _, url in sorted(set(quarters))[-CA_QUARTERS:]]
    names = []
    for url in newest:
        names += xlsx_column((await _get(client, url)).content, "Employer")
    return newest[-1], names


REGISTERS: dict[str, Fetch] = {"GB": _uk, "NL": _nl, "US": _us, "CA": _ca}


def _file(data_dir: Path, iso2: str) -> Path:
    return data_dir / "sponsors" / f"{iso2}.json"


def stale(data_dir: Path, iso2: str, now: datetime | None = None) -> bool:
    path = _file(data_dir, iso2)
    if not path.exists():
        return True
    age = (now or datetime.now(UTC)) - datetime.fromtimestamp(path.stat().st_mtime, UTC)
    return age > MAX_AGE


def visa_iso2(visa_countries: Iterable[str]) -> set[str]:
    """The user's visa countries ("United Kingdom", "UK", "Holland") as ISO2 codes."""
    return {c.iso2 for name in visa_countries if (c := geo.country(name))}


async def refresh(
    data_dir: Path, visa_countries: Iterable[str], client: httpx.AsyncClient | None = None
) -> list[str]:
    """Download the stale lists of the user's visa countries. Never raises; the ISO2 codes
    updated. `client` is for tests (a real run uses our normal client)."""
    wanted = sorted(visa_iso2(visa_countries) & set(REGISTERS))
    todo = [iso2 for iso2 in wanted if stale(data_dir, iso2)]
    if not todo:
        return []
    from linkit_all.sources.http import make_client  # late: sources import core

    done = []
    async with make_client() if client is None else _same(client) as c:
        for iso2 in todo:
            try:
                url, names = await REGISTERS[iso2](c)
                keys = _keys(names)
                if len(keys) < 50:  # a changed page, not a real list: keep the old copy
                    raise ValueError(f"only {len(keys)} names")
                path = _file(data_dir, iso2)
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                fetched = datetime.now(UTC).date().isoformat()
                tmp.write_text(
                    json.dumps({"source": url, "fetched": fetched, "names": keys}), "utf-8"
                )
                tmp.replace(path)
                done.append(iso2)
                logger.info("sponsor list {} refreshed: {} employers", iso2, len(keys))
            except Exception as e:  # network, a changed page or disk: the old copy still works
                logger.info("sponsor list {} not refreshed ({})", iso2, type(e).__name__)
    return done


class _same:
    """`async with` over a client the caller owns (it is not closed here)."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, *_: object) -> None:
        return None


@lru_cache(maxsize=8)
def _names(path: str, mtime_ns: int) -> frozenset[str]:
    try:
        return frozenset(json.loads(Path(path).read_text("utf-8"))["names"])
    except (OSError, ValueError, KeyError):
        return frozenset()


def on_list(data_dir: Path, company: str, iso2: str) -> bool:
    """Is `company` on the stored list of `iso2`? False when there is no list."""
    path = _file(data_dir, iso2)
    if iso2 not in REGISTERS or not path.exists() or not (key := employer_key(company)):
        return False
    return key in _names(str(path), path.stat().st_mtime_ns)
