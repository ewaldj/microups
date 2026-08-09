#!/usr/bin/env bash
#
# Restore-Skript: lokaler Mac -> Server (ora1.jeitler.cc oder Ersatz-Server)
#
# Läuft AUF DEM MAC, verbindet sich ausgehend per SSH zum Zielserver.
#
# WICHTIG - bewusst KEIN "alles automatisch zurückspielen":
#   Ein Restore ist immer ein Moment, in dem man genau hinschauen sollte.
#   Dieses Skript fragt daher vor jedem Schritt nach, was du wirklich willst,
#   und zeigt dir die Meta-Infos an statt sie blind anzuwenden.
#
# Nutzung:
#   ./restore-ora1.sh                     # interaktiv, fragt Zielserver + Schritte ab
#   ./restore-ora1.sh --target neuer-server.example.com --dry-run
#
set -euo pipefail

BASE_DIR="/Users/jeitler/90_BACKUP/ORA1-JEITLER-CC"
REMOTE_USER="ubuntu"
DRY_RUN=false
TARGET_HOST=""

### ---- Argumente parsen ----
while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET_HOST="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help)
      echo "Usage: $0 [--target hostname] [--dry-run]"
      exit 0
      ;;
    *) echo "Unbekannte Option: $1"; exit 1 ;;
  esac
done

if [ -z "${TARGET_HOST}" ]; then
  read -rp "Ziel-Hostname/IP für den Restore (z.B. ora1.jeitler.cc oder neuer Server): " TARGET_HOST
fi

REMOTE="${REMOTE_USER}@${TARGET_HOST}"

echo ""
echo "=== Restore-Ziel: ${REMOTE} ==="
if [ "${DRY_RUN}" = true ]; then
  echo "(DRY-RUN: es wird nichts geschrieben, nur simuliert)"
fi
echo ""

confirm() {
  local prompt="$1"
  read -rp "${prompt} [j/N]: " answer
  [[ "${answer}" =~ ^[jJ]$ ]]
}

RSYNC_DRY_FLAG=""
if [ "${DRY_RUN}" = true ]; then
  RSYNC_DRY_FLAG="--dry-run"
fi

### ---- 0. Vorab: Meta-Infos zur Orientierung anzeigen ----
echo "----------------------------------------------------------------"
echo "Vor dem eigentlichen Restore: Referenz-Infos aus dem Backup ansehen?"
echo "(Diese werden NICHT automatisch angewendet - nur zur Orientierung,"
echo " damit du z.B. Partitionierung/Pakete manuell nachbauen kannst.)"
echo "----------------------------------------------------------------"
if confirm "System-Identität, Disk-Layout, Netzwerk, Paketliste anzeigen?"; then
  for f in system-identity.txt disk-layout.txt network.txt dpkg-selections.txt apt-manual-packages.txt crontabs.txt systemd-timers.txt systemd-enabled-services.txt docker-status.txt; do
    fpath="${BASE_DIR}/meta/${f}"
    if [ -f "${fpath}" ]; then
      echo ""
      echo "### ${f} ###"
      cat "${fpath}"
      echo ""
      read -rp "Weiter mit Enter..." _
    fi
  done
fi

### ---- 1. Pakete neu installieren (optional, manuell gegengeprüft) ----
if confirm "Paketliste auf dem Zielserver installieren (dpkg --set-selections + apt dselect-upgrade)?"; then
  echo "Kopiere Paketliste und wende sie an..."
  if [ "${DRY_RUN}" = false ]; then
    scp "${BASE_DIR}/meta/dpkg-selections.txt" "${REMOTE}:/tmp/dpkg-selections.txt"
    ssh "${REMOTE}" '
      sudo dpkg --set-selections < /tmp/dpkg-selections.txt &&
      sudo apt-get update &&
      sudo apt-get dselect-upgrade -y
    '
  else
    echo "[dry-run] würde dpkg-selections übertragen und apt dselect-upgrade ausführen"
  fi
