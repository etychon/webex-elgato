# webex-elgato

Small Python utility that watches **Webex presence** and toggles **Elgato Key Light** devices on the local network: lights turn on when Webex reports an active meeting-style state, and turn off after a short run of “not in meeting” polls (debounced to avoid flicker).

Presence comes from the [Webex People API](https://developer.webex.com/docs/api/v1/people), so it can follow the same user across desk phone, desktop app, mobile, or room endpoints, depending on how Webex attributes status.

Typical uses:

- Automatic key / fill light when on camera  
- Simple “on air” or “do not disturb” cue for people nearby  

## Requirements

- **Python 3** (3.8+ recommended)  
- **Network**: outbound HTTPS to `webexapis.com`, and local LAN access to Elgato Key Light (Bonjour / mDNS discovery)  
- **Webex**: a [personal access token](https://developer.webex.com/docs/getting-started) and a way to select whose presence to read (see **Who to poll** below)  
- **Hardware**: at least one Elgato Key Light reachable on the same LAN as the machine running the script  

## Install

Clone the repository and install dependencies (ideally in a virtual environment):

```bash
git clone https://github.com/etychon/webex-elgato.git
cd webex-elgato
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Run the monitor (uses `.venv` automatically):

```bash
./run-webex-elgato.sh
```

For **systemd**, point `ExecStart` at the same script (see the unit template under `systemd/`). If you already installed an older unit that calls `/usr/bin/python3` or `.venv/bin/python` directly, **replace it** with the template’s `ExecStart=%h/webex-elgato/run-webex-elgato.sh`, then `systemctl --user daemon-reload && systemctl --user restart webex-elgato.service`.

## Configure

### Recommended: environment variables

Keeps secrets out of the repo and out of shell history if paired with a systemd `EnvironmentFile` (see below).

```bash
export WEBEX_ACCESS_TOKEN="your_personal_access_token"
# Then pick exactly one identity mode (see table); simplest for a personal token is to omit both lines below.
python3 elgato-webex-auto.py
```

Create and refresh tokens from the Webex developer portal ([Getting started](https://developer.webex.com/docs/getting-started)). If the script logs **HTTP 401**, the token is missing, wrong, or expired—issue a new token and update the environment (or env file).

#### Who to poll (People API)

The script needs **only** `WEBEX_ACCESS_TOKEN` plus **one** way to choose the person whose `status` field is read. Precedence is:

1. **`WEBEX_PERSON_ID`** — Webex **person id** (long string from API responses, e.g. `people` → `id`). Uses [`GET /people/{personId}`](https://developer.webex.com/docs/api/v1/people/get-person-details).
2. Else **`WEBEX_EMAIL`** — uses [`GET /people?email=…`](https://developer.webex.com/docs/api/v1/people/list-people) (same as before).
3. Else **neither set** — uses [`GET /people/me`](https://developer.webex.com/docs/api/v1/people/get-my-own-details) for the user that issued the token (typical for a **personal access token** monitoring yourself).

In `constants.py`, the same fields are **`user_id`** (maps to `WEBEX_PERSON_ID`), **`email`**, or omit both for `/me`.

### Alternative: `constants.py`

Copy the example and edit locally (this file is **gitignored** so it is not committed by default):

```bash
cp constants.py.example constants.py
# Edit constants.py — never commit real tokens
python3 elgato-webex-auto.py
```

Environment variables **override** values in `constants.py` when both are set.

### Optional tuning

| Variable | Description | Default |
|----------|-------------|---------|
| `WEBEX_ELGATO_POLL_SECONDS` | Delay between Webex polls (seconds) | `10` |
| `WEBEX_ELGATO_DISCOVER_SECONDS` | mDNS discovery timeout for Key Light | `2` |
| `WEBEX_ELGATO_OFF_AFTER_POLLS` | Consecutive “not in meeting” polls before turning lights off | `3` |

## Run on Linux with systemd (user service)

Example unit and env templates are under [`systemd/`](systemd/).

1. **Secrets file** — copy the example, edit values, restrict permissions:

   ```bash
   install -m 600 systemd/webex-elgato.env.example ~/.config/webex-elgato.env
   ${EDITOR:-nano} ~/.config/webex-elgato.env
   ```

2. **Service unit** — copy the example into the user unit directory, then adjust paths if your clone is not `$HOME/webex-elgato`. The template **`ExecStart`s `run-webex-elgato.sh`**, which always runs **`.venv/bin/python`** from the repo and prints a clear error if the venv or `pip install -r requirements.txt` step is missing. Re-copy this unit if you still see `ModuleNotFoundError: zeroconf` from an old `ExecStart=/usr/bin/python3 …` line.

   ```bash
   mkdir -p ~/.config/systemd/user
   cp systemd/webex-elgato.service.example ~/.config/systemd/user/webex-elgato.service
   ${EDITOR:-nano} ~/.config/systemd/user/webex-elgato.service
   ```

3. **Enable and inspect logs**:

   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now webex-elgato.service
   journalctl --user -u webex-elgato.service -f
   ```

By default, **user** units stop when your last login session ends (for example after you log out of the desktop). **`loginctl enable-linger`** tells systemd to keep **your** user service manager running anyway: it can start **at boot**, and your **enabled** `systemctl --user` services (such as this one) can run **without** you opening an interactive login first.

```bash
loginctl enable-linger "$USER"
```

## Security notes

- Treat the Webex token like a password: **do not** commit it, paste it into issues, or share screen shots that include it.  
- Prefer environment variables or a root-owned / user-only-readable env file (`chmod 600`) over storing tokens in project files.  
- If a token was ever exposed, **revoke** it in the Webex developer portal and create a new one.  

## Troubleshooting

| Symptom | Things to check |
|--------|------------------|
| 401 from Webex | Token expired or revoked; scope/access; update `WEBEX_ACCESS_TOKEN`. |
| Lights never turn on | Key Light powered on, same subnet/VLAN as this host, mDNS not blocked by Wi‑Fi client isolation or firewalls; try increasing `WEBEX_ELGATO_DISCOVER_SECONDS`. |
| Status never “meeting” | For `/me`, the token must be for that user. For email lookup, `WEBEX_EMAIL` must match. For `WEBEX_PERSON_ID`, the id must be correct and your token must be allowed to read that person. |
| Lights flicker | Increase `WEBEX_ELGATO_OFF_AFTER_POLLS` or `WEBEX_ELGATO_POLL_SECONDS`. |

## License

Copyright © 2022–2026 **Emmanuel Tychon**. This project is released under the [MIT License](LICENSE).
