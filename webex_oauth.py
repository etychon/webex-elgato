"""
Webex OAuth helpers: Device Grant login, token storage, and refresh.

Author: Emmanuel Tychon
SPDX-License-Identifier: MIT
"""

import base64
import json
import os
import time
from datetime import datetime, timezone

import requests

DEFAULT_OAUTH_SCOPE = "spark:all"
# Tried in order when the preferred scope fails (integration-specific combos).
SCOPE_FALLBACKS = (
    "spark:all",
    "spark:people_read",
    "spark:kms spark:all",
    "spark:all spark:kms",
)
DEVICE_AUTHORIZE_URL = "https://webexapis.com/v1/device/authorize"
DEVICE_TOKEN_URL = "https://webexapis.com/v1/device/token"
ACCESS_TOKEN_URL = "https://webexapis.com/v1/access_token"
REFRESH_MARGIN_SECONDS = 300
RELOGIN_HINT = "run: ./webex-elgato-login.sh login"

PORTAL_CHECKLIST = """
Webex Integration setup (one-time, in the Developer Portal):

  1. Open https://developer.webex.com/my-apps → Create an Integration
  2. Name it (e.g. webex-elgato-home)
  3. Add these Redirect URIs (all four):
       https://oauth-helper-a.wbx2.com/helperservice/v1/actions/device/callback
       https://oauth-helper-d.wbx2.com/helperservice/v1/actions/device/callback
       https://oauth-helper-k.wbx2.com/helperservice/v1/actions/device/callback
       https://oauth-helper-r.wbx2.com/helperservice/v1/actions/device/callback
  4. Scopes — enable spark:all (required for People API). If login still says
     "Scope is invalid", also enable spark:kms (common with Device Grant setups).
     Do not combine spark:all with spark:people_read on the same integration.
  5. Save and copy the Client ID and Client Secret (secret shown once)
"""


def oauth_scope():
    """OAuth scope requested at login; must match integration Scopes exactly."""
    env = os.environ.get("WEBEX_OAUTH_SCOPE")
    if env:
        return env.strip()
    creds = _load_json(credentials_path())
    if creds and creds.get("scope"):
        return creds["scope"]
    return DEFAULT_OAUTH_SCOPE


def _scope_mismatch_hint(scope, response_text):
    if "Scope is invalid" not in response_text and "invalid_scope" not in response_text:
        return ""
    return (
        " Requested scope was {!r} — it must match EXACTLY what is enabled on "
        "your integration (https://developer.webex.com/my-apps). "
        "spark:all and spark:people_read are mutually exclusive in the portal. "
        "If you enabled spark:people_read only, run: "
        "WEBEX_OAUTH_SCOPE=spark:people_read ./webex-elgato-login.sh login "
        "Or edit ~/.config/webex-elgato/credentials.json and set "
        '"scope": "spark:people_read", then run login again.'
    ).format(scope)


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return os.path.join(base, "webex-elgato")
    return os.path.join(os.path.expanduser("~"), ".config", "webex-elgato")


def credentials_path():
    return os.path.join(config_dir(), "credentials.json")


def tokens_path():
    return os.path.join(config_dir(), "tokens.json")


def _ensure_config_dir():
    path = config_dir()
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _atomic_write_json(path, data):
    _ensure_config_dir()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _load_json(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_credentials(client_id, client_secret, scope=None):
    existing = _load_json(credentials_path()) or {}
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": scope or existing.get("scope") or DEFAULT_OAUTH_SCOPE,
    }
    _atomic_write_json(credentials_path(), data)


def load_credentials():
    creds = _load_json(credentials_path())
    if creds and creds.get("client_id") and creds.get("client_secret"):
        return (
            creds["client_id"],
            creds["client_secret"],
            creds.get("scope"),
        )
    client_id = os.environ.get("WEBEX_CLIENT_ID")
    client_secret = os.environ.get("WEBEX_CLIENT_SECRET")
    if client_id and client_secret:
        return client_id, client_secret, oauth_scope()
    return None, None, None


