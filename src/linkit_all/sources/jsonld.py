"""schema.org JobPosting (JSON-LD) -> JobStub. Used by Wuzzuf and, later, any career page."""

import json
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, from_iso
from linkit_all.sources.text import html_to_text


def job_postings(html: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for node in LexborHTMLParser(html).css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text(deep=True))
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        found += [d for d in items if isinstance(d, dict) and d.get("@type") == "JobPosting"]
    return found


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def _location(posting: dict[str, Any]) -> str:
    places = posting.get("jobLocation") or []
    places = places if isinstance(places, list) else [places]
    out = []
    for place in places:
        addr = (place or {}).get("address") or {}
        if isinstance(addr, str):
            out.append(addr)
            continue
        country = addr.get("addressCountry")
        country = country.get("name") if isinstance(country, dict) else country
        parts = (addr.get("addressLocality"), addr.get("addressRegion"), country)
        out.append(", ".join(dict.fromkeys(p for p in parts if p)))
    return "; ".join(p for p in out if p)


def to_stub(posting: dict[str, Any], source: str, url: str, ats: str | None) -> JobStub:
    org = _first(posting.get("hiringOrganization")) or {}
    salary = posting.get("baseSalary") or {}
    value = salary.get("value") or {} if isinstance(salary, dict) else {}
    value = value if isinstance(value, dict) else {"minValue": value, "maxValue": value}
    return JobStub(
        source=source,
        url=url,
        title=" ".join(str(posting.get("title", "")).split()),
        company=" ".join(str(org.get("name", "") if isinstance(org, dict) else org).split())
        or "Unknown",
        location=_location(posting),
        description=html_to_text(posting.get("description") or ""),
        posted_at=from_iso(posting.get("datePosted")),
        ats=ats,
        apply_url=url,
        remote="remote" if posting.get("jobLocationType") == "TELECOMMUTE" else None,
        salary_min=value.get("minValue"),
        salary_max=value.get("maxValue"),
        salary_currency=salary.get("currency") if isinstance(salary, dict) else None,
        salary_interval=(value.get("unitText") or "").lower() or None,
        extra={
            "employment": posting.get("employmentType"),
            "valid_through": posting.get("validThrough"),
        },
    )
