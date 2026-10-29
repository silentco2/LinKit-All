"""Microsoft (Outlook, Hotmail, Live, MSN) mailboxes: OAuth2 sign-in for IMAP/SMTP (XOAUTH2).

Microsoft turned off app passwords for consumer IMAP/SMTP. Sign-in is a public-client loopback
flow (msal opens the browser and listens once on http://localhost). The serialized msal token
cache, which holds the refresh token, is the vault secret (kind="imap", site=IMAP_HOST).
Tokens are never logged. The client id comes from LINKIT_MS_CLIENT_ID (docs/setup.md).
"""

import msal
import requests

from linkit_all.core.config import get_settings

IMAP_HOST = "outlook.office365.com"
SMTP_HOST = "smtp-mail.outlook.com"
SMTP_PORT = 587  # STARTTLS only
HOSTS = {IMAP_HOST, "imap-mail.outlook.com"}
AUTHORITY = "https://login.microsoftonline.com/consumers"
# msal adds openid/profile/offline_access itself (offline_access = the refresh token)
SCOPES = [
    "https://outlook.office.com/IMAP.AccessAsUser.All",
    "https://outlook.office.com/SMTP.Send",
]
SIGN_IN_TIMEOUT_S = 300


class MicrosoftAuthError(Exception):
    """Plain-language reason the Microsoft sign-in failed."""


def is_host(host: str) -> bool:
    return host.strip().lower() in HOSTS


def configured() -> bool:
    return bool(get_settings().ms_client_id)


def _app(cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    client_id = get_settings().ms_client_id
    if not client_id:
        raise MicrosoftAuthError("Microsoft sign-in is not set up: set LINKIT_MS_CLIENT_ID")
    return msal.PublicClientApplication(client_id, authority=AUTHORITY, token_cache=cache)


def sign_in(login_hint: str) -> tuple[str, str, str]:
    """Blocking: open the browser for Microsoft sign-in; (address, access token, cache JSON)."""
    cache = msal.SerializableTokenCache()
    try:
        r = _app(cache).acquire_token_interactive(
            SCOPES,
            login_hint=login_hint or None,
            prompt="select_account",
            timeout=SIGN_IN_TIMEOUT_S,
        )
    except msal.BrowserInteractionTimeoutError:
        raise MicrosoftAuthError("Microsoft sign-in timed out: try again") from None
    except requests.RequestException:
        raise MicrosoftAuthError("Could not reach Microsoft") from None
    if "access_token" not in r:
        raise MicrosoftAuthError("Microsoft sign-in was cancelled")
    user = str((r.get("id_token_claims") or {}).get("preferred_username") or login_hint)
    return user.strip().lower(), str(r["access_token"]), cache.serialize()


def access_token(cache_json: str, user: str) -> tuple[str, str | None]:
    """A new access token from the stored refresh token, plus the cache JSON when it changed
    (Microsoft rotates refresh tokens; the caller saves it back to the vault)."""
    cache = msal.SerializableTokenCache()
    cache.deserialize(cache_json)
    app = _app(cache)
    accounts = app.get_accounts(username=user) or app.get_accounts()
    try:
        # ponytail: always refresh, so the token (~1 h) outlives the longest poll (30 min)
        r = (
            app.acquire_token_silent(SCOPES, account=accounts[0], force_refresh=True)
            if accounts
            else None
        )
    except requests.RequestException:
        raise MicrosoftAuthError("Could not reach Microsoft") from None
    if not r or "access_token" not in r:
        raise MicrosoftAuthError("The Microsoft sign-in expired: sign in with Microsoft again")
    return str(r["access_token"]), cache.serialize() if cache.has_state_changed else None


def xoauth2(user: str, token: str) -> str:
    """The SASL XOAUTH2 initial response (before base64)."""
    return f"user={user}\x01auth=Bearer {token}\x01\x01"
