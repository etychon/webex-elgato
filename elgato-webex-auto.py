#!/usr/bin/env python3
"""
Poll Webex presence and toggle Elgato Key Light(s) on the LAN when in a meeting.

Author: Emmanuel Tychon
SPDX-License-Identifier: MIT
"""

import json
import os
import sys
import time
from datetime import datetime

import requests

from elgato_discover import discover_key_lights

try:
    import constants
except ImportError:
    constants = None

PEOPLE_URL = "https://webexapis.com/v1/people"
POLL_INTERVAL = int(os.environ.get("WEBEX_ELGATO_POLL_SECONDS", "10"))
DISCOVER_TIMEOUT = float(os.environ.get("WEBEX_ELGATO_DISCOVER_SECONDS", "2"))
OFF_AFTER_POLLS = int(os.environ.get("WEBEX_ELGATO_OFF_AFTER_POLLS", "3"))
MEETING_STATUSES = frozenset({"meeting", "presenting", "call"})
AMBIGUOUS_STATUSES = frozenset({"DoNotDisturb", "unknown"})


def t_print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    print(datetime.now(), *args, **kwargs)


def load_config():
    """Prefer environment variables so secrets are not required in a Python file."""
    token = os.environ.get("WEBEX_ACCESS_TOKEN")
    email = os.environ.get("WEBEX_EMAIL")
    if constants is not None:
        token = token or getattr(constants, "access_token", None)
        email = email or getattr(constants, "email", None)
    if not token or not email:
        t_print(
            "Missing WEBEX_ACCESS_TOKEN or WEBEX_EMAIL "
            "(or define both in constants.py).",
            file=sys.stderr,
        )
        sys.exit(1)
    return token, email


def discover_lights():
    lights = discover_key_lights(DISCOVER_TIMEOUT)
    return list(lights) if lights else []


def initial_light_on(lights):
    return bool(lights and lights[0].isOn)


def spinning_cursor():
    while True:
        for cursor in "|/-\\":
            yield cursor


def fetch_person_status(client, token, email):
    headers = {
        "Authorization": "Bearer {}".format(token),
        "Content-Type": "application/json",
    }
    params = {"email": email}
    res = client.get(PEOPLE_URL, headers=headers, params=params, timeout=30)
    if res.status_code == 401:
        raise RuntimeError(
            "Webex returned 401: access token expired or invalid; issue a new token."
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
    if not isinstance(items, list) or not items:
        return None
    person = items[0]
    if not isinstance(person, dict):
        return None
    return person.get("status")


def main():
    access_token, email = load_config()
    client = requests.Session()

    all_lights = discover_lights()
    light_on = initial_light_on(all_lights)
    no_in_meeting_count = 0
    spinner = spinning_cursor()

    while True:
        try:
            resj = fetch_person_status(client, access_token, email)
            status = parse_status(resj)
            if status is None:
                time.sleep(POLL_INTERVAL)
                continue

            sys.stdout.write("\r")
            t_print(status, end=" ")

            if status in MEETING_STATUSES:
                no_in_meeting_count = 0
                if not light_on:
                    all_lights = discover_lights()
                    t_print(
                        "User is in a meeting -> turn light on [list: {}]".format(
                            all_lights
                        )
                    )
                    if all_lights:
                        for light in all_lights:
                            light.on()
                        light_on = True
                    else:
                        t_print("No Key Lights found; will retry next poll.")
            elif status in AMBIGUOUS_STATUSES:
                # Presence is ambiguous; do not change light or off-counter.
                pass
            else:
                if light_on:
                    no_in_meeting_count += 1
                    if no_in_meeting_count > OFF_AFTER_POLLS:
                        all_lights = discover_lights()
                        t_print(
                            "User is not in a meeting ({}) -> turn light off [list: {}]".format(
                                status, all_lights
                            )
                        )
                        for light in all_lights:
                            light.off()
                        light_on = False

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
            all_lights = discover_lights()
            light_on = initial_light_on(all_lights)

        sys.stdout.write(next(spinner))
        sys.stdout.write("\033[K")
        sys.stdout.flush()
        sys.stdout.write("\b")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
