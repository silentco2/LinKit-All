"""X5 Group's career site (rabota.x5.ru): a public vacancy API pages a list that holds every fact
but the body, which each vacancy's own detail request adds. X5 hires for many chains (Pyaterochka,
Perekrestok, Chizhik, X5 Tech...), so a vacancy's business unit is its employer. A single-company
plugin, not an ATS. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.http import Http

API = "https://rabota.x5.ru/vacancy/api/v1/public/vacancies"
VACANCY = "https://rabota.x5.ru/vacancies/{id}"
PAGE = 100
_ID = re.compile(r"/vacancies/([^/?#]+)")
_MODES: dict[str, Remote] = {
    "remote": "remote",
    "hybrid": "hybrid",
    "office": "onsite",
    "on_site": "onsite",
}


def parse_item(it: dict[str, Any]) -> JobStub | None:
    if not (it.get("id") and it.get("name")):
        return None
    units = [(u.get("business_unit") or {}).get("name") for u in it.get("business_units") or []]
    exact, lo, hi = it.get("salary"), it.get("salary_min"), it.get("salary_max")
    if exact is not None:
        lo = hi = exact
    url = VACANCY.format(id=it["id"])
    return JobStub(
        source="x5",
        ats="x5",
        url=url,
        title=" ".join(str(it["name"]).split()),
        company=next((str(u).strip() for u in units if u and str(u).strip()), "X5 Group"),
        location=it.get("city") or it.get("address") or "",
        posted_at=from_iso(it.get("published_at")),
        apply_url=url,
        remote=_MODES.get(it.get("work_format") or ""),
        # Printed in roubles with no period, which on this market is a monthly figure.
        salary_min=lo,
        salary_max=hi,
        salary_currency="RUB" if lo is not None or hi is not None else None,
        salary_interval="month" if lo is not None or hi is not None else None,
        extra={"id": str(it["id"])},
    )


def body_text(d: dict[str, Any]) -> str:
    """The detail response's sections as text, in the site's own order. Content fields are
    hand-written Markdown, left as is."""
    c = d.get("content") or {}
    features = "\n".join(f"- {f}" for f in d.get("key_features") or [] if str(f).strip())
    labelled = [
        f"{label}: {c[k]}".strip()
        for label, k in (
            ("Образование", "education"),
            ("Опыт работы", "experience"),
            ("Компьютерные навыки", "software_skills"),
            ("Иностранный язык", "foreign_language"),
            ("Личные качества", "personal_qualities"),
            ("Дополнительные требования", "other_requirements"),
        )
        if str(c.get(k) or "").strip()
    ]
    sections: list[tuple[str, list[Any]]] = [
        ("Особенности", [features]),
        ("О вакансии", [c.get("description")]),  # noqa: RUF001
        ("Обязанности", [c.get("main_responsibilities")]),
        ("Требования", [c.get("professional_skills"), *labelled]),
        ("Условия", [c.get("working_conditions"), c.get("business_trips")]),
    ]
    out = []
    for heading, blocks in sections:
        kept = [str(b).strip() for b in blocks if b and str(b).strip()]
        if kept:
            out.append(f"{heading}\n" + "\n\n".join(kept))
    return "\n\n".join(out)


class X5(Source):
    name = "x5"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "x5:careers", board="rabota.x5.ru")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        page = start_page + 1
        while True:
            data = await http.get_json(API, params={"page": page, "page_size": PAGE})
            items = data.get("items") or []
            if not items:
                return
            yield [s for it in items if (s := parse_item(it))]
            if page >= (data.get("pages") or 0):
                return
            page += 1

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _ID.search(stub.url)
        if not m:
            return stub
        text = body_text(await http.get_json(f"{API}/{m[1]}"))
        return stub.model_copy(update={"description": text}) if text else stub
