"""Microsoft (Outlook, Hotmail, Live, MSN) mailboxes: OAuth2 sign-in, mail via Microsoft Graph.

Microsoft turned off app passwords for consumer IMAP/SMTP, and IMAP with OAuth (XOAUTH2) fails
server-side for many personal accounts ("User is authenticated but not connected", 2026), so
mail is read and sent through Graph instead. Sign-in is a public-client loopback flow (msal
opens the browser and listens once on http://localhost). The serialized msal token cache, which
holds the refresh token, is the vault secret (kind="imap", site=IMAP_HOST, kept as the marker).
Tokens and mail bodies are never logged. The client id comes from LINKIT_MS_CLIENT_ID.
"""

import base64
from datetime import UTC, datetime
from typing import Any

import httpx
import msal
import requests

from linkit_all.core.config import get_settings

IMAP_HOST = "outlook.office365.com"  # the saved "imap_host" that marks a Microsoft mailbox
HOSTS = {IMAP_HOST, "imap-mail.outlook.com"}
AUTHORITY = "https://login.microsoftonline.com/consumers"
GRAPH = "https://graph.microsoft.com/v1.0/me"
# msal adds openid/profile/offline_access itself (offline_access = the refresh token)
SCOPES = ["https://graph.microsoft.com/Mail.Read", "https://graph.microsoft.com/Mail.Send"]
FOLDERS = ("inbox", "junkemail")  # Graph's well-known names, any mailbox language
SIGN_IN_TIMEOUT_S = 300

# (key, received, sender address, subject, text body, html body)
Row = tuple[str, datetime, str, str, str, str]


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


def _graph(method: str, path: str, token: str, **kw: Any) -> httpx.Response:
    """One Graph call. 401/403 -> MicrosoftAuthError; network or other errors -> ConnectionError
    (an OSError, which pollers treat as a blip)."""
    headers = {"Authorization": f"Bearer {token}", **kw.pop("headers", {})}
    try:
        r = httpx.request(method, GRAPH + path, headers=headers, timeout=30, **kw)
    except httpx.HTTPError as e:
        raise ConnectionError(f"Could not reach Microsoft ({type(e).__name__})") from None
    if r.status_code in (401, 403):
        raise MicrosoftAuthError("Microsoft rejected the sign-in: sign in with Microsoft again")
    if r.is_error:
        raise ConnectionError(f"Microsoft mail returned HTTP {r.status_code}")
    return r


def check(token: str) -> None:
    """Raise unless the token can read the inbox."""
    _graph("GET", "/mailFolders/inbox", token, params={"$select": "id"})


def messages(token: str, since: datetime, limit: int) -> list[Row]:
    """Inbox and junk mail received since `since`. Read-only: a Graph GET never marks it read."""
    floor = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "$filter": f"receivedDateTime ge {floor}",
        "$orderby": "receivedDateTime desc",
        "$top": str(limit),
        "$select": "id,subject,from,receivedDateTime,body",
    }
    rows: list[Row] = []
    for folder in FOLDERS:
        page = _graph("GET", f"/mailFolders/{folder}/messages", token, params=params).json()
        for m in page["value"]:
            when = datetime.fromisoformat(m["receivedDateTime"].replace("Z", "+00:00"))
            sender = ((m.get("from") or {}).get("emailAddress") or {}).get("address") or ""
            body = m.get("body") or {}
            content = str(body.get("content") or "")
            html = content if body.get("contentType") == "html" else ""
            text = "" if html else content
            rows.append((f"{folder}:{m['id']}", when, sender, m.get("subject") or "", text, html))
    return rows


def send_mime(token: str, mime: bytes) -> None:
    """Send a complete MIME message (headers, body, attachments) as the signed-in user; Graph
    keeps a copy in Sent Items."""
    # ponytail: Graph caps a request at 4 MB (~2.9 MB of attachments); upload sessions beyond that
    headers = {"Content-Type": "text/plain"}
    _graph("POST", "/sendMail", token, content=base64.b64encode(mime), headers=headers)
