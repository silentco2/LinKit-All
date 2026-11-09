# ruff: noqa: RUF001
"""Telegram source tests; the sample words are in Russian and Arabic on purpose."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pytest

from linkit_all.core.search import DEFAULT_TELEGRAM_CHANNELS, SearchConfig, normalize_channel
from linkit_all.sources import registry, telegram
from linkit_all.sources.base import JobStub
from linkit_all.sources.telegram import Telegram

NOW = datetime(2026, 6, 10)  # the fixture's posts are from 26-28 May 2026


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telegram, "DELAY", 0)
    monkeypatch.setattr(telegram, "utcnow", lambda: NOW)


def message(channel: str, num: int, text_html: str, when: str = "2026-06-01T10:00:00+00:00") -> str:
    return (
        f'<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" '
        f'data-post="{channel}/{num}"><div class="tgme_widget_message_bubble">'
        f'<div class="tgme_widget_message_text js-message_text" dir="auto">{text_html}</div>'
        f'<a class="tgme_widget_message_date" href="https://t.me/{channel}/{num}">'
        f'<time datetime="{when}" class="time">10:00</time></a></div></div></div>'
    )


def page(*messages: str) -> str:
    return f"<html><body><section>{''.join(messages)}</section></body></html>"


def run(
    source: Telegram,
    handler: Callable[[httpx.Request], httpx.Response],
    search_pages: Callable[..., list[list[JobStub]]],
    **kw: Any,
) -> list[JobStub]:
    return [s for p in search_pages(source, handler, board="chan", **kw) for s in p]


def ok(html: str) -> Callable[[httpx.Request], httpx.Response]:
    """The first preview page is `html`; older pages (?before=) are empty."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=page() if "before" in req.url.params else html)

    return handler


def test_parse_real_preview(load_fixture: Callable[[str], Any]) -> None:
    posts = telegram.parse_posts(load_fixture("telegram/hrlunapark.html"), "HRLunapark")
    assert [p.id for p in posts] == [391, 392]
    assert posts[0].posted_at == datetime(2026, 5, 26, 14, 32, 18)
    assert posts[0].text.startswith("tl;dr: recruiter at Luna Park, part-time friendly, remote")
    assert "\n" in posts[0].text and "<" not in posts[0].text
    assert telegram.parse_posts("<html></html>", "x") == []


def test_parse_skips_other_channels_and_empty_posts() -> None:
    html = page(
        message("chan", 1, "hiring a dev"),
        message("other", 2, "hiring someone"),
        message("chan", 3, "  "),
    )
    assert [p.id for p in telegram.parse_posts(html, "chan")] == [1]


def test_parse_keeps_http_links_only() -> None:
    html = page(
        message(
            "chan",
            1,
            '<a href="https://boards.greenhouse.io/acme/jobs/1">apply</a> '
            '<a href="tg://resolve?domain=x">dm</a> <a href="/rel">r</a>',
        )
    )
    assert telegram.parse_posts(html, "chan")[0].links == (
        "https://boards.greenhouse.io/acme/jobs/1",
    )


@pytest.mark.parametrize(
    "text",
    [
        "We are hiring a Python developer",
        "Looking for a designer",
        "Salary: negotiable",
        "Ищем разработчика в команду",
        "Відкрита вакансія: тестувальник",
        "Empresa: Acme\nUbicación: Madrid",
        "$120k-$180k senior engineer",
        "250 000 руб на руки",
        "مطلوب مهندس برمجيات",
        "فرصة عمل في القاهرة",
        "نبحث عن محاسب",
        "وَظِيفَةٌ شاغِرَة",  # with diacritics
        "إعلان توظيف جديد",  # alef with hamza
        "مطلوبـــة محاسبة",  # tatweel, taa marbuta
        "وظائف عن بعد",
    ],
)
def test_prefilter_accepts(text: str) -> None:
    assert telegram.looks_like_vacancy(text)


@pytest.mark.parametrize(
    "text",
    [
        "Good morning everyone, nice weather today",
        "Купил кофе и пошёл гулять",
        "I am looking... no wait, I am searching jobs",  # job seeker, no marker
        "Шукаю роботу",  # "I am looking for work": the seeker form
        "No voy a bloquear a esa empresa en el bot",
        "صباح الخير للجميع",
        "",
    ],
)
def test_prefilter_rejects(text: str) -> None:
    assert not telegram.looks_like_vacancy(text)