fi

### ---- 2. /etc zurückspielen ----
echo ""
echo "ACHTUNG bei /etc: enthält u.a. ssh_host_*, machine-id, hostname, fstab."
echo "Bei einem NEUEN Server willst du diese evtl. NICHT 1:1 übernehmen,"
echo "damit der Server eine eigene Identität behält (sonst SSH host-key Konflikte etc.)."
if confirm "/etc zurückspielen?"; then
  EXCLUDES=()
  if confirm "  -> ssh_host_*, machine-id, hostname, fstab dabei AUSSCHLIESSEN (empfohlen bei neuem Server)?"; then
    EXCLUDES=(--exclude="ssh/ssh_host_*" --exclude="machine-id" --exclude="hostname" --exclude="fstab")
  fi
  rsync -avz ${RSYNC_DRY_FLAG} -e ssh --rsync-path="sudo rsync" \
    "${EXCLUDES[@]}" \
    "${BASE_DIR}/etc/" "${REMOTE}:/etc/"
fi

### ---- 3. /home zurückspielen ----
if confirm "/home zurückspielen?"; then
  rsync -avz ${RSYNC_DRY_FLAG} -e ssh --rsync-path="sudo rsync" \
    "${BASE_DIR}/home/" "${REMOTE}:/home/"
fi

### ---- 4. /data zurückspielen ----
if confirm "/data zurückspielen?"; then
  rsync -avz ${RSYNC_DRY_FLAG} -e ssh --rsync-path="sudo rsync" \
    "${BASE_DIR}/data/" "${REMOTE}:/data/"
fi

### ---- 5. /var/www zurückspielen ----
if confirm "/var/www zurückspielen?"; then
  rsync -avz ${RSYNC_DRY_FLAG} -e ssh --rsync-path="sudo rsync" \
    "${BASE_DIR}/var/www/" "${REMOTE}:/var/www/"
fi

### ---- 6. /old-debian zurückspielen ----
if confirm "/old-debian zurückspielen?"; then
  rsync -avz ${RSYNC_DRY_FLAG} -e ssh --rsync-path="sudo rsync" \
    "${BASE_DIR}/old-debian/" "${REMOTE}:/old-debian/"
fi

### ---- 7. Datenbanken einspielen ----
LATEST_MYSQL=$(ls -t "${BASE_DIR}/db/"mysql-all-*.sql 2>/dev/null | head -n1 || true)
if [ -n "${LATEST_MYSQL}" ]; then
  if confirm "MySQL-Dump einspielen (${LATEST_MYSQL})?"; then
    if [ "${DRY_RUN}" = false ]; then
      scp "${LATEST_MYSQL}" "${REMOTE}:/tmp/mysql-restore.sql"
      ssh "${REMOTE}" 'sudo mysql < /tmp/mysql-restore.sql'
    else
      echo "[dry-run] würde ${LATEST_MYSQL} nach ${REMOTE} übertragen und einspielen"
    fi
  fi
fi

LATEST_PG=$(ls -t "${BASE_DIR}/db/"postgres-all-*.sql 2>/dev/null | head -n1 || true)
if [ -n "${LATEST_PG}" ]; then
  if confirm "PostgreSQL-Dump einspielen (${LATEST_PG})?"; then
    if [ "${DRY_RUN}" = false ]; then
      scp "${LATEST_PG}" "${REMOTE}:/tmp/pg-restore.sql"
      ssh "${REMOTE}" 'sudo -u postgres psql -f /tmp/pg-restore.sql'
    else
      echo "[dry-run] würde ${LATEST_PG} nach ${REMOTE} übertragen und einspielen"
    fi
  fi
fi

echo ""
echo "=== Restore-Durchlauf beendet ==="
echo "Empfehlung: Danach Server neu starten (Netzwerk/SSH-Keys/Dienste neu laden)"
echo "und Funktionsfähigkeit prüfen (Webserver, Datenbank, Login)."