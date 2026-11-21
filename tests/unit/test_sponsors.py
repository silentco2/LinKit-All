"""B1 visa sponsor lists (core/sponsors.py): official registers of the user's visa countries,
refreshed at most weekly, matched by normalized employer name, a label + small rank boost."""

import asyncio
import io
import json
import os
import time
import zipfile
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker
from test_matching import CFG, db, fake_embed, job  # noqa: F401

from linkit_all.core import sponsors
from linkit_all.core.models import Job, JobState, Profile
from linkit_all.matching.rank import rank_jobs

NAMES = [f"Filler Employer {i} Ltd" for i in range(60)]  # a real list is never this short


def _xlsx(header: str, values: list[str]) -> bytes:
    """A minimal .xlsx: a title row, a header row, then one value per row (shared strings)."""
    strings = ["Employers with a positive LMIA", header, *values]
    sst = "".join(f"<si><t>{s.replace('&', '&amp;')}</t></si>" for s in strings)
    rows = '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
    rows += '<row r="2"><c r="A2"><v>x</v></c><c r="C2" t="s"><v>1</v></c></row>'
    rows += "".join(
        f'<row r="{i + 3}"><c r="C{i + 3}" t="s"><v>{i + 2}</v></c></row>'
        for i in range(len(values))
    )
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>{sst}</sst>")
        z.writestr(
            "xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{rows}</sheetData></worksheet>"
        )
    return out.getvalue()


def _site() -> tuple[httpx.AsyncClient, list[str]]:
    asked: list[str] = []
    uk_csv = "Organisation Name,Town/City,County,Type & Rating,Route\r\n" + "".join(
        f" {n} ,London,,Worker (A rating),Skilled Worker\r\n"
        for n in [*NAMES, "Acme (UK) Ltd.", "Old Name Ltd t/a Brightwork"]
    )
    nl_rows = "".join(f"<tr><td>{n}</td><td>123</td></tr>" for n in [*NAMES, "Dutch Co B.V."])
    pages: dict[str, httpx.Response] = {
        "/government/publications/register-of-licensed-sponsors-workers": httpx.Response(
            200,
            text='<a href="https://assets.publishing.service.gov.uk/media/x/Register_-_2026-11-19.csv">csv</a>',
        ),
        "/media/x/Register_-_2026-11-19.csv": httpx.Response(
            200, content=uk_csv.encode("utf-8-sig")
        ),
        "/en/public-register-recognised-sponsors/public-register-regular-labour-and-highly-skilled-migrants": httpx.Response(
            200, text=f"<table><tr><th>Organisation</th><th>KVK</th></tr>{nl_rows}</table>"
        ),
        "/tools/reports-and-studies/h-1b-employer-data-hub/h-1b-employer-data-hub-files": httpx.Response(
            200,
            text='<a href="/data/h1b_datahubexport-2022.csv">22</a><a href="/data/h1b_datahubexport-2023.csv">23</a>',
        ),
        "/data/h1b_datahubexport-2023.csv": httpx.Response(
            200,
            text='"Fiscal Year",Employer,City\n'
            + "".join(f'2023,"{n}",X\n' for n in [*NAMES, "GLOBEX LLC"]),
        ),
        "/data/api/action/package_show": httpx.Response(
            200,
            json={
                "result": {
                    "resources": [
                        {"url": f"https://open.canada.ca/dl/{u}/tfwp_{q}_pos_en.xlsx"}
                        for u, q in [
                            ("b", "2025q1"),
                            ("a", "2026q2"),
                            ("c", "2025q4"),
                            ("d", "2026q1"),
                            ("e", "2025q3"),
                        ]
                    ]
                }
            },
        ),
    }
    for u, q, extra in [("a", "2026q2", "Maple Ltd"), ("d", "2026q1", "Spruce Inc."),
                        ("c", "2025q4", "Birch Corp"), ("e", "2025q3", "Cedar & Sons"),
                        ("b", "2025q1", "Too Old Inc")]:  # fmt: skip
        pages[f"/dl/{u}/tfwp_{q}_pos_en.xlsx"] = httpx.Response(
            200, content=_xlsx("Employer", [*NAMES, extra])
        )

    def handler(req: httpx.Request) -> httpx.Response:
        asked.append(req.url.path)
        return pages.get(req.url.path, httpx.Response(404))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), asked


