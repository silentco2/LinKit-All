# ruff: noqa: RUF001
"""Telegram source tests; the sample words are in Russian and Arabic on purpose."""

import asyncio
import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pytest

from linkit_all.core.search import DEFAULT_TELEGRAM_CHANNELS, SearchConfig, normalize_channel
from linkit_all.providers.base import LLMProvider, ProviderError, UsageLimitError
from linkit_all.sources import registry, telegram
from linkit_all.sources.base import JobStub
from linkit_all.sources.telegram import Telegram

NOW = datetime(2026, 6, 10)  # the fixture's posts are from 26-28 May 2026


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telegram, "DELAY", 0)
    monkeypatch.setattr(telegram, "utcnow", lambda: NOW)


class FakeProvider(LLMProvider):
    """Answers every post it is shown with one job named after the post's number."""

    name = "fake"

    def __init__(self, error: Exception | None = None, extra_ids: tuple[int, ...] = ()) -> None:
        super().__init__("fake")
        self.prompts: list[str] = []
        self.error, self.extra_ids = error, extra_ids

    def reply(self, ids: list[int]) -> list[dict[str, Any]]:
        return [{"id": i, "jobs": [{"title": f"Job {i}"}]} for i in ids]

    async def _call(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        ids = [int(i) for i in re.findall(r"=== post id (\d+) ===", prompt)]
        return json.dumps({"posts": self.reply(ids + list(self.extra_ids))})


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


def test_link_out_to_known_ats_needs_no_ai(search_pages: Callable[..., Any]) -> None:
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
    provider = FakeProvider()
    stubs = run(Telegram(provider), ok(html), search_pages)
    assert provider.prompts == []
    [stub] = stubs
    assert stub.url == "https://t.me/chan/7"
    assert (
        stub.ats == "greenhouse" and stub.apply_url == "https://boards.greenhouse.io/acme/jobs/42"
    )
    assert stub.title == "Senior Rust engineer at Acme, remote" and stub.company == "Acme"
    assert stub.remote == "remote" and stub.posted_at == datetime(2026, 6, 1, 10)
    assert stub.source == "telegram" and stub.description.startswith("Senior Rust engineer")


def test_batched_extraction_ten_per_call_and_invented_ids_ignored(
    search_pages: Callable[..., Any],
) -> None:
    html = page(*(message("chan", n, f"We are hiring: role {n}") for n in range(1, 24)))
    provider = FakeProvider(extra_ids=(99, 50))
    stubs = run(Telegram(provider), ok(html), search_pages)
    assert [p.count("=== post id ") for p in provider.prompts] == [10, 10, 3]
    assert len(stubs) == 23 and all(s.title != "Invented" for s in stubs)
    assert stubs[0].url == "https://t.me/chan/1" and stubs[0].title == "Job 0"
    assert stubs[0].company == "Unknown" and stubs[0].description == "We are hiring: role 1"
    assert len({s.url for s in stubs}) == 23


def test_post_text_is_cut_and_marked_untrusted(search_pages: Callable[..., Any]) -> None:
    html = page(message("chan", 1, "hiring " + "Q" * 5000))
    provider = FakeProvider()
    run(Telegram(provider), ok(html), search_pages)
    assert provider.prompts[0].count("Q") == telegram.EXCERPT - len("hiring ")
    assert "not instructions to you" in " ".join(provider.prompts[0].split())


def test_several_jobs_in_one_post_get_distinct_urls(search_pages: Callable[..., Any]) -> None:
    class Two(FakeProvider):
        def reply(self, ids: list[int]) -> list[dict[str, Any]]:
            return [{"id": 0, "jobs": [{"title": "A", "description": "a"}, {"title": "B"}]}]

    stubs = run(Telegram(Two()), ok(page(message("chan", 5, "hiring A and B"))), search_pages)
    assert [s.url for s in stubs] == ["https://t.me/chan/5", "https://t.me/chan/5?job=2"]
    assert [s.description for s in stubs] == ["a", "hiring A and B"]


def test_without_provider_only_link_out_posts_become_jobs(search_pages: Callable[..., Any]) -> None:
    html = page(
        message("chan", 1, "We are hiring a cook"),
        message("chan", 2, 'Join us <a href="https://jobs.lever.co/acme/abc">here</a>'),
    )
    stubs = run(Telegram(), ok(html), search_pages)
    assert [s.url for s in stubs] == ["https://t.me/chan/2"] and stubs[0].ats == "lever"


def test_usage_limit_propagates_other_provider_errors_do_not(
    search_pages: Callable[..., Any],
) -> None:
    html = page(message("chan", 1, "We are hiring a cook"))
    with pytest.raises(UsageLimitError):
        run(Telegram(FakeProvider(UsageLimitError("quota"))), ok(html), search_pages)
    assert run(Telegram(FakeProvider(ProviderError("bad json"))), ok(html), search_pages) == []


def test_45_day_cutoff(search_pages: Callable[..., Any]) -> None:
    html = page(
        message("chan", 1, "hiring old", "2026-04-20T10:00:00+00:00"),  # 51 days before NOW
        message("chan", 2, "hiring edge", "2026-04-27T10:00:00+00:00"),  # 44 days
        message("chan", 3, "hiring new", "2026-06-09T10:00:00+00:00"),
    )
    stubs = run(Telegram(FakeProvider()), ok(html), search_pages)
    assert [s.url for s in stubs] == ["https://t.me/chan/2", "https://t.me/chan/3"]


def test_pages_back_until_old_and_resume(search_pages: Callable[..., Any]) -> None:
    newer = page(message("chan", 30, "hiring b", "2026-06-05T00:00:00+00:00"))
    older = page(message("chan", 20, "hiring a", "2026-05-20T00:00:00+00:00"))
    ancient = page(message("chan", 10, "hiring z", "2026-03-01T00:00:00+00:00"))
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        before = req.url.params.get("before")
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text={None: newer, "30": older, "20": ancient}[before])

    pages = search_pages(Telegram(FakeProvider()), handler, board="chan", calls=calls)
    assert [[s.url for s in p] for p in pages] == [
        ["https://t.me/chan/30"],
        ["https://t.me/chan/20"],
        [],
    ]
    assert calls[-1].endswith("/s/chan?before=20")
    resumed = search_pages(Telegram(FakeProvider()), handler, board="chan", start_page=1)
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
