"""Site accounts for ATS sign-up/sign-in: password generation and the vault records behind them.

The vault entry is saved BEFORE the sign-up form is submitted, so a crash never loses the
password. Passwords are never logged (CLAUDE.md §2, §5.5).
"""

import secrets
import string
from dataclasses import dataclass

from linkit_all.apply.vault import Vault
from linkit_all.core.models import utcnow

KIND = "site_account"


@dataclass(frozen=True)
class PasswordRules:
    """What a site accepts. Handlers override the defaults to match the sign-up form."""

    min_len: int = 14
    max_len: int = 64
    need_upper: bool = True
    need_lower: bool = True
    need_digit: bool = True
    need_symbol: bool = True
    symbols: str = "!@#$%^&*-_+=?"  # empty = the site takes no symbols
    forbidden: str = ""  # characters the site rejects


@dataclass(frozen=True)
class Account:
    entry_id: int
    username: str
    password: str
    status: str = "active"  # pending_signup | active


def generate_password(rules: PasswordRules) -> str:
    """Random password with every required class present, shuffled, length within the rules."""
    bad = set(rules.forbidden)

    def pool(chars: str) -> str:
        return "".join(c for c in chars if c not in bad)

    classes = {
        "upper": (pool(string.ascii_uppercase), rules.need_upper),
        "lower": (pool(string.ascii_lowercase), rules.need_lower),
        "digit": (pool(string.digits), rules.need_digit),
        "symbol": (pool(rules.symbols), rules.need_symbol),
    }
    needed = [chars for chars, need in classes.values() if need]
    if any(not chars for chars in needed):
        raise ValueError("password rules leave a required character class empty")
    allowed = "".join(chars for chars, _ in classes.values())
    length = max(rules.min_len, min(20, rules.max_len), len(needed))
    if length > rules.max_len:
        raise ValueError("password rules are unsatisfiable")
    chars = [secrets.choice(c) for c in needed]
    chars += [secrets.choice(allowed) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _site(ats: str, tenant: str) -> str:
    return f"{ats}:{tenant}"


def find_account(vault: Vault, ats: str, tenant: str) -> Account | None:
    """The saved login for this ATS tenant, or None. Raises VaultLocked if locked."""
    entries = vault.find(KIND, _site(ats, tenant))
    if not entries:
        return None
    e = entries[0]
    return Account(e.id, e.username, vault.get(e.id), str(e.meta.get("status", "active")))


def create_account(
    vault: Vault, ats: str, tenant: str, username: str, rules: PasswordRules
) -> Account:
    """Generate a password and store it as pending_signup. Call before submitting sign-up."""
    password = generate_password(rules)
    meta = {"status": "pending_signup", "created_at": utcnow().isoformat()}
    entry_id = vault.put(KIND, _site(ats, tenant), username, password, meta)
    return Account(entry_id, username, password, "pending_signup")


def mark_active(vault: Vault, account: Account, ats: str, tenant: str) -> Account:
    """Sign-up verified (or login worked): flag the stored account as usable."""
    site = _site(ats, tenant)
    old = next((e.meta for e in vault.find(KIND, site) if e.id == account.entry_id), {})
    vault.put(KIND, site, account.username, account.password, {**old, "status": "active"})
    return Account(account.entry_id, account.username, account.password, "active")
