"""scripts/build_site.py: landing at /, docs at /docs/, stubs at old URLs, the old address."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "build_site", Path(__file__).parents[2] / "scripts" / "build_site.py"
)
assert _spec and _spec.loader
build_site = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_site)


def test_build(tmp_path: Path) -> None:
    docs, landing, out = tmp_path / "site", tmp_path / "landing", tmp_path / "_site"
    (docs / "install").mkdir(parents=True)
    (docs / "index.html").write_text("docs home")
    (docs / "install" / "index.html").write_text("install")
    (docs / "search.example.toml").write_text("x = 1")
    (docs / "llms.txt").write_text("llms")
    (docs / "404.html").write_text("nope")
    (docs / "sitemap.xml").write_text(
        "<urlset><url><loc>https://linkit-all.github.io/docs/install/</loc></url></urlset>"
    )
    (landing / "samples").mkdir(parents=True)
    (landing / "samples" / "cv.docx").write_text("secret")
    (landing / "index.html").write_text("LANDING")

    build_site.build(docs, landing, out)

    assert (out / "index.html").read_text() == "LANDING"  # landing owns /
    assert (out / "docs" / "install" / "index.html").read_text() == "install"
    stub = (out / "install" / "index.html").read_text()
    assert (
        'http-equiv="refresh"' in stub
        and "https://linkit-all.github.io/docs/install/" in stub
        and "noindex" in stub
    )
    assert (
        out / "search.example.toml"
    ).read_text() == "x = 1"  # data files are copied, not stubbed
    assert not (out / "samples").exists()
    assert (out / "404.html").read_text() == "nope" and (out / "docs" / "404.html").is_file()
    sitemap = (out / "sitemap.xml").read_text()
    assert (
        "<loc>https://linkit-all.github.io/</loc>" in sitemap
        and "<loc>https://linkit-all.github.io/docs/install/</loc>" in sitemap
    )
    robots = (out / "robots.txt").read_text()
    assert "Allow: /" in robots and "Sitemap: https://linkit-all.github.io/sitemap.xml" in robots

    old = tmp_path / "_old"
    build_site.build_moved(out, old)
    moved = (old / "docs" / "install" / "index.html").read_text()
    # a move, not a removal: instant refresh + canonical to the same page, and no noindex
    assert (
        '<meta http-equiv="refresh" content="0; url=https://linkit-all.github.io/docs/install/">'
        in moved
    )
    assert '<link rel="canonical" href="https://linkit-all.github.io/docs/install/">' in moved
    assert "noindex" not in moved
    assert 'location.replace("https://linkit-all.github.io/docs/install/"' in moved
    home = (old / "index.html").read_text()
    assert 'href="https://linkit-all.github.io/"' in home
    # an old stub moves straight to its final page, not through a second hop
    assert (
        'canonical" href="https://linkit-all.github.io/docs/install/"'
        in (old / "install" / "index.html").read_text()
    )
    assert (old / "search.example.toml").read_text() == "x = 1"  # files keep working
    assert "/LinKit-All" in (old / "404.html").read_text()  # unknown old links keep their path
    old_map = (old / "sitemap.xml").read_text()
    assert "<loc>https://silentco2.github.io/LinKit-All/docs/install/</loc>" in old_map
    assert "<loc>https://silentco2.github.io/LinKit-All/</loc>" in old_map
    assert not (old / "robots.txt").exists()


def test_phone_app_at_app(tmp_path: Path) -> None:
    import re

    docs, landing, app, out = (tmp_path / n for n in ("site", "landing", "phone", "_site"))
    docs.mkdir()
    (docs / "index.html").write_text("docs home")
    (docs / "sitemap.xml").write_text("<urlset></urlset>")
    landing.mkdir()
    (landing / "index.html").write_text("LANDING")
    (app / "tunnel").mkdir(parents=True)
    (app / "index.html").write_text('<base href="/app/">PHONE')
    (app / "tunnel" / "linkit_tunnel_bg.wasm").write_bytes(b"\0asm")

    build_site.build(docs, landing, out, app)

    assert (out / "app" / "index.html").read_text().endswith("PHONE")
    assert (out / "app" / "tunnel" / "linkit_tunnel_bg.wasm").is_file()
    for page in ("needs-you", "pair", "settings/phone"):  # reloads and the push tap open these
        assert (out / "app" / page / "index.html").read_text().endswith("PHONE")
    assert "Disallow: /app/" in (out / "robots.txt").read_text()
    assert "/app/" not in (out / "sitemap.xml").read_text()
    build_site.build_moved(out, tmp_path / "_old")
    assert not (tmp_path / "_old" / "app").exists()

    # every page the app can open has its copy: the routes file is the source of truth
    routes = (Path(__file__).parents[2] / "frontend" / "src" / "app" / "app.routes.ts").read_text()
    static = {p for p in re.findall(r"path: '([^']*)'", routes) if p and p != "**" and ":" not in p}
    assert static <= set(build_site.APP_PAGES)
