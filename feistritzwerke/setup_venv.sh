#!/usr/bin/env bash
# setup_venv.sh - legt ein virtuelles Environment (.venv) neben diesem Script an
# und installiert alles, was feistritz_qh.py braucht. Die System-Python bleibt unberührt.
#
# Verwendung:
#   ./setup_venv.sh                 # venv anlegen + Pakete + Chromium installieren
#   source .venv/bin/activate       # venv in der aktuellen Shell aktivieren
#   ./feistritz_qh.py --von 07.05.2026 --bis 08.05.2026
#
# Hinweis: Ein Script kann die venv nicht in deiner laufenden Shell aktivieren
# (das geht nur mit "source"). Es aktiviert sie daher nur für die eigenen Installationsschritte.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
VENV_DIR=".venv"

# Python wählen: bevorzugt 3.11, sonst python3
PY=""
for c in python3.11 python3.12 python3.13 python3; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "Fehler: kein python3 gefunden." >&2; exit 1; }
echo "Verwende $($PY --version) ($(command -v "$PY"))"

if [ ! -d "$VENV_DIR" ]; then
    echo "Erzeuge venv in $VENV_DIR ..."
    "$PY" -m venv "$VENV_DIR"
else
    echo "venv $VENV_DIR existiert bereits - wird weiterverwendet."
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Chromium für Playwright (liegt im Playwright-Cache des Benutzers, nicht in der System-Python)
python -m playwright install chromium

echo
echo "Fertig. Aktivieren mit:"
echo "    source $VENV_DIR/bin/activate"
echo "Oder ohne Aktivierung direkt starten:"
echo "    $VENV_DIR/bin/python feistritz_qh.py --von 07.05.2026 --bis 08.05.2026"
