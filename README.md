# webex-elgato

Small Python utility that watches **Webex presence** and toggles **Elgato Key Light** devices on the local network: lights turn on when Webex reports an active meeting-style state, and turn off after a short run of “not in meeting” polls (debounced to avoid flicker).

Presence comes from the [Webex People API](https://developer.webex.com/docs/api/v1/people), so it can follow the same user across desk phone, desktop app, mobile, or room endpoints, depending on how Webex attributes status.

Typical uses:

- Automatic key / fill light when on camera  
- Simple “on air” or “do not disturb” cue for people nearby  

## Requirements

- **Python 3** (3.8+ recommended)  
- **Network**: outbound HTTPS to `webexapis.com`, and local LAN access to Elgato Key Light (Bonjour / mDNS discovery)  
- **Webex**: a [Webex Integration](https://developer.webex.com/create/docs/integrations) with OAuth (recommended), or a short-lived [personal access token](https://developer.webex.com/docs/getting-started) for quick tests  
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

### Recommended: OAuth (always-on hosts, headless-friendly)

For a machine that runs 24/7 under systemd, use **OAuth with the Device Grant Flow**. You sign in once from a phone or laptop via a link printed in the terminal; tokens are stored automatically and refreshed in the background.

**First-time setup (SSH on your server is fine):**

```bash
cd ~/webex-elgato
./webex-elgato-login.sh setup
```

The wizard will:

1. Print a checklist for creating a Webex Integration in the [Developer Portal](https://developer.webex.com/my-apps)  
2. Prompt for **Client ID** and **Client Secret** (saved to `~/.config/webex-elgato/credentials.json`, mode `600`)  
3. Print a **clickable link** — open it on any device, approve Webex, and wait for confirmation  
4. Save access and refresh tokens to `~/.config/webex-elgato/tokens.json` (mode `600`)

Example output during login:

```text
Open this link on your phone or laptop (valid 5 minutes):
  https://oauth-helper-r.wbx2.com/verify?userCode=...

Or go to https://oauth-helper-r.wbx2.com/verify and enter code: 729703

Waiting for you to approve in the browser...

Webex authorization successful. Tokens saved to:
  /home/you/.config/webex-elgato/tokens.json

Next: systemctl --user restart webex-elgato.service
```

**Portal checklist** (also printed by `setup`):

1. [My Apps](https://developer.webex.com/my-apps) → **Create an Integration** (e.g. name: `webex-elgato-home`)  
2. Add **all four** Redirect URIs (Webex may use `d` as well as `a` / `k` / `r`):

   ```
   https://oauth-helper-a.wbx2.com/helperservice/v1/actions/device/callback
   https://oauth-helper-d.wbx2.com/helperservice/v1/actions/device/callback
   https://oauth-helper-k.wbx2.com/helperservice/v1/actions/device/callback
   https://oauth-helper-r.wbx2.com/helperservice/v1/actions/device/callback
   ```

3. **Scopes** — enable **`spark:all`**. If login still fails with “Scope is invalid”, also enable **`spark:kms`** (your integration may require both). Do not enable both `spark:all` and `spark:people_read`.
4. Copy **Client ID** and **Client Secret** (secret shown once)

**Re-authenticate** when the refresh token expires (~90 days without use) or is revoked:

```bash
./webex-elgato-login.sh login
systemctl --user restart webex-elgato.service
```

**Check auth status:**

```bash
./webex-elgato-login.sh status
```

| File | Contents |
|------|----------|
| `~/.config/webex-elgato/credentials.json` | Integration Client ID + Secret |
| `~/.config/webex-elgato/tokens.json` | Access + refresh tokens (auto-updated) |

The monitor refreshes the access token automatically before it expires (~14 days). You do not edit token values by hand.

#### Who to poll (People API)

With OAuth, the script uses [`GET /people/me`](https://developer.webex.com/docs/api/v1/people/get-my-own-details) for the user who approved the integration. To poll someone else, set **one** of:

1. **`WEBEX_PERSON_ID`** — [`GET /people/{personId}`](https://developer.webex.com/docs/api/v1/people/get-person-details) (requires appropriate admin scopes on the integration)  
2. **`WEBEX_EMAIL`** — [`GET /people?email=…`](https://developer.webex.com/docs/api/v1/people/list-people)  
3. **Neither** — `/people/me` (default)

In `constants.py`, the same fields are **`user_id`** (maps to `WEBEX_PERSON_ID`), **`email`**, or omit both for `/me`.

### Alternative: personal access token (quick tests only)

Personal tokens from the Developer Portal expire **12 hours** after you sign in. Not suitable for systemd.

```bash
export WEBEX_ACCESS_TOKEN="your_personal_access_token"
python3 elgato-webex-auto.py
```

If OAuth token files exist, they take precedence over `WEBEX_ACCESS_TOKEN`.

### Alternative: `constants.py`

Copy the example and edit locally (this file is **gitignored** so it is not committed by default):

```bash
cp constants.py.example constants.py
python3 elgato-webex-auto.py
```

Environment variables **override** values in `constants.py` when both are set.

### Optional tuning

| Variable | Description | Default |
|----------|-------------|---------|
| `WEBEX_ELGATO_POLL_SECONDS` | Delay between Webex polls (seconds) | `10` |
| `WEBEX_ELGATO_DISCOVER_SECONDS` | mDNS discovery timeout for Key Light | `2` |
| `WEBEX_ELGATO_DISCOVER_RETRY_SECONDS` | Minimum delay between mDNS scans when lights are missing | `60` |
| `WEBEX_ELGATO_OFF_AFTER_POLLS` | Consecutive “not in meeting” polls before turning lights off | `3` |
| `WEBEX_CLIENT_ID` / `WEBEX_CLIENT_SECRET` | Override integration credentials (advanced) | from `credentials.json` |
| `WEBEX_OAUTH_SCOPE` | OAuth scope at login (must match integration) | `spark:all` |

## Run on Linux with systemd (user service)

Example unit and env templates are under [`systemd/`](systemd/).

1. **Env file** (optional tuning only after OAuth setup):

   ```bash
   install -m 600 systemd/webex-elgato.env.example ~/.config/webex-elgato.env
   ```

2. **OAuth setup** (once):

   ```bash
   cd ~/webex-elgato && ./webex-elgato-login.sh setup
   ```

3. **Service unit** — copy the example into the user unit directory, then adjust paths if your clone is not `$HOME/webex-elgato`:

   ```bash
   mkdir -p ~/.config/systemd/user
   cp systemd/webex-elgato.service.example ~/.config/systemd/user/webex-elgato.service
   ${EDITOR:-nano} ~/.config/systemd/user/webex-elgato.service
   ```

4. **Enable and inspect logs**:

   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now webex-elgato.service
   journalctl --user -u webex-elgato.service -f
   ```

   Under systemd, presence is logged as plain text when it changes (no spinner blobs).

By default, **user** units stop when your last login session ends. **`loginctl enable-linger`** keeps your user services running at boot without an interactive login:

```bash
loginctl enable-linger "$USER"
```

## Security notes

- Treat OAuth credentials and tokens like passwords: **do not** commit them, paste them into issues, or share screen shots that include them.  
- Token files are written with mode **`600`** under `~/.config/webex-elgato/`.  
- If credentials were exposed, revoke the integration in the Webex developer portal and run `./webex-elgato-login.sh setup` again.  

## Troubleshooting

| Symptom | Things to check |
|--------|------------------|
| 401 from Webex | Run `./webex-elgato-login.sh login` and restart the service; or check `./webex-elgato-login.sh status`. |
| `redirect_uri_mismatch` during login | Add all four OAuth helper Redirect URIs in the portal (especially the `-d` URL). |
| `Scope is invalid` during login | Enable **`spark:all`** on the integration (and **`spark:kms`** if needed). Re-run `./webex-elgato-login.sh login` — the script auto-detects common scope combinations. Override manually with `--scope 'spark:kms spark:all'`. |
| Service exits: “No Webex authentication configured” | Run `./webex-elgato-login.sh setup`. |
| `[237B blob data]` in journal | Harmless on older runs; current version logs plain `presence: …` lines under systemd. |
| `Too many open files` / asyncio errors | Fixed in current code (zeroconf browser cleanup). Restart the service after updating; if the light was offline for days, discovery now backs off to once per 60s. |
| Lights never turn on | Key Light powered on, same subnet/VLAN as this host, mDNS not blocked; try increasing `WEBEX_ELGATO_DISCOVER_SECONDS`. |
| Status never “meeting” | For `/me`, you must approve OAuth as that user. For email/person id, scopes and ids must be correct. |
| Lights flicker | Increase `WEBEX_ELGATO_OFF_AFTER_POLLS` or `WEBEX_ELGATO_POLL_SECONDS`. |

## License

Copyright © 2022–2026 **Emmanuel Tychon**. This project is released under the [MIT License](LICENSE).
