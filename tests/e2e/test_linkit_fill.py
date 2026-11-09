"""LinkIt Fill extension, end to end: Playwright's Chromium loads the unpacked extension, the
real API runs on a local port, and a saved job form is served for a fake job site. The
extension fills the form and never submits it. Needs Playwright's own Chromium (branded Chrome
no longer loads unpacked extensions from the command line)."""

import asyncio
import json
import shutil
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from playwright.async_api import Route, async_playwright

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
sys.path.insert(0, str(Path(__file__).parent))
from test_agent_form import FakeAI
from test_matching import fake_embed
from test_tailor import make_cv

import linkit_all.pipeline as pipeline
import linkit_all.providers as providers
from linkit_all.api.app import create_app
from linkit_all.api.assist import pairing_token
from linkit_all.core.config import Settings
from linkit_all.core.models import ActionItem, ActionKind, AnswerEntry, Job, JobState
from linkit_all.core.profile import ProfileIn, import_profile

EXT = Path(__file__).parents[2] / "src" / "linkit_all" / "extension"
FORM = (Path(__file__).parents[1] / "fixtures/agent/synthetic_two_page.html").read_text("utf-8")
EXTRA_FORM = FORM.replace(
    '<p id="err1"',
    '<label for="shirt">T-shirt size</label><input id="shirt" name="shirt" type="text">'
    '<label for="fact">A fun fact *</label><textarea id="fact" name="fact" required></textarea>'
    '<p id="err1"',
)
JOB_URL = "https://jobs.example-board.test/apply/7"


def _chromium() -> Path | None:
    """Newest Chromium that Playwright downloaded (any build: only its binary is used)."""
    home = Path.home() / "AppData" / "Local" / "ms-playwright"
    found = sorted(home.glob("chromium-*/chrome-win*/chrome.exe")) if home.exists() else []
    return found[-1] if found else None


CHROMIUM = _chromium()
pytestmark = pytest.mark.skipif(CHROMIUM is None, reason="Playwright Chromium not installed")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def app_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings)
    db = app.state.db
    cv = make_cv(tmp_path / "cv.docx")
    import_profile(db, ProfileIn(full_name="Jane Doe", email="jane@example.com",
                                 phone="+44 20 0000 0000", location="London", cv_path=cv),
                   settings.data_dir)  # fmt: skip
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%test\n")
    with db.begin() as s:
        job = Job(source="board", url=JOB_URL, title="Backend Engineer", company="Acme",
                  location="London", description="Python", dedupe_hash="h", state=JobState.needs_user,
                  data={"apply_url": JOB_URL, "cv_pdf": str(pdf)})  # fmt: skip
        s.add(job)
        s.flush()
        s.add(ActionItem(job_id=job.id, kind=ActionKind.apply_in_browser, code="apply_in_browser"))
    monkeypatch.setattr(providers, "get_provider", lambda *a, **k: FakeAI())

    async def embedder(_settings: Any) -> Any:
        return fake_embed

    monkeypatch.setattr(pipeline, "_get_embedder", embedder)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    ext = shutil.copytree(EXT, tmp_path / "ext")  # a copy: the real app.json is the running app's
    (ext / "app.json").write_text(json.dumps({"port": port}), "utf-8")
    yield {"port": port, "token": pairing_token(settings), "db": db, "data": tmp_path, "ext": ext}
    server.should_exit = True
    thread.join(timeout=10)


def test_extension_fills_the_waiting_job_and_never_submits(app_server: dict[str, Any]) -> None:
    posts: list[str] = []

    async def go() -> dict[str, Any]:
        async with async_playwright() as pw:
            ctx = await pw.chromium.launch_persistent_context(
                str(app_server["data"] / "chromium"),
                executable_path=str(CHROMIUM),
                headless=False,  # the new headless mode below runs extensions; the old one does not
                args=[
                    "--headless=new",
                    f"--disable-extensions-except={app_server['ext']}",
                    f"--load-extension={app_server['ext']}",
                ],
            )

            async def site(route: Route) -> None:
                if route.request.method == "POST":
                    posts.append(route.request.url)
                await route.fulfill(body=EXTRA_FORM, content_type="text/html")

            await ctx.route("https://jobs.example-board.test/**", site)
            worker = (
                ctx.service_workers[0]
                if ctx.service_workers
                else await ctx.wait_for_event("serviceworker")
            )
            await worker.evaluate(
                "(token) => chrome.storage.local.set({token})",
                app_server["token"],
            )
            page = await ctx.new_page()
            await page.goto(JOB_URL)
            await page.wait_for_function(
                "document.querySelector('#full_name').value !== ''", timeout=30000
            )
            got = {
                "name": await page.input_value("#full_name"),
                "email": await page.input_value("#email"),
                "honeypot": await page.input_value("#website_url"),
            }
            await page.wait_for_function("document.querySelector('#fact').value !== ''")
            await asyncio.sleep(1)  # the panel finishes this step
            await page.fill("#shirt", "Large")  # LinkIt left this one empty
            await page.fill("#fact", "I keep bees")  # and wrote this one with the AI
            await page.focus("#email")
            for _ in range(40):
                with app_server["db"]() as s:
                    saved = {e.question: (e.answer, e.source) for e in s.query(AnswerEntry)}
                if saved.get("T-shirt size") and saved.get("A fun fact", ("", ""))[1] == "user":
                    break
                await asyncio.sleep(0.25)
            got["saved"] = saved
            await ctx.close()
            return got

    got = asyncio.run(go())
    saved = got.pop("saved")
    assert got == {"name": "Jane Doe", "email": "jane@example.com", "honeypot": ""}
    assert saved["T-shirt size"] == ("Large", "user")
    assert saved["A fun fact"] == ("I keep bees", "user")
    assert posts == []  # nothing was submitted
    with app_server["db"]() as s:
        assert s.query(Job).one().state == JobState.needs_user  # only the user marks it applied


