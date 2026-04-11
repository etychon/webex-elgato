# webex-elgato

Small Python utility that watches **Webex presence** and toggles **Elgato Key Light** devices on the local network: lights turn on when Webex reports an active meeting-style state, and turn off after a short run of “not in meeting” polls (debounced to avoid flicker).

Presence comes from the [Webex People API](https://developer.webex.com/docs/api/v1/people), so it can follow the same user across desk phone, desktop app, mobile, or room endpoints, depending on how Webex attributes status.

Typical uses:

- Automatic key / fill light when on camera  
- Simple “on air” or “do not disturb” cue for people nearby  

## Requirements

- **Python 3** (3.8+ recommended)  
- **Network**: outbound HTTPS to `webexapis.com`, and local LAN access to Elgato Key Light (Bonjour / mDNS discovery)  
- **Webex**: a [personal access token](https://developer.webex.com/docs/getting-started) and the Webex **email** used for the People lookup  
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

## Configure

### Recommended: environment variables

Keeps secrets out of the repo and out of shell history if paired with a systemd `EnvironmentFile` (see below).

```bash
export WEBEX_ACCESS_TOKEN="your_personal_access_token"
export WEBEX_EMAIL="your.webex.login@example.com"
python3 elgato-webex-auto.py
```

Create and refresh tokens from the Webex developer portal ([Getting started](https://developer.webex.com/docs/getting-started)). If the script logs **HTTP 401**, the token is missing, wrong, or expired—issue a new token and update the environment (or env file).

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

2. **Service unit** — copy the example into the user unit directory, then set `WorkingDirectory` and `ExecStart` to match this repo’s path on the machine (the template assumes `$HOME/webex-elgato`; adjust `%h/...` paths as needed):

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

User services normally stop when the graphical session ends. To keep the service running after logout (optional, common on workstations that stay powered on):

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
| Status never “meeting” | Email in `WEBEX_EMAIL` must match the Webex identity whose presence is returned by the People API for your token. |
| Lights flicker | Increase `WEBEX_ELGATO_OFF_AFTER_POLLS` or `WEBEX_ELGATO_POLL_SECONDS`. |

## License

Copyright © 2022–2026 **Emmanuel Tychon**. This project is released under the [MIT License](LICENSE).
