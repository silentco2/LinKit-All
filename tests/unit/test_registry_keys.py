"""The `keys` constructor value that registry() hands to plugins, and how the pipeline builds it."""

from pathlib import Path

from sqlalchemy.orm import sessionmaker
from test_vault import db, mem_keyring, vault  # noqa: F401

from linkit_all.apply.vault import Vault
from linkit_all.core.api_keys import set_keys
from linkit_all.core.config import Settings
from linkit_all.pipeline import api_key_getter
from linkit_all.sources import registry


def test_registry_passes_keys_to_plugins_that_ask() -> None:
    found = registry()
    assert {"adzuna", "reed", "usajobs", "whatjobs"} <= set(found)
    assert all(found[n].kind == "aggregator" for n in ("adzuna", "reed", "usajobs", "whatjobs"))
    assert found["reed"]._keys("reed") is None  # type: ignore[attr-defined]  # default: no keys

    def keys(name: str) -> dict[str, str] | None:
        return {"api_key": f"key-for-{name}"}

    found = registry(None, None, keys)
    assert found["reed"]._keys("reed") == {"api_key": "key-for-reed"}  # type: ignore[attr-defined]
    assert found["careers"].provider is None  # type: ignore[attr-defined]  # others unaffected


def test_api_key_getter_reads_the_servers_vault(
    vault: Vault,  # noqa: F811
    db: sessionmaker,  # type: ignore[type-arg]  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path)
    keys = api_key_getter(db, settings, vault)
    set_keys(vault, "reed", {"api_key": "abc"})
    assert keys("reed") == {"api_key": "abc"} and keys("adzuna") is None
    vault.lock()
    assert keys("reed") is None  # locked and no keyring entry for this vault: nothing, no error
