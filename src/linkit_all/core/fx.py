"""Exchange rates: a table shipped with the app, refreshed at the start of each search.

Rates are USD-based (open.er-api.com). The refresh request carries no personal data.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from linkit_all.core.config import get_settings

URL = "https://open.er-api.com/v6/latest/USD"
BUNDLED = Path(__file__).parent.parent / "data" / "fx.json"
# Working-time conventions for turning a stated pay period into a month.
_MONTHLY = {"year": 1 / 12, "month": 1.0, "week": 52 / 12, "day": 22.0, "hour": 176.0}


@dataclass(frozen=True)
class Rates:
    date: str  # ISO day the table was published
    base: str
    rates: dict[str, float]  # units of each currency per 1 base


def _parse(d: dict[str, Any]) -> Rates | None:
    """A valid table or None; shared by file reads and a fresh download."""
    try:
        rates = {str(k).upper(): float(v) for k, v in d["rates"].items()}
        base = str(d["base"]).upper()
        ok = base in rates and all(v > 0 for v in rates.values())  # also rejects NaN
        return Rates(str(d["date"]), base, rates) if ok else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


@lru_cache(maxsize=8)
def _load(path: str, mtime_ns: int) -> Rates | None:
    """Parse one file; the mtime keys the cache so a refresh is seen without a restart."""
    try:
        d = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return _parse(d) if isinstance(d, dict) else None


def _read(path: Path) -> Rates | None:
    try:
        return _load(str(path), path.stat().st_mtime_ns)
    except OSError:
        return None


def rates(data_dir: Path | None = None) -> Rates:
    """The newest of `data_dir/fx.json` (written by `refresh`) and the table in the wheel."""
    mine = _read((data_dir or get_settings().data_dir) / "fx.json")
    shipped = _read(BUNDLED)
    if mine and (shipped is None or mine.date >= shipped.date):
        return mine
    if shipped is None:
        raise RuntimeError("bundled fx.json is missing or unreadable")
    return shipped


def convert(
    amount: float, from_cur: str, to_cur: str, data_dir: Path | None = None
) -> float | None:
    """`amount` in `to_cur`, or None when either currency is not in the table."""
    table = rates(data_dir).rates
    src, dst = table.get(from_cur.strip().upper()), table.get(to_cur.strip().upper())
    if src is None or dst is None:
        return None
    return amount / src * dst


def monthly(amount: float, period: str) -> float:
    """A pay amount per "year", "month", "week", "day" or "hour" as a monthly figure."""
    return amount * _MONTHLY[period]


async def _fetch() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=5) as client:  # default headers only
        r = await client.get(URL)
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        return data


async def refresh(data_dir: Path) -> bool:
    """Fetch today's table into `data_dir/fx.json`. Never raises; True when it was updated."""
    try:
        d = await _fetch()
        if d.get("result") != "success":
            raise ValueError("unexpected response")
        day = datetime.fromtimestamp(d["time_last_update_unix"], UTC).date().isoformat()
        table = {"base": "USD", "date": day, "rates": d["rates"]}
        if _parse(table) is None:
            raise ValueError("unusable rates")
        data_dir.mkdir(parents=True, exist_ok=True)
        tmp = data_dir / "fx.json.tmp"
        tmp.write_text(json.dumps(table, separators=(",", ":")), "utf-8")
        tmp.replace(data_dir / "fx.json")
        return True
    except Exception as e:  # network, bad payload or disk: the shipped table still works
        logger.info("exchange rates not refreshed ({})", type(e).__name__)
        return False
