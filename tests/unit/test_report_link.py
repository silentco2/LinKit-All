"""GitHub issues instead of analytics: /api/status carries only non-personal facts for a report."""

from fastapi.testclient import TestClient
from test_api import client  # noqa: F401


def test_status_about_is_non_personal(client: TestClient) -> None:  # noqa: F811
    about = client.get("/api/status").json()["about"]
    assert set(about) == {"version", "os", "python", "ai"}
    assert about["python"].count(".") == 2 and about["ai"] in {"codex_cli", "claude_cli", "litellm"}
