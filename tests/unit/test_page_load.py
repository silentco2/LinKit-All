"""Opening an application page: a dropped connection gets one more try, nothing else does."""

import asyncio
from typing import Any

import pytest
from playwright.async_api import Error as PlaywrightError

from linkit_all.apply.handlers.base import goto


class FakePage:
    def __init__(self, *errors: str) -> None:
        self.errors, self.calls = list(errors), 0

    async def goto(self, url: str, **kw: Any) -> None:
        self.calls += 1
        if self.errors:
            raise PlaywrightError(self.errors.pop(0))

    async def wait_for_timeout(self, ms: float) -> None:
        pass


def test_a_dropped_connection_is_tried_once_more() -> None:
    page = FakePage("Page.goto: net::ERR_CONNECTION_CLOSED at https://jobs.ashbyhq.com/x")
    asyncio.run(goto(page, "https://jobs.ashbyhq.com/x"))  # type: ignore[arg-type]
    assert page.calls == 2


@pytest.mark.parametrize(
    "errors",
    [
        ["net::ERR_CONNECTION_RESET", "net::ERR_CONNECTION_RESET"],  # twice: the site is down
        ["net::ERR_NAME_NOT_RESOLVED"],  # not a dropped connection: no retry
    ],
)
def test_other_failures_are_not_retried(errors: list[str]) -> None:
    page = FakePage(*errors)
    with pytest.raises(PlaywrightError):
        asyncio.run(goto(page, "https://x.test"))  # type: ignore[arg-type]
    assert page.calls == len(errors)
