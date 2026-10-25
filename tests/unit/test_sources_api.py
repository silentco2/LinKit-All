"""GET /api/sources: the opt-in sources Setup lists, their enabled flags and key badges."""

from fastapi.testclient import TestClient
from test_api import SAME_ORIGIN, client, mem_keyring  # noqa: F401
from test_vault import PASS

from linkit_all.apply.vault import Vault
from linkit_all.core.api_keys import set_keys

OPT_IN = {"aggregator", "board", "company", "telegram"}


def listed(client: TestClient) -> dict[str, dict]:  # type: ignore[type-arg]  # noqa: F811
    body = client.get("/api/sources").json()
    return {s["name"]: s for s in body["sources"]}


def test_lists_opt_in_sources_and_counts_ats(client: TestClient) -> None:  # noqa: F811
    body = client.get("/api/sources").json()
    assert body["ats_count"] > 50  # shown as one sentence, never as rows
    names = listed(client)
    assert {s["kind"] for s in names.values()} <= OPT_IN
    assert {"aggregator", "board", "company"} <= {s["kind"] for s in names.values()}
    assert not {"careers", "greenhouse", "wuzzuf", "linkedin"} & set(names)
    adzuna = names["adzuna"]
    assert adzuna["label"] == "Adzuna" and adzuna["description"].startswith("Adzuna job search API")
    assert adzuna["region"] == "" and adzuna["enabled"] is False
    assert all(s["label"] and s["description"] for s in names.values())


def test_enabled_flags_follow_the_saved_config(client: TestClient) -> None:  # noqa: F811
    assert not any(s["enabled"] for s in listed(client).values() if s["name"] != "telegram")
    cfg = client.get("/api/search").json()
    cfg["sources"]["enabled"] = ["adzuna", "no_such_source"]
    assert client.put("/api/search", json=cfg, headers=SAME_ORIGIN).status_code == 200
    names = listed(client)
    assert names["adzuna"]["enabled"] is True and names["reed"]["enabled"] is False


def test_key_badges_follow_the_vault(client: TestClient) -> None:  # noqa: F811
    names = listed(client)
    for n in ("adzuna", "reed", "usajobs", "whatjobs"):
        assert names[n]["needs_key"] == n and names[n]["key_configured"] is False
    free = next(s for s in names.values() if s["kind"] == "board")
    assert free["needs_key"] is None and free["key_configured"] is False

    vlt: Vault = client.app.state.vault  # type: ignore[attr-defined]
    client.post("/api/vault/create", json={"passphrase": PASS}, headers=SAME_ORIGIN)
    client.post(
        "/api/vault/unlock", json={"passphrase": PASS, "remember": False}, headers=SAME_ORIGIN
    )
    set_keys(vlt, "reed", {"api_key": "reed-key-1234abcd"})
    names = listed(client)
    assert names["reed"]["key_configured"] is True and names["adzuna"]["key_configured"] is False
    assert "reed-key-1234abcd" not in client.get("/api/sources").text

    client.post("/api/vault/lock", json={}, headers=SAME_ORIGIN)
    assert listed(client)["reed"]["key_configured"] is False  # unknown while locked
