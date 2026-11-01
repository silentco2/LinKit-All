"""Readable names for user-added sources: "Stripe · Greenhouse", "Notion · careers page".

ATS pages are named offline (detector + slug). Other careers pages are fetched once, when added;
the domain is the fallback. The fetched page is never logged."""

import re
from urllib.parse import urlparse

import httpx
from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats_detector import detect
from linkit_all.sources.http import USER_AGENT

CAREERS_PAGE = "careers page"
TIMEOUT_S = 5.0
_MAX_CHARS = 60

# Display names where plain title case is wrong; any other platform key is title-cased.
PLATFORMS = {
    "adp": "ADP",
    "ashby": "Ashby",
    "ashbygraphql": "Ashby",
    "bamboohr": "BambooHR",
    "breezy": "Breezy HR",
    "greenhouse": "Greenhouse",
    "hibob": "HiBob",
    "icims": "iCIMS",
    "jazzhr": "JazzHR",
    "join": "JOIN",
    "lever": "Lever",
    "smartrecruiters": "SmartRecruiters",
    "successfactors": "SuccessFactors",
    "teamtailor": "Teamtailor",
    "ukg": "UKG",
    "workable": "Workable",
    "workday": "Workday",
}

# Tests swap this for a fake transport (httpx.MockTransport); None = the real network.
_TRANSPORT: httpx.BaseTransport | None = None

_TITLE_SPLIT = re.compile(r"\s+[|\-\u2013]\s+")
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac"}


def ats_label(ats: str, slug: str) -> str:
    """("greenhouse", "stripe") -> "Stripe · Greenhouse"; Workday "tenant/wd5/site" -> "Tenant"."""
    company = slug.split("/")[0]
    if not any(c.isupper() for c in company):  # "BoschGroup" is already a name; "my-co" is not
        company = re.sub(r"[-_]+", " ", company).title()
    return f"{company} · {PLATFORMS.get(ats, ats.title())}"


def domain_name(url: str) -> str:
    """The registrable domain without "www." ("careers.notion.com" -> "notion.com")."""
    host = (urlparse(url if "://" in url else f"https://{url}").hostname or url).lower()
    parts = host.removeprefix("www.").split(".")
    # ponytail: no public-suffix list; "co.uk"-style endings are the one case handled.
    keep = 3 if len(parts) > 2 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL else 2
    return ".".join(parts[-keep:])


def offline_label(url: str) -> str:
    """The label that needs no network: the ATS name, else the domain."""
    found = detect(url)
    return ats_label(*found) if found else f"{domain_name(url)} · {CAREERS_PAGE}"


def _site_name(html: str) -> str:
    tree = LexborHTMLParser(html)
    meta = tree.css_first('meta[property="og:site_name"]')
    if meta and (name := (meta.attributes.get("content") or "").strip()):
        return name
    title = tree.css_first("title")
    return _TITLE_SPLIT.split(title.text().strip(), maxsplit=1)[0].strip() if title else ""


def careers_label(url: str) -> str:
    """ "<og:site_name or title> · careers page" from one fetch; the domain label on any failure."""
    try:
        with httpx.Client(
            timeout=TIMEOUT_S,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            transport=_TRANSPORT,
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            name = " ".join(_site_name(resp.text[:300_000]).split())[:_MAX_CHARS]
    except Exception:
        name = ""
    return f"{name} · {CAREERS_PAGE}" if name else offline_label(url)


def label_for(url: str) -> str:
    """The label stored when `url` is added: ATS pages offline, careers pages by one fetch."""
    return offline_label(url) if detect(url) else careers_label(url)