def test_fold_merges_arabic_variants() -> None:
    assert telegram.fold("أإآ ة ى ئ ؤ") == telegram.fold("ااا ه ي ي و")
    assert telegram.fold("مَطْلُوب") == "مطلوب"


def test_link_out_to_known_ats(search_pages: Callable[..., Any]) -> None:
    html = page(
        message(
            "chan",
            7,
            'Senior Rust engineer at Acme, remote<br/><a href="https://boards.greenhouse.io/acme/jobs/42">'
            "apply here</a>",
        ),
        message(
            "chan", 8, 'Nothing about work here, just a link <a href="https://example.com/x">x</a>'
        ),
    )
    [stub] = run(Telegram(), ok(html), search_pages)
    assert stub.url == "https://t.me/chan/7"
    assert (
        stub.ats == "greenhouse" and stub.apply_url == "https://boards.greenhouse.io/acme/jobs/42"
    )
    assert stub.title == "Senior Rust engineer at Acme, remote" and stub.company == "Acme"
    assert stub.remote == "remote" and stub.posted_at == datetime(2026, 6, 1, 10)
    assert stub.source == "telegram" and stub.description.startswith("Senior Rust engineer")


def test_45_day_cutoff(search_pages: Callable[..., Any]) -> None:
    html = page(
        message(
            "chan", 1, "hiring old hr@acme.com", "2026-04-20T10:00:00+00:00"
        ),  # 51 days before NOW
        message("chan", 2, "hiring edge hr@acme.com", "2026-04-27T10:00:00+00:00"),  # 44 days
        message("chan", 3, "hiring new hr@acme.com", "2026-06-09T10:00:00+00:00"),
    )
    stubs = run(Telegram(), ok(html), search_pages)
    assert [s.url for s in stubs] == ["https://t.me/chan/2", "https://t.me/chan/3"]


def test_pages_back_until_old_and_resume(search_pages: Callable[..., Any]) -> None:
    newer = page(message("chan", 30, "hiring b hr@acme.com", "2026-06-05T00:00:00+00:00"))
    older = page(message("chan", 20, "hiring a hr@acme.com", "2026-05-20T00:00:00+00:00"))
    ancient = page(message("chan", 10, "hiring z hr@acme.com", "2026-03-01T00:00:00+00:00"))
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        before = req.url.params.get("before")
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text={None: newer, "30": older, "20": ancient}[before])

    pages = search_pages(Telegram(), handler, board="chan", calls=calls)
    assert [[s.url for s in p] for p in pages] == [
        ["https://t.me/chan/30"],
        ["https://t.me/chan/20"],
        [],
    ]
    assert calls[-1].endswith("/s/chan?before=20")
    resumed = search_pages(Telegram(), handler, board="chan", start_page=1)
    assert [[s.url for s in p] for p in resumed] == [["https://t.me/chan/20"], []]


def test_empty_preview_is_unsupported(
    search_pages: Callable[..., Any],
) -> None:
    from linkit_all.sources.careers import Unsupported

    with pytest.raises(Unsupported, match="no public posts"):
        run(Telegram(), ok(page()), search_pages)


def test_http_error_raises(search_pages: Callable[..., Any]) -> None:
    with pytest.raises(httpx.HTTPStatusError):
        run(Telegram(), lambda req: httpx.Response(404), search_pages)


def test_requests_are_spaced_by_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(s: float) -> None:
        slept.append(s)
        await real_sleep(0)

    monkeypatch.setattr(telegram, "DELAY", 2.0)
    monkeypatch.setattr(telegram.asyncio, "sleep", fake_sleep)
    src = Telegram()

    async def go() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text=page()))
        ) as c:
            http = telegram.Http(c, attempts=1)
            await src._preview(http, "chan", 0)
            await src._preview(http, "chan", 0)

    asyncio.run(go())
    assert len(slept) == 1 and 0 < slept[0] <= 2.0


def test_tasks_and_registration() -> None:
    cfg = SearchConfig.model_validate(
        {"sources": {"enabled": ["telegram"], "telegram_channels": ["@A_channel", "chan2"]}}
    )
    src = registry()["telegram"]
    assert src.is_enabled(cfg) and not src.is_enabled(SearchConfig())
    assert [(t.board, t.key) for t in src.tasks(cfg)] == [
        ("A_channel", "telegram:a_channel"),
        ("chan2", "telegram:chan2"),
    ]


