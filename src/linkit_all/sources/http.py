"""Shared async HTTP: per-host rate limits and retries on 429/5xx/network errors."""

from typing import Any
from urllib.parse import urlsplit

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

USER_AGENT = "LinKitAll/0.1 (personal job search tool)"


class RetryableStatus(Exception):
    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"HTTP {response.status_code} for {response.request.url}")
        self.response = response


class Http:
    def __init__(
        self,
        client: httpx.AsyncClient,
        per_host_rate: dict[str, float] | None = None,
        default_rate: float = 2.0,  # requests per second per host
        attempts: int = 4,
    ) -> None:
        self.client = client
        self._rates = per_host_rate or {}
        self._default = default_rate
        self._attempts = attempts
        self._limiters: dict[str, AsyncLimiter] = {}

    def _limiter(self, host: str) -> AsyncLimiter:
        if host not in self._limiters:
            self._limiters[host] = AsyncLimiter(self._rates.get(host, self._default), 1)
        return self._limiters[host]

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """GET with rate limit + retries. 4xx (except 429) is returned to the caller."""
        limiter = self._limiter(urlsplit(url).hostname or "")
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._attempts),
            wait=wait_exponential(multiplier=1, max=30),
            retry=retry_if_exception_type((RetryableStatus, httpx.TransportError)),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                async with limiter:
                    resp = await self.client.get(url, **kwargs)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise RetryableStatus(resp)
                return resp
        raise AssertionError("unreachable")  # pragma: no cover

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = await self.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()


def make_client(**kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}, **kwargs
    )
