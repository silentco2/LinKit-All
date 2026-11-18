"""Render scripts/social_card.html to docs/assets/social.png (1280x640)."""

from pathlib import Path

from playwright.sync_api import sync_playwright

from linkit_all.core.tools import browser_path

HERE = Path(__file__).parent
OUT = HERE.parent / "docs" / "assets" / "social.png"

FONTS = HERE.parent / "frontend" / "node_modules"
if not all(
    (FONTS / f).is_file()
    for f in (
        "@fontsource-variable/ibm-plex-sans/files/ibm-plex-sans-latin-wght-normal.woff2",
        "@fontsource/ibm-plex-sans-arabic/files/ibm-plex-sans-arabic-arabic-600-normal.woff2",
    )
):
    raise SystemExit("Fonts come from frontend/node_modules: run npm ci in frontend first.")

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=browser_path(), headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 640})
    page.goto((HERE / "social_card.html").as_uri())
    page.evaluate("document.fonts.ready")
    page.screenshot(path=OUT)
    browser.close()
print(OUT, OUT.stat().st_size, "bytes")
