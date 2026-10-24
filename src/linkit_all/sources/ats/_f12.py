"""Small helpers private to the F1.2 ATS adapters (the underscore keeps it out of the registry)."""

import httpx

from linkit_all.sources.base import Remote
from linkit_all.sources.http import Http

_MODES: dict[str, Remote] = {
    "remote": "remote",
    "hybrid": "hybrid",
    "onsite": "onsite",
    "on-site": "onsite",
    "on_site": "onsite",
}


async def get_page(http: Http, url: str) -> httpx.Response:
    """GET a human-facing page (the host's Crawl-delay applies). HTTP errors raise (the runner
    records them); nothing is retried around a block."""
    await http.allowed(url)
    resp = await http.get(url)
    resp.raise_for_status()
    return resp


def mode(value: str | None) -> Remote | None:
    """A vendor's workplace-type word ("Hybrid", "ON_SITE") as our remote mode."""
    return _MODES.get((value or "").strip().lower())


def name_from_slug(slug: str) -> str:
    """Display name for a board slug when the API gives none: "acme-corp" -> "Acme Corp"."""
    return slug.replace("-", " ").replace("_", " ").title()


def name_from_host(host: str) -> str:
    """Company name from a careers host: "jobs.acme.com" -> "Acme", "acme.catsone.com" -> "Acme"."""
    labels = [p for p in host.lower().split(".") if p not in ("www", "jobs", "careers", "career")]
    return name_from_slug(labels[0] if labels else host)
