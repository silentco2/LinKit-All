"""D2: pasted or scraped links never reach this computer or its private network."""

import asyncio

import httpx
import pytest

from linkit_all.sources import http as http_mod
from linkit_all.sources.http import BlockedAddress, Http, is_public, make_client

DNS = {
    "jobs.example.com": ["93.184.216.34"],
    "intranet.example.com": ["10.0.0.5"],
    "mixed.example.com": ["93.184.216.34", "192.168.1.10"],
    "metadata.example.com": ["169.254.169.254"],
    "six.example.com": ["fd00::1"],
}


@pytest.fixture
def lookups(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def resolve(host: str) -> list[str]:
        seen.append(host)
        if host not in DNS:
            raise OSError("no such host")
        return DNS[host]

    monkeypatch.setattr(http_mod, "_resolve", resolve)
    return seen


def fetch(url: str, handler: object = None) -> httpx.Response:
    async def go() -> httpx.Response:
        transport = httpx.MockTransport(handler or (lambda r: httpx.Response(200, text="ok")))  # type: ignore[arg-type]
        async with make_client(transport=transport) as client:
            return await Http(client, default_rate=1e6).get(url)

    return asyncio.run(go())


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.0.1", "169.254.169.254", "100.64.0.1",
     "0.0.0.0",  # noqa: S104 - a value under test, nothing binds to it
     "::1", "::", "fe80::1%eth0", "fc00::1", "::ffff:127.0.0.1", "not-an-ip", ""],
)  # fmt: skip
def test_private_addresses_are_not_public(address: str) -> None:
    assert not is_public(address)


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_are_public(address: str) -> None:
    assert is_public(address)


@pytest.mark.parametrize(
    "url",
    [
        "http://intranet.example.com/jobs",  # a name that resolves into the private network
        "http://mixed.example.com/",  # one private address among public ones is enough
        "http://metadata.example.com/latest/meta-data/",
        "http://six.example.com/",
        "http://127.0.0.1:8765/api/profile",  # literals never reach the resolver
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:10.0.0.1]/",
    ],
)
def test_private_targets_are_refused_once(url: str, lookups: list[str]) -> None:
    with pytest.raises(BlockedAddress):
        fetch(url)
    assert len(lookups) <= 1  # refused, not retried


def test_public_host_and_our_own_localhost_pass(lookups: list[str]) -> None:
    assert fetch("https://jobs.example.com/a").text == "ok"
    assert fetch("http://localhost:8765/api/health").text == "ok"
    assert lookups == ["jobs.example.com"]  # localhost is allowed by name, not resolved


def test_unresolvable_host_is_left_to_fail_on_its_own(lookups: list[str]) -> None:
    assert fetch("https://nowhere.example.com/").status_code == 200  # the mock answers


def test_a_redirect_into_the_private_network_is_refused(lookups: list[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "jobs.example.com":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/"})
        return httpx.Response(200, text="secret")

    with pytest.raises(BlockedAddress):
        fetch("https://jobs.example.com/go", handler)


def test_blocked_address_is_an_http_error() -> None:
    assert issubclass(BlockedAddress, httpx.HTTPError)
    assert not issubclass(BlockedAddress, httpx.TransportError)
