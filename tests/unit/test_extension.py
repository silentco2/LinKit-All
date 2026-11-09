"""LinkIt Fill extension: its files ship in the package and read pages like the app's agent."""

import json
from pathlib import Path

PKG = Path(__file__).parents[2] / "src" / "linkit_all"
EXT = PKG / "extension"


def test_extension_snapshot_is_the_agents_snapshot() -> None:
    agent = (PKG / "apply" / "agent" / "snapshot.js").read_text("utf-8").replace("\r\n", "\n")
    ext = (EXT / "snapshot.js").read_text("utf-8").replace("\r\n", "\n")
    assert "window.lkSnapshot = " + agent.strip() + ";" in ext, (
        "regenerate src/linkit_all/extension/snapshot.js from apply/agent/snapshot.js"
    )


def test_manifest_talks_only_to_this_computer() -> None:
    m = json.loads((EXT / "manifest.json").read_text("utf-8"))
    assert m["manifest_version"] == 3
    assert m["host_permissions"] == ["http://127.0.0.1/*", "http://localhost/*"]
    assert set(m["permissions"]) == {"storage", "contextMenus", "scripting", "activeTab"}
    for name in ("background.js", "content.js", "snapshot.js", "options.html", "options.js"):
        assert (EXT / name).is_file(), name


def test_content_script_never_presses_next_or_submit() -> None:
    js = (EXT / "content.js").read_text("utf-8")
    assert ".submit(" not in js and "requestSubmit" not in js
    assert "type=submit" not in js