def test_the_job_follows_linkedins_apply_to_the_employers_site(app_server: dict[str, Any]) -> None:
    linkedin = "https://www.linkedin.com/jobs/view/7"
    ad = f'<html><body><h1>Backend Engineer</h1><a href="{JOB_URL}" target="_blank">Apply</a></body></html>'
    with app_server["db"].begin() as s:
        job = s.query(Job).one()
        job.url, job.data = linkedin, {**job.data, "apply_url": linkedin}

    async def go() -> dict[str, Any]:
        async with async_playwright() as pw:
            ctx = await pw.chromium.launch_persistent_context(
                str(app_server["data"] / "chromium"),
                executable_path=str(CHROMIUM),
                headless=False,
                args=[
                    "--headless=new",
                    f"--disable-extensions-except={app_server['ext']}",
                    f"--load-extension={app_server['ext']}",
                ],
            )

            async def site(route: Route) -> None:
                body = ad if route.request.url.startswith(linkedin) else FORM
                await route.fulfill(body=body, content_type="text/html")

            await ctx.route("https://www.linkedin.com/**", site)
            await ctx.route("https://jobs.example-board.test/**", site)
            worker = (
                ctx.service_workers[0]
                if ctx.service_workers
                else await ctx.wait_for_event("serviceworker")
            )
            await worker.evaluate(
                "(token) => chrome.storage.local.set({token})",
                app_server["token"],
            )
            page = await ctx.new_page()
            await page.goto(linkedin)
            await page.wait_for_function(
                "!!document.querySelector('[data-lk-agent]')", timeout=30000
            )
            async with ctx.expect_page() as new:
                await page.click("text=Apply")
            form = await new.value
            await form.wait_for_load_state()
            follow: dict[str, Any] = {}
            for _ in range(60):  # the employer tab's content script asks the worker on load
                follow = await worker.evaluate(
                    "chrome.storage.session.get('follow').then(r => r.follow || {})"
                )
                if len(follow) == 2:
                    break
                await asyncio.sleep(0.25)
            got = {"tabs": len(follow), "name": await form.input_value("#full_name")}
            await ctx.close()
            return got

    # the employer's tab carries the job (2 tabs followed); it waits for "Fill this step"
    assert asyncio.run(go()) == {"tabs": 2, "name": ""}


async def _browser(pw: Any, app: dict[str, Any], pages: dict[str, str]) -> tuple[Any, Any]:
    """Chromium with the extension paired, serving `pages` for the (fake) sites."""
    ctx = await pw.chromium.launch_persistent_context(
        str(app["data"] / "chromium"), executable_path=str(CHROMIUM), headless=False,
        args=["--headless=new", f"--disable-extensions-except={app['ext']}", f"--load-extension={app['ext']}"],
    )  # fmt: skip

    async def site(route: Route) -> None:
        url = route.request.url
        await route.fulfill(body=pages[url.split("?")[0]], content_type="text/html")

    for url in pages:
        await ctx.route(url.split("//")[0] + "//" + url.split("/")[2] + "/**", site)
    worker = (
        ctx.service_workers[0] if ctx.service_workers else await ctx.wait_for_event("serviceworker")
    )
    await worker.evaluate("(token) => chrome.storage.local.set({token})", app["token"])
    return ctx, worker


RIGHT_CLICK = """async () => {
  const tab = (await chrome.tabs.query({})).sort((x, y) => x.id - y.id).pop();
  chrome.contextMenus.onClicked.dispatch({menuItemId: 'linkit-fill'}, tab);
}"""
TAB_JOB = """() => chrome.storage.session.get('follow')
  .then(r => Object.values(r.follow || {}).map(f => f.job.title))"""


async def _until(check: Any, tries: int = 80) -> Any:
    got = None
    for _ in range(tries):
        if got := await check():
            return got
        await asyncio.sleep(0.25)
    return got


