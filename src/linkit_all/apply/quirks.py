"""Per-ATS quirks that silently break a fill, keyed by the host the form is really on (an Apply
button often leads from one ATS to another, so the job's own source says little). Field-tested
by career-ops on real applications. Logic adapted from career-ops (MIT)."""

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Quirks:
    # Workday's React fields ignore a value set by script ("required" on a visibly filled box):
    # focus, select all and type real keystrokes.
    type_keys: bool = False
    # Lever raises hCaptcha on untrusted clicks: tick boxes with real input events only, never
    # the page-script fallback.
    trusted_ticks_only: bool = False
    # Ashby merges candidates by email per company: a second application there can vanish.
    email_merge: bool = False
    # SuccessFactors may keep the profile parsed from an earlier CV instead of this one.
    stored_profile: bool = False


_BY_HOST: list[tuple[tuple[str, ...], Quirks]] = [
    (("myworkdayjobs.com", "myworkdaysite.com", "workday.com"), Quirks(type_keys=True)),
    (("lever.co",), Quirks(trusted_ticks_only=True)),
    (("ashbyhq.com",), Quirks(email_merge=True)),
    (
        ("successfactors.com", "successfactors.eu", "sapsf.com", "sapsf.eu"),
        Quirks(stored_profile=True),
    ),
]
NONE = Quirks()


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def quirks_for(url: str) -> Quirks:
    host = host_of(url)
    for domains, quirks in _BY_HOST:
        if any(host == d or host.endswith("." + d) for d in domains):
            return quirks
    return NONE
