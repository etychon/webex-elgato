#!/usr/bin/env python3
"""
Poll Webex presence and toggle Elgato Key Light(s) on the LAN when in a meeting.

Author: Emmanuel Tychon
SPDX-License-Identifier: MIT
"""

import argparse
import getpass
import json
import os
import sys
import time
from datetime import datetime
from urllib.parse import quote

import requests

from elgato_discover import discover_key_lights
from webex_oauth import (
    DEFAULT_OAUTH_SCOPE,
    PORTAL_CHECKLIST,
    RELOGIN_HINT,
    TokenProvider,
    auth_status_lines,
    credentials_path,
    device_login,
    load_credentials,
    oauth_scope,
    save_credentials,
    tokens_file_exists,
)

try:
    import constants
except ImportError:
    constants = None

PEOPLE_URL = "https://webexapis.com/v1/people"
POLL_INTERVAL = int(os.environ.get("WEBEX_ELGATO_POLL_SECONDS", "10"))
DISCOVER_TIMEOUT = float(os.environ.get("WEBEX_ELGATO_DISCOVER_SECONDS", "2"))
DISCOVER_RETRY_SECONDS = float(
    os.environ.get("WEBEX_ELGATO_DISCOVER_RETRY_SECONDS", "60")
)
OFF_AFTER_POLLS = int(os.environ.get("WEBEX_ELGATO_OFF_AFTER_POLLS", "3"))
MEETING_STATUSES = frozenset({"meeting", "presenting", "call"})
AMBIGUOUS_STATUSES = frozenset({"DoNotDisturb", "unknown"})
INTERACTIVE_STDOUT = sys.stdout.isatty()


def t_print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    print(datetime.now(), *args, **kwargs)


def load_identity():
    """Load person identity for the People API (see README for modes)."""
    person_id = os.environ.get("WEBEX_PERSON_ID")
    email = os.environ.get("WEBEX_EMAIL")
    if constants is not None:
        person_id = person_id or getattr(constants, "user_id", None)
        email = email or getattr(constants, "email", None)
    if person_id:
        mode = "person_id"
    elif email:
        mode = "email"
    else:
        mode = "me"
    return mode, person_id, email


def _static_pat_token():
    token = os.environ.get("WEBEX_ACCESS_TOKEN")
    if constants is not None:
        token = token or getattr(constants, "access_token", None)
    return token


def resolve_auth():
    """
    Return (token_provider, identity_mode, person_id, email).

    token_provider is either a TokenProvider instance (OAuth) or a str (static PAT).
    OAuth stored tokens take precedence over PAT when both exist.
    """
    mode, person_id, email = load_identity()
    pat = _static_pat_token()

    if tokens_file_exists():
        provider = TokenProvider()
        return provider, mode, person_id, email

    if pat:
        return pat, mode, person_id, email

    client_id, client_secret, _scope = load_credentials()
    if client_id and client_secret:
        t_print(
            "OAuth credentials found but no tokens. Run: ./webex-elgato-login.sh login",
            file=sys.stderr,
        )
        sys.exit(1)

    t_print(
        "No Webex authentication configured.",
        file=sys.stderr,
    )
    t_print(
        "  OAuth (recommended): ./webex-elgato-login.sh setup",
        file=sys.stderr,
    )
    t_print(
        "  Quick test only:     set WEBEX_ACCESS_TOKEN (expires in ~12 hours)",
        file=sys.stderr,
    )
    sys.exit(1)


def _get_token(auth):
    if isinstance(auth, TokenProvider):
        return auth.get_access_token()
    return auth


def discover_lights():
    lights = discover_key_lights(DISCOVER_TIMEOUT)
    return list(lights) if lights else []


class LightDiscovery:
    """Rate-limited mDNS discovery to avoid leaking resources when lights are offline."""

    def __init__(self):
        self._lights = []
        self._last_attempt = 0.0

    def discover(self, force=False):
        now = time.time()
        if (
            not force
            and self._last_attempt
            and now - self._last_attempt < DISCOVER_RETRY_SECONDS
        ):
            return list(self._lights), False
        self._last_attempt = now
        self._lights = discover_lights()
        return list(self._lights), True

    def invalidate(self):
        self._lights = []
        self._last_attempt = 0.0


def initial_light_on(lights):
    return bool(lights and lights[0].isOn)


def spinning_cursor():
    while True:
        for cursor in "|/-\\":
            yield cursor


def fetch_person_status(client, auth, mode, person_id, email, retried=False):
    token = _get_token(auth)
    headers = {
        "Authorization": "Bearer {}".format(token),
        "Content-Type": "application/json",
    }
    if mode == "person_id":
        url = "{}/{}".format(PEOPLE_URL, quote(str(person_id), safe=""))
        res = client.get(url, headers=headers, timeout=30)
    elif mode == "email":
        res = client.get(
            PEOPLE_URL, headers=headers, params={"email": email}, timeout=30
        )
    else:
        res = client.get("{}/me".format(PEOPLE_URL), headers=headers, timeout=30)

    if res.status_code == 401:
        if isinstance(auth, TokenProvider) and not retried:
            auth.force_refresh()
            return fetch_person_status(
                client, auth, mode, person_id, email, retried=True
            )
        raise RuntimeError(
            "Webex returned 401: access token expired or invalid; {}".format(
                RELOGIN_HINT
            )
        )
    if not res.ok:
        raise RuntimeError(
            "Webex HTTP {}: {}".format(res.status_code, res.text[:500])
        )
    return res.json()


def parse_status(payload):
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if isinstance(items, list) and items:
        person = items[0]
        if isinstance(person, dict):
            return person.get("status")
        return None
    if "items" not in payload and "status" in payload:
        return payload.get("status")
    return None


