"""One-off: build `src/linkit_all/data/company_boards.json` from a career-ops checkout.

    uv run python scripts/build_company_boards.py <path to the career-ops repo>

Reads `templates/portals.example.yml` (`tracked_companies`, MIT) and
`employers/boards/**/*.ndjson` (CC BY 4.0; rows with `retired: true` are skipped). Each
careers / API address goes through our own ATS detector, so only boards one of our plugins can
crawl are kept. Output: a list of `{ats, slug, name}`, one per board (slug compared without
case), sorted by name. Nothing is fetched.
"""

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from linkit_all.sources.ats_detector import detect

OUT = Path(__file__).resolve().parents[1] / "src/linkit_all/data/company_boards.json"


def entries(repo: Path) -> Iterator[tuple[str, list[str]]]:
    """(company name, its addresses) from both career-ops lists."""
    portals = yaml.safe_load((repo / "templates/portals.example.yml").read_text("utf-8"))
    for c in portals.get("tracked_companies") or []:
        if isinstance(c, dict):
            yield str(c.get("name") or ""), [str(c.get(k) or "") for k in ("careers_url", "api")]
    for path in sorted((repo / "employers/boards").rglob("*.ndjson")):
        for line in path.read_text("utf-8").splitlines():
            if not line.strip():
                continue
            row: dict[str, Any] = json.loads(line)
            if row.get("retired") is not True:
                yield str(row.get("name") or ""), [str(row.get("careers_url") or "")]


def build(repo: Path) -> list[dict[str, str]]:
    boards: dict[tuple[str, str], dict[str, str]] = {}
    for name, urls in entries(repo):
        found = next((f for u in urls if u and (f := detect(u))), None)
        # the shorthand must read back as the same board: it is what `sources.companies` stores
        if not name.strip() or found is None or detect(f"{found[0]}:{found[1]}") != found:
            continue
        ats, slug = found
        boards.setdefault((ats, slug.lower()), {"ats": ats, "slug": slug, "name": name.strip()})
    return sorted(boards.values(), key=lambda b: (b["name"].lower(), b["ats"], b["slug"]))


if __name__ == "__main__":
    rows = build(Path(sys.argv[1]))
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=0) + "\n", "utf-8")
    print(f"{len(rows)} boards -> {OUT}")
