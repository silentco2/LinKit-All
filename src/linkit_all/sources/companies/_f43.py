"""Small helpers private to the F4.3 single-company plugins (the underscore keeps it out of the
registry)."""

import re
from typing import Any

from linkit_all.sources.base import Remote, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http


def ru_mode(*texts: str | None) -> Remote | None:
    """Work format from Russian or English words; the broadest arrangement named wins (a posting
    offering "hybrid / office, elsewhere remote" can be taken remotely)."""
    joined = " ".join(t for t in texts if t).lower()
    if any(w in joined for w in ("удал", "дистанц", "remote")):
        return "remote"
    if "гибрид" in joined or "hybrid" in joined:
        return "hybrid"
    if any(w in joined for w in ("офис", "на месте", "office")):
        return "onsite"
    return None


def rub_month(low: Any, high: Any) -> dict[str, Any]:
    """Salary fields for a monthly rouble range; empty when neither bound is a positive number."""
    lo = low if isinstance(low, int | float) and low > 0 else None
    hi = high if isinstance(high, int | float) and high > 0 else None
    if lo is None and hi is None:
        return {}
    return {
        "salary_min": lo or hi,
        "salary_max": hi or lo,
        "salary_currency": "RUB",
        "salary_interval": "month",
    }


_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def text_of(part: str | None) -> str:
    """A body that may be HTML or plain text, as plain text."""
    part = (part or "").strip()
    return strip_html(part) if _TAG.search(part) else part


def sections(*pairs: tuple[str, str | None]) -> str:
    """(heading, body) pairs as one plain-text description; an empty body drops its heading."""
    out = []
    for heading, body in pairs:
        if text := text_of(body):
            out.append(f"{heading}\n{text}" if heading else text)
    return "\n\n".join(out)


def distinct(items: list[str | None], sep: str = "; ") -> str:
    return sep.join(dict.fromkeys(i.strip() for i in items if i and i.strip()))


def careers_task(name: str) -> list[Task]:
    return [Task(name, f"{name}:careers")]


async def json_or_none(http: Http, url: str, **kwargs: Any) -> Any:
    """GET JSON; None when the posting is gone (404/410). Other HTTP errors raise."""
    resp = await http.get(url, **kwargs)
    if resp.status_code in (404, 410):
        return None
    resp.raise_for_status()
    return resp.json()
