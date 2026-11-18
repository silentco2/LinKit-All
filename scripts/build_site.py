"""Build the GitHub Pages site: landing at /, MkDocs docs at /docs/, stubs at old docs URLs.

Usage: uv run --no-sync python scripts/build_site.py --docs site --landing landing --out _site
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
from pathlib import Path

BASE = "https://silentco2.github.io/LinKit-All/"
STUB = (
    '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
    "<title>Moved to {url}</title>"
    '<meta http-equiv="refresh" content="0; url={url}">'
    '<link rel="canonical" href="{url}">'
    '<meta name="robots" content="noindex">'
    '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
    '<body><p>This page moved to <a href="{url}">{url}</a>.</p></body></html>\n'
)


def _page_path(rel: Path) -> str:
    """Site-relative URL path of a built HTML page: install/index.html -> install/."""
    if rel.name == "index.html":
        return "" if rel.parent == Path(".") else rel.parent.as_posix() + "/"
    return rel.as_posix()


def build(docs: Path, landing: Path, out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(docs, out / "docs")
    if (landing / "index.html").is_file():
        shutil.copytree(landing, out, dirs_exist_ok=True, ignore=shutil.ignore_patterns("samples"))
    else:
        print(f"warning: {landing}/index.html is missing; building docs and redirects only")

    # old docs URLs: HTML pages get a stub, other files are copied; never overwrite a landing file
    for src in sorted(docs.rglob("*")):
        rel = src.relative_to(docs)
        dest = out / rel
        if not src.is_file() or dest.exists() or rel.name == "404.html":
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".html":
            url = BASE + "docs/" + _page_path(rel)
            dest.write_text(STUB.format(url=html.escape(url)), encoding="utf-8")
        elif src.name != "sitemap.xml.gz":
            shutil.copy2(src, dest)

    if (docs / "404.html").is_file() and not (out / "404.html").exists():
        shutil.copy2(docs / "404.html", out / "404.html")  # GitHub Pages serves the root 404

    urls = [BASE]
    sitemap = docs / "sitemap.xml"
    if sitemap.is_file():
        urls += re.findall(r"<loc>([^<]+)</loc>", sitemap.read_text(encoding="utf-8"))
    body = "".join(f"  <url><loc>{html.escape(u)}</loc></url>\n" for u in dict.fromkeys(urls))
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}</urlset>\n',
        encoding="utf-8",
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--docs", type=Path, default=Path("site"))
    p.add_argument("--landing", type=Path, default=Path("landing"))
    p.add_argument("--out", type=Path, default=Path("_site"))
    a = p.parse_args()
    build(a.docs, a.landing, a.out)
    print(f"built {a.out}")


if __name__ == "__main__":
    main()
