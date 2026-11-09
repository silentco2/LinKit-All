"""Pressing Apply on a board whose script redirects later than the page settles."""

import asyncio
from typing import Any

import pytest

from linkit_all.apply import runner

BEFORE = ("https://board.test/job", 0)
AWAY = ("https://ats.test/form", 5)


def _moved(monkeypatch: pytest.MonkeyPatch, seen: list[tuple[str, int]]) -> bool:
    """`seen` is what the page looks like at each look; the last one stays."""

    async def where(_page: Any) -> tuple[str, int]:
        return seen.pop(0) if len(seen) > 1 else seen[0]

    async def settle(_page: Any) -> None:
        return None

    monkeypatch.setattr(runner, "_where", where)
    monkeypatch.setattr(runner, "_settle", settle)
    monkeypatch.setattr(runner, "APPLY_REDIRECT_WAIT_S", 1.2)
    return asyncio.run(runner._moved_on(None, BEFORE))  # type: ignore[arg-type]


def test_a_late_redirect_is_waited_for(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _moved(monkeypatch, [BEFORE, BEFORE, AWAY]) is True


def test_a_page_that_never_moves_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _moved(monkeypatch, [BEFORE]) is False


def test_a_half_loaded_page_is_not_mistaken_for_a_move(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _moved(monkeypatch, [("https://board.test/job", 3), BEFORE]) is False
