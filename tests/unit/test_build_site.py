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
