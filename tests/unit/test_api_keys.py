"""API keys in the vault: get_keys/set_keys/delete_keys and the /api/keys routes."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_api import SAME_ORIGIN, client, mem_keyring  # noqa: F401
from test_vault import PASS, db, vault  # noqa: F401

from linkit_all.apply.vault import Vault, VaultLocked
from linkit_all.core.api_keys import KIND, KNOWN, delete_keys, get_keys, set_keys

APP_KEY = "adzuna-app-key-SECRET-1234abcd"


def test_set_get_delete_roundtrip(vault: Vault) -> None:  # noqa: F811
    assert get_keys(vault, "adzuna") is None
    set_keys(vault, "adzuna", {"app_id": " 42 ", "app_key": APP_KEY})
    assert get_keys(vault, "adzuna") == {"app_id": "42", "app_key": APP_KEY}
    set_keys(vault, "adzuna", {"app_id": "43", "app_key": "other"})  # replaces, no duplicate
    assert get_keys(vault, "adzuna") == {"app_id": "43", "app_key": "other"}
    (entry,) = vault.entries()
    assert (entry.kind, entry.site, entry.username) == (KIND, "adzuna", "default")
    assert set(entry.meta) == {"saved_at"}
    delete_keys(vault, "adzuna")
    assert get_keys(vault, "adzuna") is None and vault.entries() == []


def test_set_keys_validates_and_locked_vault(vault: Vault) -> None:  # noqa: F811
    for name, values in (
        ("nope", {"api_key": APP_KEY}),
        ("reed", {}),
        ("reed", {"api_key": "  "}),
        ("reed", {"api_key": APP_KEY, "extra": "x"}),
        ("adzuna", {"app_id": "1"}),
    ):
        with pytest.raises(ValueError) as e:
            set_keys(vault, name, values)
        assert APP_KEY not in str(e.value)
    assert vault.entries() == []
    vault.lock()
    assert get_keys(vault, "reed") is None
    with pytest.raises(VaultLocked):
        set_keys(vault, "reed", {"api_key": APP_KEY})


def test_known_providers() -> None:
    assert {n: [f.name for f in s.fields] for n, s in KNOWN.items()} == {
        "adzuna": ["app_id", "app_key"],
        "reed": ["api_key"],
        "usajobs": ["api_key", "email"],
        "whatjobs": ["publisher_ids"],
    }


def test_keys_api(client: TestClient) -> None:  # noqa: F811
    vlt: Vault = client.app.state.vault  # type: ignore[attr-defined]

    def put(name: str, body: dict[str, str]) -> Any:
        return client.put(f"/api/keys/{name}", json=body, headers=SAME_ORIGIN)

    listed = client.get("/api/keys").json()
    assert [p["name"] for p in listed] == list(KNOWN)
    assert all(not p["configured"] and p["current"] == {} for p in listed)
    assert listed[0]["fields"] == [
        {"name": "app_id", "label": "App ID", "secret": False},
        {"name": "app_key", "label": "App key", "secret": True},
    ]

    assert put("reed", {"api_key": APP_KEY}).status_code == 423  # locked
    assert client.delete("/api/keys/reed", headers=SAME_ORIGIN).status_code == 423
    client.post("/api/vault/create", json={"passphrase": PASS}, headers=SAME_ORIGIN)
    client.post(
        "/api/vault/unlock", json={"passphrase": PASS, "remember": False}, headers=SAME_ORIGIN
    )

    assert put("nope", {"api_key": "x"}).status_code == 422
    assert client.delete("/api/keys/nope", headers=SAME_ORIGIN).status_code == 422
    bad = put("adzuna", {"app_id": "1"})  # app_key missing
    assert bad.status_code == 422 and "App key" in bad.json()["detail"]
    assert put("reed", {"api_key": APP_KEY, "extra": "x"}).status_code == 422
    assert vlt.entries() == []

    ok = put("adzuna", {"app_id": "42", "app_key": APP_KEY})
    assert ok.status_code == 200
    assert APP_KEY not in ok.text and APP_KEY not in client.get("/api/keys").text
    adzuna = next(p for p in client.get("/api/keys").json() if p["name"] == "adzuna")
    assert adzuna["configured"] is True
    assert adzuna["current"] == {"app_id": "42", "app_key": "\u2022\u2022\u2022\u2022abcd"}
    assert get_keys(vlt, "adzuna") == {"app_id": "42", "app_key": APP_KEY}

    # a blank field keeps its saved value; short secrets are fully hidden
    assert put("adzuna", {"app_id": "43", "app_key": ""}).status_code == 200
    assert get_keys(vlt, "adzuna") == {"app_id": "43", "app_key": APP_KEY}
    put("reed", {"api_key": "short"})
    reed = next(p for p in client.get("/api/keys").json() if p["name"] == "reed")
    assert reed["current"] == {"api_key": "\u2022\u2022\u2022\u2022"}

    client.post("/api/vault/lock", json={}, headers=SAME_ORIGIN)
    assert all(not p["configured"] for p in client.get("/api/keys").json())  # unknown while locked
    client.post(
        "/api/vault/unlock", json={"passphrase": PASS, "remember": False}, headers=SAME_ORIGIN
    )
    assert client.delete("/api/keys/adzuna", headers=SAME_ORIGIN).status_code == 204
    assert get_keys(vlt, "adzuna") is None and get_keys(vlt, "reed") is not None