@pytest.mark.parametrize(
    ("raw", "key"),
    [("Acme (UK) Ltd.", "acme"), ("ACME LIMITED", "acme"), ("The Acme Company", "acme"),
     ("Dutch Co B.V.", "dutch"), ("GLOBEX LLC", "globex"), ("Acme Group", "acme group"),
     ("Ltd", "")],
)  # fmt: skip
def test_employer_key(raw: str, key: str) -> None:
    assert sponsors.employer_key(raw) == key


def test_xlsx_column_finds_the_header() -> None:
    assert sponsors.xlsx_column(_xlsx("Employer", ["A & B Ltd", "C Inc"]), "Employer") == [
        "A & B Ltd",
        "C Inc",
    ]


def test_refresh_fetches_only_visa_countries_and_only_when_stale(tmp_path: Path) -> None:
    client, asked = _site()
    done = asyncio.run(
        sponsors.refresh(tmp_path, ["United Kingdom", "Holland", "USA", "Canada", "Egypt"], client)
    )
    assert sorted(done) == ["CA", "GB", "NL", "US"]  # Egypt has no list
    on = lambda co, iso: sponsors.on_list(tmp_path, co, iso)  # noqa: E731
    assert (
        on("Acme Ltd", "GB") and on("Brightwork", "GB") and on("Old Name", "GB")
    )  # t/a: both names
    assert on("Dutch Co", "NL") and on("Globex", "US") and not on("Acme", "US")
    assert (
        on("Maple", "CA") and on("Cedar & Sons", "CA") and not on("Too Old", "CA")
    )  # newest 4 quarters
    assert json.loads((tmp_path / "sponsors" / "US.json").read_text("utf-8"))["source"].endswith(
        "2023.csv"
    )

    asked.clear()
    assert asyncio.run(sponsors.refresh(tmp_path, ["United Kingdom"], client)) == [] and asked == []
    week_ago = time.time() - 8 * 86400
    os.utime(tmp_path / "sponsors" / "GB.json", (week_ago, week_ago))
    assert asyncio.run(sponsors.refresh(tmp_path, ["United Kingdom"], client)) == ["GB"]


def test_a_failed_or_odd_download_keeps_the_old_copy(tmp_path: Path) -> None:
    client, _ = _site()
    asyncio.run(sponsors.refresh(tmp_path, ["United Kingdom"], client))
    path = tmp_path / "sponsors" / "GB.json"
    os.utime(path, (0, 0))
    broken = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<p>moved</p>"))
    )
    assert asyncio.run(sponsors.refresh(tmp_path, ["United Kingdom"], broken)) == []
    assert sponsors.on_list(tmp_path, "Acme", "GB")  # the old list still answers


def test_rank_labels_and_boosts_listed_employers_in_visa_countries(
    db: sessionmaker[Session],  # noqa: F811
    tmp_path: Path,
) -> None:
    client, _ = _site()
    asyncio.run(sponsors.refresh(tmp_path, ["United Kingdom"], client))
    with db.begin() as s:
        profile = s.get_one(Profile, 1)
        profile.answers = {**profile.answers, "visa_countries": ["United Kingdom"]}
        for title, company, where in [("Backend Engineer", "Acme Ltd", "London, UK"),
                                      ("Backend Engineer", "Initech", "London, UK"),
                                      ("Backend Engineer", "Brightwork", "Remote")]:  # fmt: skip
            s.add(job(title=title, company=company, location=where, url=f"https://x/{company}",
                      description="Python APIs", state=JobState.enriched))  # fmt: skip
    cfg = CFG.model_copy(deep=True)
    cfg.filters.locations, cfg.filters.title_include, cfg.search.places = [], [], []
    rank_jobs(db, cfg, fake_embed, tmp_path)
    with db() as s:
        got = {j.company: j.data for j in s.query(Job)}
    assert got["Acme Ltd"]["sponsor"] == "GB" and got["Initech"]["sponsor"] is None
    assert got["Brightwork"]["sponsor"] is None  # on the list, but not placed in the UK
    assert got["Acme Ltd"]["rank"] == pytest.approx(
        got["Initech"]["rank"] + sponsors.BOOST, abs=1e-3
    )
