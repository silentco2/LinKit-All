"""API keys for job-aggregator APIs, kept in the vault (CLAUDE.md §2, §6).

One vault entry per provider: kind "api_key", site = provider name, username "default". The secret
is a JSON object with every field (secret or not); only `saved_at` goes in plaintext meta.
Sources call `get_keys`; it returns None when the vault is locked or nothing is saved.
"""

import json
from dataclasses import dataclass

from linkit_all.apply.vault import Vault
from linkit_all.core.models import utcnow

KIND = "api_key"
USERNAME = "default"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    secret: bool = True


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    label: str
    fields: tuple[FieldSpec, ...]
    signup_url: str
    note: str


KNOWN: dict[str, ProviderSpec] = {
    p.name: p
    for p in (
        ProviderSpec(
            "adzuna",
            "Adzuna",
            (FieldSpec("app_id", "App ID", secret=False), FieldSpec("app_key", "App key")),
            "https://developer.adzuna.com/signup",
            "Free. Covers about 20 countries.",
        ),
        ProviderSpec(
            "reed",
            "Reed",
            (FieldSpec("api_key", "API key"),),
            "https://www.reed.co.uk/developers/jobseeker",
            "Free. UK jobs.",
        ),
        ProviderSpec(
            "usajobs",
            "USAJobs",
            (FieldSpec("api_key", "API key"), FieldSpec("email", "Account email", secret=False)),
            "https://developer.usajobs.gov/apirequest/",
            "Free. US federal jobs. The email you registered with is sent as the User-Agent.",
        ),
        ProviderSpec(
            "whatjobs",
            "WhatJobs",
            (FieldSpec("publisher_ids", "Publisher IDs", secret=False),),
            "https://www.whatjobs.com/affiliates",
            "Free. One publisher ID per country: country=id, comma-separated (gb=123, us=456).",
        ),
    )
}


def get_keys(vault: Vault, name: str) -> dict[str, str] | None:
    """The saved field values, or None if the vault is locked or the provider is not saved."""
    if not vault.unlocked():
        return None
    entries = vault.find(KIND, name)
    if not entries:
        return None
    data = json.loads(vault.get(entries[0].id))
    return {k: str(v) for k, v in data.items()}


def set_keys(vault: Vault, name: str, values: dict[str, str]) -> None:
    """Save exactly the provider's fields. ValueError on an unknown provider, field or blank value.

    Raises VaultLocked when the vault is locked. Error text never contains a value.
    """
    spec = KNOWN.get(name)
    if spec is None:
        raise ValueError(f"unknown provider: {name}")
    wanted = {f.name for f in spec.fields}
    if set(values) - wanted:
        raise ValueError("unknown field")
    clean = {k: v.strip() for k, v in values.items()}
    missing = [f.label for f in spec.fields if not clean.get(f.name)]
    if missing:
        raise ValueError("required: " + ", ".join(missing))
    vault.put(KIND, name, USERNAME, json.dumps(clean), {"saved_at": utcnow().isoformat()})


def delete_keys(vault: Vault, name: str) -> None:
    for e in vault.find(KIND, name):
        vault.delete(e.id)
