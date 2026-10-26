"""Tests never reach a live site: the apply runner's posting-liveness check gets no real client.
Tests that exercise it pass their own mock-transport `Http` to `Applier(http=...)`."""

from typing import NoReturn

import pytest

from linkit_all.apply import runner


def _no_network(*args: object, **kwargs: object) -> NoReturn:
    raise RuntimeError("no live network in tests")


@pytest.fixture(autouse=True)
def _offline_liveness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "make_client", _no_network)