def test_each_page_knows_its_own_job_even_without_a_page_load(app_server: dict[str, Any]) -> None:
    """Glassdoor's jobs share one path and differ only in `jl`; LinkedIn's list changes job
    without loading a page."""
    board = "https://www.jobs-glass.test/job-listing/j"
    with app_server["db"].begin() as s:
        for jl, title in ((111, "Data Engineer"), (222, "QA Engineer")):
            job = Job(source="glassdoor", url=f"{board}?jl={jl}", title=title, company="Globex",
                      location="", description="", dedupe_hash=str(jl), state=JobState.needs_user,
                      data={"apply_url": f"{board}?jl={jl}"})  # fmt: skip
            s.add(job)
            s.flush()
            s.add(ActionItem(job_id=job.id, kind=ActionKind.apply_in_browser, code="x"))

    async def go() -> list[list[str]]:
        async with async_playwright() as pw:
            ctx, worker = await _browser(pw, app_server, {board: FORM})
            page = await ctx.new_page()
            await page.goto(f"{board}?jl=222")

            async def titles(want: str) -> list[str] | None:
                now: list[str] = await worker.evaluate(TAB_JOB)
                return now if now == [want] else None

            first = await _until(lambda: titles("QA Engineer"))
            await page.evaluate("history.pushState({}, '', '?jl=111')")
            second = await _until(lambda: titles("Data Engineer"))
            await ctx.close()
            return [first, second]

    assert asyncio.run(go()) == [["QA Engineer"], ["Data Engineer"]]


SHADOW_AND_FRAME = """<!doctype html><body>
<header><label for=where>City</label><input id=where></header>
<div id=host></div><iframe src="https://careers.other.test/frame" style="width:400px;height:200px"></iframe>
<script>
  document.getElementById('host').attachShadow({mode: 'open'}).innerHTML =
    '<label for=n>First name</label><input id=n required><label for=t>T-shirt size</label><input id=t>';
</script></body>"""
FRAME = "<!doctype html><body><label for=e>Email</label><input id=e type=email required></body>"
DIALOG = """<!doctype html><body><label for=out>First name</label><input id=out>
<div role=dialog aria-modal=true style="width:300px"><label for=m>Email</label><input id=m type=email></div></body>"""


def test_right_click_fills_shadow_dom_and_iframes_on_any_site(app_server: dict[str, Any]) -> None:
    url = "https://careers.other.test/apply"

    async def go() -> dict[str, str]:
        async with async_playwright() as pw:
            pages = {url: SHADOW_AND_FRAME, "https://careers.other.test/frame": FRAME}
            ctx, worker = await _browser(pw, app_server, pages)
            await worker.evaluate("chrome.contextMenus.update('linkit-fill', {})")  # it exists
            page = await ctx.new_page()
            await page.goto(url)
            await asyncio.sleep(1)
            shadow = "document.getElementById('host').shadowRoot.getElementById"
            assert await page.evaluate(f"{shadow}('n').value") == ""  # no job here: not on load
            await worker.evaluate(RIGHT_CLICK)

            async def name() -> str:
                return str(await page.evaluate(f"{shadow}('t').value"))

            await _until(name)
            frame = page.frames[1]
            await _until(lambda: frame.input_value("#e"))
            got = {
                "name": await page.evaluate(f"{shadow}('n').value"),
                "shirt": await name(),
                "frame": await frame.input_value("#e"),
                "site_search": await page.input_value("#where"),
            }
            await ctx.close()
            return got

    assert asyncio.run(go()) == {
        "name": "Jane",
        "shirt": "Because I build backend systems.",  # right-click: optional fields too
        "frame": "jane@example.com",
        "site_search": "",  # the site's own search bar
    }


def test_right_click_fills_a_frame_written_inline(app_server: dict[str, Any]) -> None:
    url = "https://careers.other.test/inline"
    html = (
        '<!doctype html><body><iframe srcdoc="<label for=e>Email</label>'
        '<input id=e type=email required>"></iframe></body>'
    )

    async def go() -> str:
        async with async_playwright() as pw:
            ctx, worker = await _browser(pw, app_server, {url: html})
            page = await ctx.new_page()
            await page.goto(url)
            await asyncio.sleep(1)
            await worker.evaluate(RIGHT_CLICK)
            frame = page.frames[1]
            await _until(lambda: frame.input_value("#e"))
            got = await frame.input_value("#e")
            await ctx.close()
            return got

    assert asyncio.run(go()) == "jane@example.com"


def test_an_open_dialog_is_the_form(app_server: dict[str, Any]) -> None:
    url = "https://careers.other.test/modal"

    async def go() -> tuple[str, str]:
        async with async_playwright() as pw:
            ctx, worker = await _browser(pw, app_server, {url: DIALOG})
            page = await ctx.new_page()
            await page.goto(url)
            await asyncio.sleep(1)
            await worker.evaluate(RIGHT_CLICK)
            await _until(lambda: page.input_value("#m"))
            got = await page.input_value("#m"), await page.input_value("#out")
            await ctx.close()
            return got

    assert asyncio.run(go()) == ("jane@example.com", "")
