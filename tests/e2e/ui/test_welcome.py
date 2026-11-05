"""First-run flow (/welcome) and a render smoke test, through the real UI. Dry-run: nothing is
submitted anywhere. Build the frontend first (see conftest.py)."""

import sys
from pathlib import Path

import httpx
import pytest
from conftest import UI

sys.path.insert(0, str(Path(__file__).parents[2] / "unit"))
from test_cv_formats import make_pdf
from test_tailor import make_cv

pytestmark = pytest.mark.ui

ORIGIN = lambda base: {"origin": base}  # noqa: E731  (same-origin header the API requires)


def api(ui: UI, method: str, path: str, **kw: object) -> httpx.Response:
    r = httpx.request(method, f"{ui.base_url}/api{path}", headers=ORIGIN(ui.base_url), **kw)  # type: ignore[arg-type]
    assert r.status_code == 200, r.text
    return r


def test_welcome_pdf_approve(ui: UI, tmp_path: Path) -> None:
    page = ui.page
    page.goto("/")
    page.wait_for_url("**/welcome")
    make_pdf(tmp_path / "cv.pdf")
    page.locator("input[type=file]").set_input_files(tmp_path / "cv.pdf")
    page.get_by_role("alert").filter(has_text="Check the converted CV").wait_for()
    next_btn = page.get_by_role("button", name="Next")
    assert next_btn.is_disabled()
    page.get_by_role("button", name="Approve this as my CV").click()
    page.get_by_text("Your CV is ready.").wait_for()
    assert next_btn.is_enabled()
    assert api(ui, "GET", "/status").json()["cv_ready"] is True
    assert not ui.console_errors


def test_welcome_local_model_pick(ui: UI, tmp_path: Path, fake_local_ai: None) -> None:
    api(ui, "POST", "/profile/cv", params={"filename": "cv.docx"},
        content=make_cv(tmp_path / "cv.docx").read_bytes())  # fmt: skip
    page = ui.page
    page.goto("/welcome")
    page.get_by_role("heading", name="Connect your AI").wait_for()  # CV done: lands on step 2
    page.get_by_label("Local model (free, private)").check()
    page.get_by_role("button", name="llama3.1:8b").wait_for()
    assert page.get_by_role("button", name="gemma-3").is_visible()
    page.get_by_role("button", name="llama3.1:8b").click()
    page.get_by_text("Connected and saved.").wait_for()
    assert page.get_by_role("button", name="Next").is_enabled()
    ai = api(ui, "GET", "/search").json()["ai"]
    assert ai["provider"] == "litellm"
    assert ai["model"] == "ollama/llama3.1:8b"
    assert ai["api_base"] == "http://127.0.0.1:11434"
    assert not ui.console_errors


@pytest.mark.parametrize("path", ["/home", "/jobs", "/needs-you", "/activity", "/settings/profile"])
def test_pages_render_without_console_errors(ui: UI, path: str) -> None:
    ui.page.goto(path)
    ui.page.locator("h1").first.wait_for()
    assert ui.page.locator("h1").first.inner_text().strip()
    ui.page.wait_for_load_state("networkidle")
    assert not ui.console_errors
