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
# Requests per second for hosts that throttle hard; others get default_rate.
SLOW_HOSTS = {
    "www.linkedin.com": 0.5,
    "wuzzuf.net": 0.1,  # robots.txt Crawl-delay 10
    "apply.workable.com": 1.0,
}
SLOW_SUFFIXES = {".myworkdayjobs.com": 1.0}  # one host per Workday tenant


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
        self._rates = {**SLOW_HOSTS, **(per_host_rate or {})}
        self._default = default_rate
        self._attempts = attempts
        self._limiters: dict[str, AsyncLimiter] = {}

    def _limiter(self, host: str) -> AsyncLimiter:
        if host not in self._limiters:
            rate = self._rates.get(host) or next(
                (r for suffix, r in SLOW_SUFFIXES.items() if host.endswith(suffix)), self._default
            )
            burst = max(1.0, rate)  # 0.5/s must be "1 per 2 s"; capacity can't go below 1
            self._limiters[host] = AsyncLimiter(burst, burst / rate)
        return self._limiters[host]

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """GET with rate limit + retries. 4xx (except 429) is returned to the caller."""
        return await self._send("GET", url, **kwargs)

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
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
                    resp = await self.client.request(method, url, **kwargs)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise RetryableStatus(resp)
                return resp
        raise AssertionError("unreachable")  # pragma: no cover

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = await self.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def post_json(self, url: str, body: Any, **kwargs: Any) -> Any:
        resp = await self._send("POST", url, json=body, **kwargs)
        resp.raise_for_status()
        return resp.json()


def make_client(**kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}, **kwargs
    )
