"""Exchange rates: lookup, conversion, pay periods and the refresh (mocked, never online)."""

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest

from linkit_all.core import fx

REAL_FETCH = fx._fetch  # captured at import: tests/conftest.py replaces it per test
REAL_CLIENT = httpx.AsyncClient


def table(date: str, **rates: float) -> dict[str, object]:
    return {"base": "USD", "date": date, "rates": {"USD": 1, **rates}}


def test_bundled_table_is_usable() -> None:
    r = fx.rates(Path("/nonexistent"))
    assert r.base == "USD" and r.date and len(r.rates) > 100
    assert {"EGP", "EUR", "SAR", "AED"} <= set(r.rates)


def test_convert(tmp_path: Path) -> None:
    (tmp_path / "fx.json").write_text(json.dumps(table("2999-01-01", EGP=50, EUR=0.5)))
    assert fx.convert(100, "usd", "EGP", tmp_path) == 5000
    assert fx.convert(100, "EUR", "EGP", tmp_path) == 10000
    assert fx.convert(7, "EGP", "egp", tmp_path) == pytest.approx(7)
    assert fx.convert(1, "XXX", "EGP", tmp_path) is None
    assert fx.convert(1, "EGP", "XXX", tmp_path) is None


def test_newest_table_wins_and_bad_files_are_ignored(tmp_path: Path) -> None:
    shipped = fx.rates(Path("/nonexistent"))
    file = tmp_path / "fx.json"
    tick = iter(range(1, 100))

    def write(text: str) -> None:
        """Each write gets its own time: Windows can give two quick writes the same one."""
        file.write_text(text)
        stamp = next(tick) * 1_000_000_000
        os.utime(file, ns=(stamp, stamp))

    write(json.dumps(table("2999-01-01", EGP=1)))
    assert fx.rates(tmp_path).date == "2999-01-01"
    write(json.dumps(table("2000-01-01", EGP=1)))  # older than the shipped one
    assert fx.rates(tmp_path).date == shipped.date
    for junk in ("not json", "[]", '{"base": "USD"}', json.dumps(table("2999-01-01", EGP=-1))):
        write(junk)
        assert fx.rates(tmp_path).date == shipped.date


@pytest.mark.parametrize(
    ("amount", "period", "month"),
    [(12000, "year", 1000), (500, "month", 500), (100, "week", 100 * 52 / 12),
     (10, "day", 220), (2, "hour", 352)],
)  # fmt: skip
def test_monthly(amount: float, period: str, month: float) -> None:
    assert fx.monthly(amount, period) == pytest.approx(month)


def payload(**extra: object) -> dict[str, object]:
    return {"result": "success", "time_last_update_unix": 1793404951, "base_code": "USD",
            "rates": {"USD": 1, "EGP": 49.5}, **extra}  # fmt: skip


def test_refresh_writes_the_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload())

    monkeypatch.setattr(fx, "_fetch", REAL_FETCH)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw)
    )
    assert asyncio.run(fx.refresh(tmp_path / "data")) is True
    assert [str(r.url) for r in seen] == [fx.URL] and not seen[0].content
    assert json.loads((tmp_path / "data" / "fx.json").read_text()) == {
        "base": "USD", "date": "2026-10-31", "rates": {"USD": 1, "EGP": 49.5},
    }  # fmt: skip
    assert fx.convert(2, "USD", "EGP", tmp_path / "data") == 99


@pytest.mark.parametrize(
    "response",
    [httpx.Response(500), httpx.Response(200, text="<html>"),
     httpx.Response(200, json={"result": "error"}),
     httpx.Response(200, json=payload(rates={"EGP": -3}))],
)  # fmt: skip
def test_refresh_failures_never_raise_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    monkeypatch.setattr(fx, "_fetch", REAL_FETCH)
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(lambda r: response), **kw),
    )  # fmt: skip
    assert asyncio.run(fx.refresh(tmp_path)) is False
    assert not (tmp_path / "fx.json").exists()


def test_refresh_survives_a_dead_network(tmp_path: Path) -> None:
    assert asyncio.run(fx.refresh(tmp_path)) is False  # conftest's offline stub raises
    assert not list(tmp_path.iterdir())