@pytest.mark.parametrize(
    ("raw", "name"),
    [
        ("@Remoteit", "Remoteit"),
        ("t.me/job_python", "job_python"),
        ("https://t.me/s/job_python?before=5", "job_python"),
        ("http://telegram.me/hrlunapark/391", "hrlunapark"),
        ("  zrabota ", "zrabota"),
    ],
)
def test_channel_names_normalized(raw: str, name: str) -> None:
    assert normalize_channel(raw) == name


def test_channel_config_validation_and_defaults() -> None:
    cfg = SearchConfig.model_validate(
        {"sources": {"telegram_channels": ["@Foo_bar", "t.me/foo_BAR", "", "baz_qux"]}}
    )
    assert cfg.sources.telegram_channels == ["Foo_bar", "baz_qux"]
    with pytest.raises(ValueError, match="not a Telegram channel"):
        SearchConfig.model_validate({"sources": {"telegram_channels": ["not a channel!"]}})
    default = SearchConfig().sources.telegram_channels
    assert len(default) == 95 and default == list(DEFAULT_TELEGRAM_CHANNELS)
    assert (
        SearchConfig.model_validate(
            {"sources": {"telegram_channels": []}}
        ).sources.telegram_channels
        == []
    )


def test_email_post_is_a_mailto_job(search_pages: Callable[..., Any]) -> None:
    html = page(message("chan", 1, "Backend dev needed in Cairo, send your CV to hr@acme.com"))
    [stub] = run(Telegram(), ok(html), search_pages)
    assert stub.apply_url == "mailto:hr@acme.com" and stub.url == "https://t.me/chan/1"
    assert stub.title == "Backend dev needed in Cairo" and stub.company == "Acme"
    assert stub.extra == {"channel": "chan", "post": 1}


def job_site(jsonld: str = "") -> Callable[[httpx.Request], httpx.Response]:
    """Telegram preview for a post linking to acme.com/careers/42, and that page."""
    html = page(message("chan", 1, "Backend dev wanted, remote. Apply at acme.com/careers/42"))
    preview = ok(html)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host != "acme.com":
            return preview(req)
        if req.url.path != "/careers/42":
            return httpx.Response(404)
        return httpx.Response(
            200, text=f"<html>{jsonld}<body><h1>Careers</h1><p>x</p></body></html>"
        )

    return handler


def test_unknown_link_goes_to_the_scraper(search_pages: Callable[..., Any]) -> None:
    ld = (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Backend Engineer",'
        '"hiringOrganization":{"name":"Acme Inc"},"description":"Build APIs."}</script>'
    )
    [stub] = run(Telegram(), job_site(ld), search_pages)
    assert (stub.title, stub.company) == ("Backend Engineer", "Acme Inc")
    assert stub.apply_url == "https://acme.com/careers/42" and stub.url == "https://t.me/chan/1"
    assert stub.source == "telegram" and stub.description == "Build APIs."


def test_page_without_job_data_keeps_the_posts_title(search_pages: Callable[..., Any]) -> None:
    [stub] = run(Telegram(), job_site(), search_pages)
    assert stub.title == "Backend dev wanted, remote"  # not the page's "Careers"
    assert stub.apply_url == "https://acme.com/careers/42"


def test_stored_post_does_not_fetch_its_link(search_pages: Callable[..., Any]) -> None:
    hosts: list[str] = []
    site = job_site()

    def spy(req: httpx.Request) -> httpx.Response:
        hosts.append(req.url.host)
        return site(req)

    src = Telegram()
    src.seen_url = lambda url: url == "https://t.me/chan/1"
    [stub] = run(src, spy, search_pages)
    assert "acme.com" not in hosts and stub.url == "https://t.me/chan/1"


def test_posts_without_a_way_to_apply_and_seekers_are_dropped(
    search_pages: Callable[..., Any],
) -> None:
    html = page(
        message("chan", 1, "We are hiring a cook, write to @recruiter"),
        message("chan", 2, "We are hiring a cook"),
        message("chan", 3, "Ищу работу, резюме: me@acme.com"),
    )
    assert run(Telegram(), ok(html), search_pages) == []


def test_a_link_repeated_across_posts_is_a_footer(search_pages: Callable[..., Any]) -> None:
    foot = '<a href="https://promo.example/join">our site</a>'
    html = page(
        message("chan", 1, f"We are hiring a cook {foot}"),
        message("chan", 2, f"We are hiring a baker {foot}"),
    )
    assert run(Telegram(), ok(html), search_pages) == []
