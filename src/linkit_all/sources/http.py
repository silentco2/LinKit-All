"""Shared async HTTP: per-host rate limits and retries on 429/5xx/network errors."""

import asyncio
import contextlib
import re
import string
from typing import Any
from urllib.parse import quote, urlsplit

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


_URL_SAFE = "!#$&'()*+,/:;=?@[]%~-._"
_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")


def _norm(s: str) -> str:
    """Percent-encode non-ASCII, uppercase escapes, decode unreserved ones: comparable paths."""

    def fix(m: re.Match[str]) -> str:
        ch = chr(int(m[1], 16))
        return ch if ch in _UNRESERVED else "%" + m[1].upper()

    return re.sub(r"%([0-9A-Fa-f]{2})", fix, quote(s, safe=_URL_SAFE))


class Robots:
    """One host's robots.txt for one product token, per RFC 9309: every group naming the token
    (else every `*` group) is merged; `*` and `$` work in paths; the longest matching rule wins,
    Allow on a tie; `Crawl-delay` is the largest of the selected groups."""

    def __init__(self, text: str, token: str = ROBOTS_TOKEN) -> None:
        groups: list[tuple[set[str], list[tuple[bool, str]], list[float]]] = []
        in_agents = False  # consecutive User-agent lines share one group
        for raw in text.splitlines():
            key, sep, value = raw.split("#", 1)[0].partition(":")
            key, value = key.strip().lower(), value.strip()
            if not sep:
                continue
            if key == "user-agent":
                if not in_agents:
                    groups.append((set(), [], []))
                groups[-1][0].add(value.lower())
                in_agents = True
            elif key in ("allow", "disallow", "crawl-delay") and groups:
                in_agents = False
                if key == "crawl-delay":
                    with contextlib.suppress(ValueError):
                        groups[-1][2].append(float(value))
                elif value:  # empty Disallow = allow everything; empty Allow = nothing
                    groups[-1][1].append((key == "allow", value))
        mine = [g for g in groups if token.lower() in g[0]] or [g for g in groups if "*" in g[0]]
        self._rules: list[tuple[int, bool, re.Pattern[str]]] = []
        for _, rules, _ in mine:
            for allow, pattern in rules:
                pat = _norm(pattern if pattern[0] in "/*" else "/" + pattern)
                body = pat.removesuffix("$")
                rx = ".*".join(re.escape(part) for part in body.split("*"))
                self._rules.append(
                    (len(pat), allow, re.compile(rx + (r"\Z" if body != pat else "")))
                )
        self.crawl_delay = max((d for g in mine for d in g[2] if d > 0), default=None)

    def can_fetch(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.path == "/robots.txt":
            return True
        path = _norm((parts.path or "/") + (f"?{parts.query}" if parts.query else ""))
        hits = [(n, allow) for n, allow, rx in self._rules if rx.match(path)]
        return max(hits)[1] if hits else True  # (length, allow): longest wins, True beats False


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
        self._robots: dict[str, Robots] = {}  # per host, for this run only
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
        return self._robots[host].can_fetch(url)

    async def _fetch_robots(self, scheme: str, host: str) -> Robots:
        name = host.split(":")[0]
        text = "User-agent: *\nDisallow: /"  # 5xx or network error: no crawl
        try:  # one attempt, no retries: a failing robots.txt means "do not crawl" this run
            async with self._limiter(name):
                resp = await self.client.get(f"{scheme}://{host}/robots.txt")
            if resp.status_code < 400:
                text = resp.text
            elif resp.status_code < 500 and resp.status_code != 429:
                text = ""  # no robots.txt (or none for us): everything is allowed
        except httpx.HTTPError:
            pass
        robots = Robots(text)
        if delay := robots.crawl_delay:
            rate = 1 / delay
            if rate < (self._rates.get(name) or self._default):
                self._rates[name] = rate
                self._limiters.pop(name, None)  # rebuilt with the slower rate
        return robots

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
