"""EURES (europa.eu/eures), the EU's cross-border public employment service, which gathers the
vacancies of every EU/EFTA national employment service. The search answers full bodies.
Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from math import ceil
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import query_tasks

SEARCH = "https://europa.eu/eures/api/jv-searchengine/public/jv-search/search"
PORTAL = "https://europa.eu/eures/portal/jv-se/jv-details/"
PAGE = 50  # the API's maximum resultsPerPage
MAX_RESULTS = 10_000  # deeper pages answer "Too many results were requested"
# EURES country codes ("el" is its Greece, not ISO "gr") -> display names.
COUNTRIES = {
    "at": "Austria", "be": "Belgium", "bg": "Bulgaria", "hr": "Croatia", "cy": "Cyprus",
    "cz": "Czechia", "dk": "Denmark", "ee": "Estonia", "fi": "Finland", "fr": "France",
    "de": "Germany", "el": "Greece", "hu": "Hungary", "is": "Iceland", "ie": "Ireland",
    "it": "Italy", "lv": "Latvia", "li": "Liechtenstein", "lt": "Lithuania", "lu": "Luxembourg",
    "mt": "Malta", "nl": "Netherlands", "no": "Norway", "pl": "Poland", "pt": "Portugal",
    "ro": "Romania", "sk": "Slovakia", "si": "Slovenia", "es": "Spain", "se": "Sweden",
    "ch": "Switzerland",
}  # fmt: skip
_BY_NAME = {n.casefold(): c for c, n in COUNTRIES.items()} | {"greece": "el", "gr": "el"}
_PERIODS = ((1, "LAST_DAY"), (3, "LAST_THREE_DAYS"), (7, "LAST_WEEK"), (10_000, "LAST_MONTH"))
_EMPTY_FILTERS = (
    "skillUris", "requiredExperienceCodes", "positionScheduleCodes", "sectorCodes",
    "educationAndQualificationLevelCodes", "positionOfferingCodes", "euresFlagCodes",
    "otherBenefitsCodes", "requiredLanguages", "occupationUris",
)  # fmt: skip


def country_code(location: str) -> str | None:
    """ "Germany" or "de" -> "de"; places that are not an EURES country -> None (no filter)."""
    key = location.strip().casefold()
    return key if key in COUNTRIES else _BY_NAME.get(key)


class Eures(Source):
    name = "eures"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        last = min(ceil(task.limit / PAGE), MAX_RESULTS // PAGE)
        for page in range(start_page + 1, last + 1):
            data = await http.post_json(SEARCH, self.body(task, page))
            rows = data.get("jvs") or []
            stubs = [s for r in rows if (s := self.stub(r))]
            if stubs:
                yield stubs
            if len(rows) < PAGE or page * PAGE >= data.get("numberRecords", 0):
                return

    @staticmethod
    def body(task: Task, page: int) -> dict[str, Any]:
        code = country_code(task.location)
        period = next(name for days, name in _PERIODS if task.posted_within_days <= days)
        return {
            "resultsPerPage": PAGE,
            "page": page,
            "sortSearch": "MOST_RECENT",
            "keywords": [{"keyword": task.query, "specificSearchCode": "EVERYWHERE"}],
            "publicationPeriod": period,
            "locationCodes": [code] if code else [],
            "sessionId": "linkit-all",  # required by the request schema, carries no identity
            "requestLanguage": "en",
        } | {f: [] for f in _EMPTY_FILTERS}

    def stub(self, v: dict[str, Any]) -> JobStub | None:
        if not v.get("id") or not v.get("title"):
            return None
        countries = [
            COUNTRIES.get(c.lower(), c.upper()) for c in sorted(v.get("locationMap") or {})
        ]
        url = f"{PORTAL}{v['id']}?lang=en"
        return JobStub(
            source=self.name,
            url=url,
            title=v["title"].strip(),
            company=((v.get("employer") or {}).get("name") or "").strip() or "Unknown",
            location="; ".join(countries),
            description=strip_html(v.get("description") or ""),
            posted_at=from_epoch_ms(v.get("creationDate")),
            apply_url=url,
            extra={"id": v["id"]},
        )
