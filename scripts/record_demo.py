"""Record the README demo GIF from the made-up study data (scripts/seed_usability.py).

    uv run python scripts/record_demo.py [--out docs/assets/demo.gif]

Seeds a temporary data folder, starts the app on a free port, walks Home -> Jobs -> a job ->
Needs you in a headless browser (light theme), and writes an animated GIF. No real data is
touched and nothing is submitted. Build the web page first (`npx ng build` in frontend/).
"""

import argparse
import contextlib
import io
import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
from PIL import Image
from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
import seed_usability

from linkit_all.core.tools import browser_path

VIEW = {"width": 1280, "height": 800}
SCALE = 0.75  # 960 x 600 in the GIF: readable, and the file stays small


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextlib.contextmanager
def app(data: Path) -> Iterator[str]:
    port = free_port()
    env = {**os.environ, "LINKIT_DATA_DIR": str(data)}
    cmd = [sys.executable, "-c", "from linkit_all.cli import app; app()",
           "serve", "--port", str(port), "--no-open"]  # fmt: skip
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            with contextlib.suppress(httpx.HTTPError):
                if httpx.get(url, timeout=1).status_code == 200:
                    break
            time.sleep(0.5)
        else:
            raise RuntimeError("the app did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(10)


class Film:
    def __init__(self, page: Page) -> None:
        self.page, self.frames = page, []  # type: list[tuple[Image.Image, int]]

    def go(self, url: str) -> None:
        self.page.goto(url)
        self.page.wait_for_load_state("networkidle")
        # the app moves focus to the page heading for screen readers; no outline in the film
        self.page.evaluate("document.activeElement?.blur?.()")

    def shot(self, ms: int) -> None:
        img = Image.open(io.BytesIO(self.page.screenshot())).convert("RGB")
        size = (round(img.width * SCALE), round(img.height * SCALE))
        self.frames.append((img.resize(size, Image.Resampling.LANCZOS), ms))

    def scroll(self, dy: int, steps: int = 8) -> None:
        for _ in range(steps):
            self.page.mouse.wheel(0, dy / steps)
            self.page.wait_for_timeout(60)
            self.shot(80)

    def type(self, text: str) -> None:
        for ch in text:
            self.page.keyboard.type(ch)
            self.shot(90)

    def save(self, out: Path) -> None:
        imgs = [f.quantize(colors=128, method=Image.Quantize.MEDIANCUT) for f, _ in self.frames]
        imgs[0].save(out, save_all=True, append_images=imgs[1:], loop=0, optimize=True,
                     duration=[ms for _, ms in self.frames], disposal=1)  # fmt: skip


def record(url: str, out: Path) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=browser_path(), headless=True)
        page = browser.new_page(viewport=VIEW, color_scheme="light", locale="en-US")
        film = Film(page)

        film.go(f"{url}/home")
        film.shot(3000)
        film.scroll(560)
        film.shot(2500)

        film.go(f"{url}/jobs")
        film.shot(2500)
        page.get_by_text("Software Engineer", exact=True).first.click()
        page.get_by_text("Filled answers").wait_for()
        page.wait_for_timeout(400)
        film.shot(4000)

        film.go(f"{url}/needs-you")
        film.shot(2500)
        box = page.get_by_label("What is your notice period?").first
        box.click()
        film.type("One month")
        film.shot(2500)
        browser.close()
    film.save(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("docs/assets/demo.gif"))
    args = ap.parse_args()
    if browser_path() is None:
        print("No Chrome, Edge, Brave or Chromium found.", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data = Path(tmp) / "data"
        if seed_usability.main(["--data-dir", str(data)]):
            return 1
        with app(data) as url:
            record(url, args.out)
    print(f"Wrote {args.out} ({args.out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
