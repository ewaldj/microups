#!/usr/bin/env bash
#
# Backup-Skript: ora1.jeitler.cc -> lokaler Mac
# Läuft AUF DEM MAC, verbindet sich ausgehend per SSH zum Server (rein Pull, kein Zugriff auf den Mac nötig).
#
# Voraussetzung auf dem Server:
#   - SSH-Key-Login für User "ubuntu" eingerichtet
#   - passwortloses sudo für rsync, mysqldump/pg_dumpall etc., z.B. über
#     /etc/sudoers.d/backup:
#       ubuntu ALL=(root) NOPASSWD: /usr/bin/rsync, /usr/bin/dpkg, /usr/bin/apt-mark,
#                                    /usr/sbin/ufw, /usr/sbin/iptables, /usr/bin/mysqldump,
#                                    /usr/bin/pg_dumpall, /usr/bin/crontab
#
set -euo pipefail

### ---- Konfiguration ----
REMOTE_USER="ubuntu"
REMOTE_HOST="ora1.jeitler.cc"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"

BASE_DIR="/Users/jeitler/90_BACKUP/ORA1-JEITLER-CC"
DATE_STAMP="$(date +%F)"

# Welche Verzeichnisse per rsync gesichert werden
RSYNC_PATHS=(
  "/etc/"
  "/home/"
  "/data/"
  "/var/www/"
  "/old-debian/"
)

RSYNC_OPTS=(-avz --delete --inplace -e ssh --rsync-path="sudo rsync")

# Datenbanken die gedumpt werden sollen (auf "true" setzen falls vorhanden)
BACKUP_MYSQL=false
BACKUP_POSTGRES=false

### ---- Verzeichnisstruktur anlegen ----
mkdir -p "${BASE_DIR}/meta" "${BASE_DIR}/db"
LOG_FILE="${BASE_DIR}/meta/backup-${DATE_STAMP}.log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

log "=== Backup gestartet: ${REMOTE} ==="

### ---- 1. Dateisystem-Sync per rsync ----
for path in "${RSYNC_PATHS[@]}"; do
  target_subdir="${path#/}"
  target_subdir="${target_subdir%/}"
  target="${BASE_DIR}/${target_subdir}/"
  mkdir -p "${target}"
  log "rsync ${REMOTE}:${path} -> ${target}"
  if rsync "${RSYNC_OPTS[@]}" "${REMOTE}:${path}" "${target}" >> "${LOG_FILE}" 2>&1; then
    log "  OK: ${path}"
  else
    log "  FEHLER bei rsync von ${path} (siehe Log) - Skript läuft weiter"
  fi
done

### ---- 2. Paketlisten ----
log "Paketlisten sichern..."
ssh "${REMOTE}" 'dpkg --get-selections' > "${BASE_DIR}/meta/dpkg-selections.txt" 2>>"${LOG_FILE}" || log "  FEHLER: dpkg-selections"
ssh "${REMOTE}" 'apt-mark showmanual' > "${BASE_DIR}/meta/apt-manual-packages.txt" 2>>"${LOG_FILE}" || log "  FEHLER: apt-manual-packages"

### ---- 3. Disk-Layout / Mounts ----
log "Disk-Layout sichern..."
ssh "${REMOTE}" 'echo "== lsblk =="; lsblk; echo; echo "== df -h =="; df -h; echo; echo "== fstab =="; cat /etc/fstab' \
  > "${BASE_DIR}/meta/disk-layout.txt" 2>>"${LOG_FILE}" || log "  FEHLER: disk-layout"

### ---- 4. Netzwerk & Firewall ----
log "Netzwerkkonfiguration sichern..."
ssh "${REMOTE}" 'echo "== ip a =="; ip a; echo; echo "== ufw status =="; sudo ufw status verbose 2>/dev/null; echo; echo "== iptables =="; sudo iptables -L -n -v 2>/dev/null' \
  > "${BASE_DIR}/meta/network.txt" 2>>"${LOG_FILE}" || log "  FEHLER: network"

### ---- 5. Cronjobs & systemd-Timer ----
log "Cronjobs sichern..."
ssh "${REMOTE}" 'for u in $(cut -f1 -d: /etc/passwd); do echo "== $u =="; sudo crontab -u "$u" -l 2>/dev/null; done' \
  > "${BASE_DIR}/meta/crontabs.txt" 2>>"${LOG_FILE}" || log "  FEHLER: crontabs"

ssh "${REMOTE}" 'systemctl list-timers --all' \
  > "${BASE_DIR}/meta/systemd-timers.txt" 2>>"${LOG_FILE}" || log "  FEHLER: systemd-timers"

### ---- 6. Installierte systemd-Services (nur enabled, zur Übersicht) ----
log "Aktive systemd-Services sichern..."
ssh "${REMOTE}" 'systemctl list-unit-files --state=enabled' \
  > "${BASE_DIR}/meta/systemd-enabled-services.txt" 2>>"${LOG_FILE}" || log "  FEHLER: systemd-enabled-services"

### ---- 7. Hostname / Machine-ID / OS-Version (zur Doku, NICHT blind restoren) ----
log "System-Identität dokumentieren..."
ssh "${REMOTE}" 'echo "== hostname =="; hostname; echo; echo "== machine-id =="; cat /etc/machine-id; echo; echo "== os-release =="; cat /etc/os-release' \
  > "${BASE_DIR}/meta/system-identity.txt" 2>>"${LOG_FILE}" || log "  FEHLER: system-identity"

### ---- 8. Docker (falls vorhanden) ----
log "Docker-Status sichern (falls installiert)..."
ssh "${REMOTE}" 'command -v docker >/dev/null 2>&1 && { echo "== containers =="; sudo docker ps -a; echo; echo "== images =="; sudo docker images; echo; echo "== volumes =="; sudo docker volume ls; } || echo "docker nicht installiert"' \
  > "${BASE_DIR}/meta/docker-status.txt" 2>>"${LOG_FILE}" || log "  FEHLER: docker-status"

### ---- 9. Datenbanken ----
if [ "${BACKUP_MYSQL}" = true ]; then
  log "MySQL-Dump wird erstellt..."
  ssh "${REMOTE}" 'sudo mysqldump --all-databases' \
    > "${BASE_DIR}/db/mysql-all-${DATE_STAMP}.sql" 2>>"${LOG_FILE}" \
    && log "  OK: MySQL-Dump" || log "  FEHLER: MySQL-Dump"
fi

if [ "${BACKUP_POSTGRES}" = true ]; then
  log "PostgreSQL-Dump wird erstellt..."
  ssh "${REMOTE}" 'sudo -u postgres pg_dumpall' \
    > "${BASE_DIR}/db/postgres-all-${DATE_STAMP}.sql" 2>>"${LOG_FILE}" \
    && log "  OK: PostgreSQL-Dump" || log "  FEHLER: PostgreSQL-Dump"
fi

### ---- Abschluss ----
log "=== Backup abgeschlossen ==="
log "Log-Datei: ${LOG_FILE}"

# Kurze Zusammenfassung der Fehler, falls vorhanden
if grep -q "FEHLER" "${LOG_FILE}"; then
  echo ""
  echo "!!! Es gab Fehler beim Backup - siehe ${LOG_FILE} !!!"
  grep "FEHLER" "${LOG_FILE}"
  exit 1
fi

exit 0