def save_tokens(access_token, refresh_token, expires_in, refresh_expires_in):
    now = time.time()
    data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": now + int(expires_in),
        "refresh_expires_at": now + int(refresh_expires_in),
    }
    _atomic_write_json(tokens_path(), data)
    return data


def load_tokens():
    return _load_json(tokens_path())


def tokens_file_exists():
    data = load_tokens()
    return bool(data and data.get("access_token") and data.get("refresh_token"))


def _basic_auth_header(client_id, client_secret):
    raw = "{}:{}".format(client_id, client_secret).encode("utf-8")
    return "Basic {}".format(base64.b64encode(raw).decode("ascii"))


def _parse_token_response(payload):
    if not payload.get("access_token"):
        raise RuntimeError("Webex token response missing access_token")
    refresh = payload.get("refresh_token")
    if not refresh:
        raise RuntimeError("Webex token response missing refresh_token")
    expires_in = payload.get("expires_in", 0)
    refresh_expires_in = payload.get("refresh_token_expires_in", 0)
    return save_tokens(
        payload["access_token"],
        refresh,
        expires_in,
        refresh_expires_in,
    )


def refresh_tokens(client_id, client_secret, refresh_token):
    res = requests.post(
        ACCESS_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    if not res.ok:
        raise RuntimeError(
            "Token refresh failed (HTTP {}): {} — {}".format(
                res.status_code, res.text[:300], RELOGIN_HINT
            )
        )
    return _parse_token_response(res.json())


class TokenProvider:
    """Returns a valid access token, refreshing from disk when needed."""

    def __init__(self):
        self._tokens = load_tokens()
        self._client_id, self._client_secret, _scope = load_credentials()

    def has_oauth_setup(self):
        return bool(
            self._client_id
            and self._client_secret
            and self._tokens
            and self._tokens.get("refresh_token")
        )

    def force_refresh(self):
        if not self._client_id or not self._client_secret:
            raise RuntimeError(
                "Missing OAuth credentials — {}".format(RELOGIN_HINT)
            )
        if not self._tokens or not self._tokens.get("refresh_token"):
            raise RuntimeError(
                "Missing OAuth tokens — {}".format(RELOGIN_HINT)
            )
        self._tokens = refresh_tokens(
            self._client_id,
            self._client_secret,
            self._tokens["refresh_token"],
        )
        return self._tokens["access_token"]

    def get_access_token(self):
        if not self.has_oauth_setup():
            raise RuntimeError(
                "OAuth not configured — {}".format(RELOGIN_HINT)
            )
        expires_at = float(self._tokens.get("expires_at", 0))
        if expires_at > time.time() + REFRESH_MARGIN_SECONDS:
            return self._tokens["access_token"]
        return self.force_refresh()


def _scope_locked(scope_locked=False):
    return scope_locked or bool(os.environ.get("WEBEX_OAUTH_SCOPE"))


def _device_authorize(client_id, scope):
    return requests.post(
        DEVICE_AUTHORIZE_URL,
        data={"client_id": client_id, "scope": scope},
        timeout=30,
    )


def _resolve_device_scope(
    client_id, client_secret, preferred_scope, print_fn=print, scope_locked=False
):
    """Pick a scope string that this integration accepts for device/authorize."""
    candidates = [preferred_scope]
    for scope in SCOPE_FALLBACKS:
        if scope not in candidates:
            candidates.append(scope)

    if _scope_locked(scope_locked):
        candidates = [preferred_scope]

    last_body = ""
    for scope in candidates:
        res = _device_authorize(client_id, scope)
        if res.ok:
            if scope != preferred_scope and client_secret:
                print_fn(
                    "Adjusted OAuth scope to {!r} (matches your integration).".format(
                        scope
                    )
                )
                save_credentials(client_id, client_secret, scope)
            return scope, res
        last_body = res.text[:500]

    raise RuntimeError(
        "Device authorize failed: no working scope found for this integration.{}{}".format(
            " Tried: {}.".format(", ".join(candidates)) if len(candidates) > 1 else "",
            _scope_mismatch_hint(preferred_scope, last_body),
        )
    )


def device_login(client_id, client_secret, print_fn=print, scope_locked=False):
    """Run Device Grant Flow; save tokens on success."""
    preferred = oauth_scope()
    scope, res = _resolve_device_scope(
        client_id,
        client_secret,
        preferred,
        print_fn=print_fn,
        scope_locked=scope_locked,
    )
    auth = res.json()
    user_code = auth.get("user_code", "")
    verification_complete = auth.get("verification_uri_complete", "")
    verification_uri = auth.get("verification_uri", "")
    device_code = auth.get("device_code", "")
    expires_in = int(auth.get("expires_in", 300))
    interval = max(int(auth.get("interval", 5)), 2)

    print_fn("")
    print_fn("Open this link on your phone or laptop (valid {} minutes):".format(
        max(expires_in // 60, 1)
    ))
    if verification_complete:
        print_fn("  {}".format(verification_complete))
    if verification_uri and user_code:
        print_fn("")
        print_fn("Or go to {} and enter code: {}".format(
            verification_uri, user_code
        ))
    print_fn("")
    print_fn("Waiting for you to approve in the browser...")

    deadline = time.time() + expires_in
    headers = {"Authorization": _basic_auth_header(client_id, client_secret)}
    body = {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": device_code,
        "client_id": client_id,
    }

    while time.time() < deadline:
        time.sleep(interval)
        poll = requests.post(
            DEVICE_TOKEN_URL,
            headers=headers,
            data=body,
            timeout=30,
        )
        if poll.status_code == 200:
            tokens = _parse_token_response(poll.json())
            print_fn("")
            print_fn("Webex authorization successful. Tokens saved to:")
            print_fn("  {}".format(tokens_path()))
            return tokens

        if poll.status_code == 428:
            continue

        try:
            err = poll.json()
            error = err.get("error", "")
        except (json.JSONDecodeError, ValueError):
            error = ""

        if error in ("authorization_pending", "slow_down"):
            if error == "slow_down":
                interval = min(interval + 2, 30)
            continue

        raise RuntimeError(
            "Device login failed (HTTP {}): {}".format(
                poll.status_code, poll.text[:500]
            )
        )

    raise RuntimeError(
        "Device login timed out after {} seconds. Run login again.".format(
            expires_in
        )
    )


def format_expiry(epoch):
    if not epoch:
        return "unknown"
    dt = datetime.fromtimestamp(float(epoch), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def auth_status_lines():
    """Human-readable status for the status subcommand."""
    lines = []
    cred_id, cred_secret, cred_scope = load_credentials()
    tokens = load_tokens()
    pat = os.environ.get("WEBEX_ACCESS_TOKEN")

    if tokens and tokens.get("access_token"):
        lines.append("Auth mode: OAuth (stored tokens)")
        if cred_id:
            lines.append("Client ID: {}...".format(cred_id[:12]))
        if cred_scope or cred_id:
            lines.append("OAuth scope: {}".format(oauth_scope()))
        lines.append(
            "Access token expires: {}".format(
                format_expiry(tokens.get("expires_at"))
            )
        )
        lines.append(
            "Refresh token expires: {}".format(
                format_expiry(tokens.get("refresh_expires_at"))
            )
        )
        now = time.time()
        if tokens.get("refresh_expires_at", 0) < now:
            lines.append("Action needed: refresh token expired — run login")
        elif tokens.get("expires_at", 0) < now + REFRESH_MARGIN_SECONDS:
            lines.append("Note: access token will refresh automatically on next poll")
    elif pat:
        lines.append("Auth mode: personal access token (WEBEX_ACCESS_TOKEN)")
        lines.append("Note: PAT expires ~12h after Developer Portal login")
    elif cred_id and cred_secret:
        lines.append("Auth mode: OAuth credentials saved, not yet logged in")
        lines.append("Action needed: run ./webex-elgato-login.sh login")
    else:
        lines.append("Auth mode: not configured")
        lines.append("Action needed: run ./webex-elgato-login.sh setup")
    return lines
