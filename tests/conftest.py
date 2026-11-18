"""Tests never reach a live site: the apply runner's posting-liveness check gets no real client.
Tests that exercise it pass their own mock-transport `Http` to `Applier(http=...)`.
The exchange-rate refresh at run start fails the same way (it is allowed to fail)."""

from collections.abc import Iterator
from typing import NoReturn

import httpx
import pytest

from linkit_all.apply import runner
from linkit_all.core import fx
from linkit_all.tailor.render import libreoffice


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """The UI tests' session browser keeps Playwright's sync loop running on this thread, and
    asyncio.run then fails in every later test: so they go last."""
    items.sort(key=lambda item: "/e2e/ui/" in item.nodeid)


def _no_network(*args: object, **kwargs: object) -> NoReturn:
    raise RuntimeError("no live network in tests")


@pytest.fixture(autouse=True)
def _offline_liveness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "make_client", _no_network)


@pytest.fixture(autouse=True, scope="session")
def _lo_profile(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """LibreOffice's profile goes to a scratch folder, never the real data folder."""
    folder = tmp_path_factory.mktemp("lo-profile")
    mp = pytest.MonkeyPatch()
    mp.setattr(libreoffice, "profile_dir", lambda: folder)
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def _offline_fx(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fail() -> NoReturn:
        raise RuntimeError("no live network in tests")

    monkeypatch.setattr(fx, "_fetch", _fail)


@pytest.fixture(autouse=True)
def _offline_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding a careers page fetches it once for its name; tests that care pass a fake transport."""
    from linkit_all.sources import labels

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no live network in tests", request=request)

    monkeypatch.setattr(labels, "_TRANSPORT", httpx.MockTransport(refuse))
