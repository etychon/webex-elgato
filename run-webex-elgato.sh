#!/bin/sh
# Run the monitor with this repo's .venv (systemd-friendly entrypoint).
set -ef
ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
PY="$ROOT/.venv/bin/python"
MAIN="$ROOT/elgato-webex-auto.py"

if ! test -x "$PY"; then
	printf '%s\n' "webex-elgato: missing $PY" >&2
	printf '%s\n' "  Create it: cd \"$ROOT\" && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
	exit 1
fi
if ! "$PY" -c "import zeroconf, leglight" >/dev/null 2>&1; then
	printf '%s\n' "webex-elgato: venv at $PY lacks dependencies (e.g. zeroconf)." >&2
	printf '%s\n' "  Install: cd \"$ROOT\" && .venv/bin/pip install -r requirements.txt" >&2
	exit 1
fi
exec "$PY" "$MAIN"