def _prompt_scope():
    print("")
    print("OAuth scope must match EXACTLY one scope enabled on your integration.")
    print("  spark:all          — recommended (Device Grant sample)")
    print("  spark:people_read  — minimal, only if spark:all is NOT checked")
    default = DEFAULT_OAUTH_SCOPE
    entered = input("Scope [{}]: ".format(default)).strip()
    return entered or default


def _prompt_credentials(scope_override=None):
    print(PORTAL_CHECKLIST)
    client_id = input("Client ID: ").strip()
    if not client_id:
        print("Client ID is required.", file=sys.stderr)
        sys.exit(1)
    client_secret = getpass.getpass("Client Secret: ").strip()
    if not client_secret:
        print("Client Secret is required.", file=sys.stderr)
        sys.exit(1)
    scope = scope_override or _prompt_scope()
    return client_id, client_secret, scope


def cmd_setup(args):
    client_id, client_secret, scope = _prompt_credentials(
        scope_override=getattr(args, "scope", None)
    )
    save_credentials(client_id, client_secret, scope)
    print("Credentials saved to {}".format(credentials_path()))
    print("Using OAuth scope: {}".format(oauth_scope()))
    device_login(
        client_id,
        client_secret,
        print_fn=print,
        scope_locked=bool(getattr(args, "scope", None)),
    )
    print("")
    print("Next: systemctl --user restart webex-elgato.service")


def cmd_login(args):
    scope_arg = getattr(args, "scope", None)
    client_id, client_secret, saved_scope = load_credentials()
    if not client_id or not client_secret:
        client_id, client_secret, scope = _prompt_credentials(
            scope_override=scope_arg
        )
    else:
        scope = scope_arg or saved_scope or DEFAULT_OAUTH_SCOPE
    save_credentials(client_id, client_secret, scope)
    print("Using OAuth scope: {}".format(oauth_scope()))
    device_login(
        client_id,
        client_secret,
        print_fn=print,
        scope_locked=bool(scope_arg),
    )
    print("")
    print("Next: systemctl --user restart webex-elgato.service")


def cmd_status(_args):
    for line in auth_status_lines():
        print(line)


def run_monitor():
    auth, identity_mode, person_id, email = resolve_auth()
    client = requests.Session()
    discovery = LightDiscovery()

    all_lights, _ = discovery.discover(force=True)
    light_on = initial_light_on(all_lights)
    no_in_meeting_count = 0
    spinner = spinning_cursor()
    last_logged_status = None

    while True:
        try:
            resj = fetch_person_status(
                client, auth, identity_mode, person_id, email
            )
            status = parse_status(resj)
            if status is None:
                time.sleep(POLL_INTERVAL)
                continue

            if INTERACTIVE_STDOUT:
                sys.stdout.write("\r")
                t_print(status, end=" ")
            elif status != last_logged_status:
                t_print("presence:", status)
                last_logged_status = status

            if status in MEETING_STATUSES:
                no_in_meeting_count = 0
                if not light_on:
                    all_lights, attempted = discovery.discover()
                    if attempted:
                        t_print(
                            "User is in a meeting -> turn light on [list: {}]".format(
                                all_lights
                            )
                        )
                    if all_lights:
                        for light in all_lights:
                            light.on()
                        light_on = True
                    elif attempted:
                        t_print(
                            "No Key Lights found; retrying discovery in {}s.".format(
                                int(DISCOVER_RETRY_SECONDS)
                            )
                        )
            elif status in AMBIGUOUS_STATUSES:
                pass
            else:
                if light_on:
                    no_in_meeting_count += 1
                    if no_in_meeting_count > OFF_AFTER_POLLS:
                        all_lights, attempted = discovery.discover()
                        if not attempted:
                            continue
                        t_print(
                            "User is not in a meeting ({}) -> turn light off [list: {}]".format(
                                status, all_lights
                            )
                        )
                        for light in all_lights:
                            light.off()
                        light_on = False
                        discovery.invalidate()

        except requests.exceptions.RequestException as exc:
            t_print("HTTP error: {} — retrying in 60s".format(exc))
            time.sleep(60)
            continue
        except (json.JSONDecodeError, RuntimeError) as exc:
            t_print("Error: {} — retrying in 60s".format(exc))
            time.sleep(60)
            continue
        except Exception as exc:
            t_print("Unexpected error: {} — retrying in 60s".format(exc))
            time.sleep(60)
            discovery.invalidate()
            all_lights, _ = discovery.discover(force=True)
            light_on = initial_light_on(all_lights)

        if INTERACTIVE_STDOUT:
            sys.stdout.write(next(spinner))
            sys.stdout.write("\033[K")
            sys.stdout.flush()
            sys.stdout.write("\b")

        time.sleep(POLL_INTERVAL)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Webex presence monitor for Elgato Key Light"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="Run the presence monitor (default)")
    setup_p = sub.add_parser(
        "setup",
        help="Interactive OAuth setup: portal checklist, credentials, device login",
    )
    setup_p.add_argument(
        "--scope",
        help="OAuth scope (must match portal exactly, e.g. spark:all)",
    )
    login_p = sub.add_parser(
        "login",
        help="Re-run device login (when refresh token expires or is revoked)",
    )
    login_p.add_argument(
        "--scope",
        help="OAuth scope (must match portal exactly, e.g. spark:people_read)",
    )
    sub.add_parser("status", help="Show authentication status and token expiry")

    args = parser.parse_args(argv)
    command = args.command or "run"

    if command == "setup":
        cmd_setup(args)
    elif command == "login":
        cmd_login(args)
    elif command == "status":
        cmd_status(args)
    else:
        run_monitor()


if __name__ == "__main__":
    main()
