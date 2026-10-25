"""Helpers for the keyed aggregator plugins: saved API keys, daily call budgets, countries."""

import json
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

from loguru import logger

KeyGetter = Callable[[str], dict[str, str] | None]

# ISO 3166 alpha-2 (lower case) -> display name, for every country any keyed API serves.
COUNTRIES: dict[str, str] = {
    "ae": "United Arab Emirates", "ar": "Argentina", "at": "Austria", "au": "Australia",
    "be": "Belgium", "bh": "Bahrain", "br": "Brazil", "ca": "Canada", "ch": "Switzerland",
    "cl": "Chile", "co": "Colombia", "cr": "Costa Rica", "de": "Germany", "dk": "Denmark",
    "do": "Dominican Republic", "dz": "Algeria", "ec": "Ecuador", "eg": "Egypt", "es": "Spain",
    "fi": "Finland", "fr": "France", "gb": "United Kingdom", "gr": "Greece", "gt": "Guatemala",
    "hk": "Hong Kong", "hu": "Hungary", "id": "Indonesia", "ie": "Ireland", "in": "India",
    "it": "Italy", "ke": "Kenya", "kw": "Kuwait", "lu": "Luxembourg", "ma": "Morocco",
    "mx": "Mexico", "my": "Malaysia", "ng": "Nigeria", "nl": "Netherlands", "no": "Norway",
    "nz": "New Zealand", "om": "Oman", "pa": "Panama", "pe": "Peru", "ph": "Philippines",
    "pk": "Pakistan", "pl": "Poland", "pr": "Puerto Rico", "pt": "Portugal", "py": "Paraguay",
    "qa": "Qatar", "ru": "Russia", "sa": "Saudi Arabia", "se": "Sweden", "sg": "Singapore",
    "sv": "El Salvador", "th": "Thailand", "tr": "Turkey", "tz": "Tanzania", "ug": "Uganda",
    "us": "United States", "uy": "Uruguay", "ve": "Venezuela", "vn": "Vietnam",
    "za": "South Africa",
}  # fmt: skip
_ALIASES = {
    "usa": "us", "u.s.": "us", "u.s.a.": "us", "united states of america": "us", "america": "us",
    "uk": "gb", "u.k.": "gb", "great britain": "gb", "britain": "gb", "england": "gb",
    "scotland": "gb", "wales": "gb", "northern ireland": "gb", "uae": "ae", "emirates": "ae",
    "holland": "nl", "the netherlands": "nl", "turkiye": "tr",
}  # fmt: skip
_BY_NAME = {name.lower(): code for code, name in COUNTRIES.items()} | _ALIASES
_warned: set[str] = set()


def split_location(location: str) -> tuple[str | None, str]:
    """ "Leeds, UK" -> ("gb", "Leeds"); "Egypt" -> ("eg", ""); "Austin, TX" -> (None, "Austin, TX").
    A country is only recognised as the last comma-separated part."""
    parts = [p.strip() for p in location.split(",") if p.strip()]
    if parts and (code := _BY_NAME.get(parts[-1].lower())):
        return code, ", ".join(parts[:-1])
    return None, ", ".join(parts)


def get_keys(keys: KeyGetter | None, name: str, fields: tuple[str, ...]) -> dict[str, str] | None:
    """The saved values when every field is there. Logs once per process when nothing is saved."""
    values = keys(name) if keys else None
    if values and all(values.get(f) for f in fields):
        return values
    if name not in _warned:
        _warned.add(name)
        logger.info("{}: no API key set in Setup → API keys", name)
    return None


def parse_ids(raw: str) -> dict[str, str]:
    """ "gb=123, us:456" -> {"gb": "123", "us": "456"}; malformed pairs are skipped."""
    out: dict[str, str] = {}
    for pair in re.split(r"[,;\s]+", raw.strip()):
        code, _, ident = pair.replace(":", "=", 1).partition("=")
        if code.strip() and ident.strip():
            out[code.strip().lower()] = ident.strip()
    return out


class DailyBudget:
    """Calls allowed per day, kept in `<data_dir>/<name>_budget.json` so it survives restarts and
    separate runs (in memory only without a data dir)."""

    def __init__(self, name: str, limit: int, data_dir: Path | None = None) -> None:
        self.limit = limit
        self._path = data_dir / f"{name}_budget.json" if data_dir else None
        self._day, self._used = date.today().isoformat(), 0
        if self._path and self._path.exists():
            try:
                data = json.loads(self._path.read_text("utf-8"))
                if data.get("day") == self._day:
                    self._used = int(data.get("used", 0))
            except (OSError, ValueError):
                pass  # unreadable counter: start from zero rather than block the source

    def take(self) -> bool:
        """Spend one call; False when today's budget is gone."""
        today = date.today().isoformat()
        if today != self._day:
            self._day, self._used = today, 0
        if self._used >= self.limit:
            return False
        self._used += 1
        if self._path:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(json.dumps({"day": self._day, "used": self._used}), "utf-8")
            except OSError:
                pass  # the count then lives in memory only
        return True
