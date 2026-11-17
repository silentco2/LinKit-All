"""Shared async HTTP: per-host rate limits, retries on 429/5xx/network errors, and a guard
that keeps pasted or scraped links away from this computer and its network (SSRF).

The address guard's logic is adapted from career-ops (MIT)."""

import asyncio
import contextlib
import ipaddress
from collections.abc import Mapping
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
ROBOTS_TOKEN = "LinKitAll"  # noqa: S105 - product token robots.txt Crawl-delay groups name
# Requests per second for hosts that throttle hard; others get default_rate.
SLOW_HOSTS = {
    "www.linkedin.com": 0.5,
    "wuzzuf.net": 0.1,  # robots.txt Crawl-delay 10
    "forasna.com": 0.1,  # robots.txt Crawl-delay 10
    "apply.workable.com": 1.0,
    "api.higherme.com": 1 / 3,
    "join.com": 1.5,
    "www.workstream.us": 1.0,  # refuses ~1.4 req/s per IP
}
# One host per tenant (Workday).
SLOW_SUFFIXES = {".myworkdayjobs.com": 1.0, ".myworkdaysite.com": 1.0}


def crawl_delay(text: str, token: str = ROBOTS_TOKEN) -> float | None:
    """Largest `Crawl-delay` among the robots.txt groups naming `token` (else the `*` groups).
    Only pacing is read from robots.txt; Allow/Disallow rules are ignored."""
    groups: list[tuple[set[str], list[float]]] = []
    in_agents = False  # consecutive User-agent lines share one group
    for raw in text.splitlines():
        key, sep, value = raw.split("#", 1)[0].partition(":")
        key, value = key.strip().lower(), value.strip()
        if not sep:
            continue
        if key == "user-agent":
            if not in_agents:
                groups.append((set(), []))
            groups[-1][0].add(value.lower())
            in_agents = True
        elif key in ("allow", "disallow", "crawl-delay") and groups:
            in_agents = False
            if key == "crawl-delay":
                with contextlib.suppress(ValueError):
                    groups[-1][1].append(float(value))
    mine = [g for g in groups if token.lower() in g[0]] or [g for g in groups if "*" in g[0]]
    return max((d for g in mine for d in g[1] if d > 0), default=None)


class BlockedAddress(httpx.RequestError):
    """The link points at this computer or its private network: never fetched. Not a
    `TransportError`, so it is not retried; callers that catch `httpx.HTTPError` see it."""


async def _resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    return [str(info[4][0]) for info in infos]


def is_public(address: str) -> bool:
    """False for loopback, link-local (169.254.169.254 is the cloud metadata service), RFC1918,
    CGNAT, unique-local, multicast, reserved and unparseable addresses."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])  # fe80::1%eth0
    except ValueError:
        return False  # refuse to guess
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 is loopback however it is spelled
    return ip.is_global


async def guard(request: httpx.Request) -> None:
    """httpx request hook: runs before every request and every redirect hop.

    `localhost` by name stays allowed (our own local API); everything else is resolved first
    and refused when any of its addresses is not public.
    ponytail: checked just before the connection, not pinned to it, so a name that answers
    public then private (DNS rebinding) can slip by; pin the address in a custom transport if
    that ever matters for a local single-user app."""
    host = request.url.host
    if host == "localhost":
        return
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        try:
            addresses = await _resolve(host)
        except OSError:
            return  # does not resolve: the request fails on its own
    if not all(is_public(a) for a in addresses):
        raise BlockedAddress(f"{host} is a private or local address: not fetched", request=request)


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
        self._robots_read: set[str] = set()  # hosts whose Crawl-delay was looked up this run
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
        return await self.request("GET", url, **kwargs)

    async def post_form(
        self, url: str, data: Mapping[str, Any], headers: Mapping[str, str] | None = None
    ) -> httpx.Response:
        """POST an urlencoded form, like `get`: 4xx (except 429) is returned to the caller."""
        return await self.request("POST", url, data=dict(data), headers=dict(headers or {}))

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Any method, rate-limited and retried on 429/5xx/network errors. A 4xx other than 429
        (403, say) is returned, not raised, so the caller can look at it."""
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
        """Always True: robots.txt is not enforced. The first call per host reads its robots.txt
        once, only to apply its Crawl-delay to that host's rate limit."""
        parts = urlsplit(url)
        host = parts.netloc.lower()
        async with self._robots_lock:
            if host not in self._robots_read:
                self._robots_read.add(host)
                await self._apply_crawl_delay(parts.scheme, host)
        return True

    async def _apply_crawl_delay(self, scheme: str, host: str) -> None:
        name = host.split(":")[0]
        try:  # one attempt, no retries; any failure just leaves the rate unchanged
            async with self._limiter(name):
                resp = await self.client.get(f"{scheme}://{host}/robots.txt")
        except httpx.HTTPError:
            return
        if resp.status_code < 400 and (delay := crawl_delay(resp.text)):
            rate = 1 / delay
            if rate < (self._rates.get(name) or self._default):
                self._rates[name] = rate
                self._limiters.pop(name, None)  # rebuilt with the slower rate

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = await self.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def post_json(self, url: str, body: Any, **kwargs: Any) -> Any:
        resp = await self.request("POST", url, json=body, **kwargs)
        resp.raise_for_status()
        return resp.json()


def make_client(**kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        event_hooks={"request": [guard]},
        **kwargs,
    )
