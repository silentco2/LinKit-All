"""Shared async HTTP: per-host rate limits and retries on 429/5xx/network errors."""

import asyncio
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

USER_AGENT = "LinKitAll/0.1 (personal job search tool)"
ROBOTS_TOKEN = "LinKitAll"  # noqa: S105 - product token robots.txt groups are matched against
# Requests per second for hosts that throttle hard; others get default_rate.
SLOW_HOSTS = {
    "www.linkedin.com": 0.5,
    "wuzzuf.net": 0.1,  # robots.txt Crawl-delay 10
    "forasna.com": 0.1,  # robots.txt Crawl-delay 10
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
        self._robots: dict[str, RobotFileParser] = {}  # per host, for this run only
        self._robots_lock = asyncio.Lock()

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

    async def allowed(self, url: str) -> bool:
        """May we fetch `url`? Reads the host's robots.txt once per run and applies its
        Crawl-delay to that host. 4xx = no robots.txt = allowed; 5xx or network error = not."""
        parts = urlsplit(url)
        host = parts.netloc.lower()
        async with self._robots_lock:
            if host not in self._robots:
                self._robots[host] = await self._fetch_robots(parts.scheme, host)
        return self._robots[host].can_fetch(ROBOTS_TOKEN, url)

    async def _fetch_robots(self, scheme: str, host: str) -> RobotFileParser:
        rp = RobotFileParser()
        name = host.split(":")[0]
        block = ["User-agent: *", "Disallow: /"]  # 5xx or network error: no crawl
        try:  # one attempt, no retries: a failing robots.txt means "do not crawl" this run
            async with self._limiter(name):
                resp = await self.client.get(f"{scheme}://{host}/robots.txt")
            lines: list[str]
            if resp.status_code >= 500 or resp.status_code == 429:
                lines = block
            elif resp.status_code >= 400:
                lines = []  # no robots.txt (or none for us): everything is allowed
            else:
                lines = resp.text.splitlines()
        except httpx.HTTPError:
            lines = block
        rp.parse(lines)
        rp.modified()  # can_fetch() refuses until a check time is recorded
        if delay := rp.crawl_delay(ROBOTS_TOKEN):
            rate = 1 / float(delay)
            if rate < (self._rates.get(name) or self._default):
                self._rates[name] = rate
                self._limiters.pop(name, None)  # rebuilt with the slower rate
        return rp
        if resp.status_code >= 500 or resp.status_code == 429:
            rp.disallow_all = True
        elif resp.status_code >= 400:
            rp.allow_all = True
        else:
            rp.parse(resp.text.splitlines())
            rp.modified()  # can_fetch() refuses until a check time is recorded
            if delay := rp.crawl_delay(ROBOTS_TOKEN):
                rate = float(1 / float(delay))
                if rate < (self._rates.get(name) or self._default):
                    self._rates[name] = rate
                    self._limiters.pop(name, None)  # rebuilt with the slower rate
        return rp

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
