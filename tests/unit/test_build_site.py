"""scripts/build_site.py: landing at /, docs at /docs/, stubs at old URLs."""

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
        "<urlset><url><loc>https://silentco2.github.io/LinKit-All/docs/install/</loc></url></urlset>"
    )
    (landing / "samples").mkdir(parents=True)
    (landing / "samples" / "cv.docx").write_text("secret")
    (landing / "index.html").write_text("LANDING")

    build_site.build(docs, landing, out)

    assert (out / "index.html").read_text() == "LANDING"  # landing owns /
    assert (out / "docs" / "install" / "index.html").read_text() == "install"
    stub = (out / "install" / "index.html").read_text()
    assert (
        'http-equiv="refresh"' in stub and "LinKit-All/docs/install/" in stub and "noindex" in stub
    )
    assert (
        out / "search.example.toml"
    ).read_text() == "x = 1"  # data files are copied, not stubbed
    assert not (out / "samples").exists()
    assert (out / "404.html").read_text() == "nope" and (out / "docs" / "404.html").is_file()
    sitemap = (out / "sitemap.xml").read_text()
    assert (
        "<loc>https://silentco2.github.io/LinKit-All/</loc>" in sitemap
        and "/docs/install/" in sitemap
    )
