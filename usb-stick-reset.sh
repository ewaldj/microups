#!/bin/bash
# ============================================================
#  USB Disk Reset Tool für macOS
#  - Überschreibt MBR/GPT/Partitionstabelle mit dd (zeros)
#  - Formatiert neu mit gewähltem Dateisystem
#  - Optionale Verifikation + f3probe Fake-Stick-Test
#
#  Nutzung: sudo bash usb-reset.sh
# ============================================================

RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
CYN='\033[0;36m'
BLD='\033[1m'
RST='\033[0m'

sep() { echo -e "${BLU}────────────────────────────────────────────────────${RST}"; }
ok()  { echo -e "${GRN}  ✓ $*${RST}"; }
err() { echo -e "${RED}  ✗ $*${RST}"; }
inf() { echo -e "${CYN}  → $*${RST}"; }
warn(){ echo -e "${YLW}  ⚠  $*${RST}"; }

clear
echo ""
echo -e "${BLD}  USB DISK RESET TOOL  |  macOS${RST}"
sep
echo ""

# ── Root-Check ───────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  err "Dieses Script benötigt sudo-Rechte."
  echo "  Starte neu mit: sudo bash $0"
  exit 1
fi

# ── Schritt 1: Laufwerke anzeigen ────────────────────────────
echo -e "${BLD}SCHRITT 1 – Verfügbare externe Laufwerke:${RST}"
echo ""
diskutil list external physical
echo ""
sep

# ── Schritt 2: Disk auswählen ────────────────────────────────
echo ""
echo -e "${BLD}SCHRITT 2 – Laufwerk wählen${RST}"
warn "NUR externe USB-Sticks wählen! Falsche Disk = Datenverlust."
echo ""
read -rp "  Disk-Identifier eingeben (z.B. disk2): " DISK

DISK_PATH="/dev/${DISK}"
RAW_DISK="/dev/r${DISK}"   # raw device = schneller für dd

# Existenz prüfen
if ! diskutil info "${DISK_PATH}" &>/dev/null; then
  err "Laufwerk ${DISK_PATH} nicht gefunden. Abbruch."
  exit 1
fi

# Interne Disk absichern
DISK_INFO=$(diskutil info "${DISK_PATH}")
IS_INTERNAL=$(echo "$DISK_INFO" | grep -i "Internal" | grep -i "Yes" || true)
if [[ -n "$IS_INTERNAL" ]]; then
  err "SICHERHEIT: ${DISK_PATH} ist eine interne Disk – Abbruch!"
  exit 1
fi

DISK_SIZE=$(echo "$DISK_INFO" | grep "Disk Size" | awk -F'[:(]' '{print $2}' | xargs)
echo ""
ok "Gewählt: ${DISK_PATH}  (${DISK_SIZE})"
sep

# ── Schritt 3: Dateisystem wählen ───────────────────────────
echo ""
echo -e "${BLD}SCHRITT 3 – Dateisystem wählen${RST}"
echo ""
echo "   1)  ExFAT   – Mac + Windows, keine Dateigrößenlimit  ${CYN}[empfohlen]${RST}"
echo "   2)  FAT32   – breite Kompatibilität, max. 4 GB/Datei"
echo "   3)  APFS    – nur macOS, sehr schnell"
echo "   4)  HFS+    – Mac OS Extended (Journaled)"
echo "   5)  NTFS    – Windows primär (macOS nur lesend)"
echo ""
read -rp "  Wahl [1-5, Enter = 1]: " FS_CHOICE

case "${FS_CHOICE}" in
  2) FS="FAT32"  ;;
  3) FS="APFS"   ;;
  4) FS="JHFS+"  ;;
  5) FS="NTFS"   ;;
  *) FS="ExFAT"  ;;
esac
ok "Dateisystem: ${FS}"

# ── Schritt 4: Label + Schema ────────────────────────────────
echo ""
read -rp "  Volume-Name [USBSTICK]: " LABEL
LABEL="${LABEL:-USBSTICK}"

echo ""
echo -e "${BLD}  Partitionsschema:${RST}"
echo "   1)  MBR  – Master Boot Record  ${CYN}[Standard, empfohlen]${RST}"
echo "   2)  GPT  – GUID Partition Table (modern)"
read -rp "  Wahl [1-2, Enter = 1]: " SCHEME_CHOICE
SCHEME=$([[ "$SCHEME_CHOICE" == "2" ]] && echo "GPT" || echo "MBR")
ok "Schema: ${SCHEME}"
sep

# ── Schritt 5: DD-Größe wählen ───────────────────────────────
echo ""
echo -e "${BLD}SCHRITT 4 – DD Zero-Wipe (Partitionstabelle löschen)${RST}"
echo ""
echo "  Wie viele MB sollen am Anfang mit Nullen überschrieben werden?"
echo "   1)  10 MB   – reicht für MBR/GPT/Bootloader  ${CYN}[empfohlen, schnell]${RST}"
echo "   2)  50 MB   – extra-sicher bei hartnäckigen Strukturen"
echo "   3)  100 MB  – sehr gründlich"
echo "   4)  Komplett (gesamter Stick) – dauert lange!"
echo ""
read -rp "  Wahl [1-4, Enter = 1]: " DD_CHOICE

case "${DD_CHOICE}" in
  2) DD_COUNT=50;   DD_LABEL="50 MB"      ;;
  3) DD_COUNT=100;  DD_LABEL="100 MB"     ;;
  4) DD_COUNT=0;    DD_LABEL="vollständig";;
  *) DD_COUNT=10;   DD_LABEL="10 MB"      ;;
esac

# ── Zusammenfassung + Bestätigung ────────────────────────────
echo ""
sep
echo ""
echo -e "${BLD}  ZUSAMMENFASSUNG – Was jetzt passiert:${RST}"
echo ""
echo -e "  Laufwerk  :  ${RED}${DISK_PATH}${RST} (${DISK_SIZE})"
echo -e "  DD-Wipe   :  Erste ${DD_LABEL} mit /dev/zero überschreiben"
echo -e "  Format    :  ${FS}  |  Label: ${LABEL}  |  Schema: ${SCHEME}"
echo -e "  Verifikation folgt automatisch"
echo ""
warn "ALLE DATEN AUF ${DISK_PATH} WERDEN UNWIEDERBRINGLICH GELÖSCHT!"
echo ""
read -rp "  Tippe 'JA' zum Bestätigen (oder Enter zum Abbrechen): " CONFIRM

if [[ "${CONFIRM}" != "JA" ]]; then
  inf "Abgebrochen. Keine Änderungen vorgenommen."
  exit 0
fi

sep

# ── Schritt 6: Aushängen ─────────────────────────────────────
echo ""
echo -e "${BLD}[1/4] Laufwerk aushängen...${RST}"
if diskutil unmountDisk "${DISK_PATH}" 2>&1; then
  ok "Erfolgreich ausgehängt"
else
  warn "Aushängen teilweise fehlgeschlagen – fahre trotzdem fort"
fi

# ── Schritt 7: DD Zero-Wipe ──────────────────────────────────
echo ""
echo -e "${BLD}[2/4] DD Zero-Wipe läuft...${RST}"
inf "Überschreibe ${DD_LABEL} auf ${RAW_DISK} mit /dev/zero"
echo ""

if [[ $DD_COUNT -eq 0 ]]; then
  # Gesamten Stick überschreiben
  if dd if=/dev/zero of="${RAW_DISK}" bs=1m 2>&1 | \
     grep -v "^$" | tail -5; then
    true  # dd gibt Fehler beim Erreichen des Endes – das ist normal
  fi
else
  dd if=/dev/zero of="${RAW_DISK}" bs=1m count="${DD_COUNT}" 2>&1
fi

echo ""
ok "DD Zero-Wipe abgeschlossen"

# Sync erzwingen
sync
sleep 1

# ── Schritt 8: Formatieren ───────────────────────────────────
echo ""
echo -e "${BLD}[3/4] Formatierung mit diskutil...${RST}"
inf "diskutil eraseDisk ${FS} ${LABEL} ${SCHEME} ${DISK_PATH}"
echo ""

if diskutil eraseDisk "${FS}" "${LABEL}" "${SCHEME}" "${DISK_PATH}"; then
  echo ""
  ok "Formatierung erfolgreich"
else
  echo ""
  err "Formatierung fehlgeschlagen!"
  echo ""
  inf "Versuche alternativen Weg über diskutil partitionDisk..."
  diskutil partitionDisk "${DISK_PATH}" 1 "${SCHEME}" "${FS}" "${LABEL}" 100%
fi

# ── Schritt 9: Verifikation ──────────────────────────────────
echo ""
echo -e "${BLD}[4/4] Disk-Verifikation...${RST}"

echo ""
inf "Prüfe Disk-Struktur..."
diskutil verifyDisk "${DISK_PATH}" && ok "Disk OK" || warn "Disk-Prüfung meldet Probleme"

echo ""
inf "Prüfe Volume..."
diskutil verifyVolume "${DISK_PATH}s1" 2>/dev/null && ok "Volume OK" || \
  inf "Volume-Prüfung übersprungen (bei APFS normal)"

# ── Ergebnis ─────────────────────────────────────────────────
sep
echo ""
echo -e "${BLD}  ERGEBNIS:${RST}"
echo ""
diskutil info "${DISK_PATH}" | grep -E "Device:|Disk Size|Volume Name|File System|Partition Type|Ejectable|Removable"
echo ""

REPORTED_SIZE=$(diskutil info "${DISK_PATH}" | grep "Disk Size" | awk -F'[:(]' '{print $2}' | xargs)
inf "Gemeldete Größe: ${REPORTED_SIZE}"

# ── Fake-Stick Warnung ───────────────────────────────────────
echo ""
echo -e "${BLD}  FAKE-STICK TEST (optional):${RST}"
echo ""
echo "  Wenn die Größe immer noch falsch ist, könnte es ein"
echo "  gefälschter Stick mit manipuliertem Controller sein."
echo ""
read -rp "  f3probe Fake-Test durchführen? (benötigt: brew install f3) [j/N]: " DO_F3

if [[ "${DO_F3}" == "j" || "${DO_F3}" == "J" ]]; then
  if command -v f3probe &>/dev/null; then
    echo ""
    inf "Starte f3probe – das dauert einige Minuten..."
    f3probe --destructive --time-ops "${DISK_PATH}"
  else
    warn "f3probe nicht installiert."
    inf "Installieren mit: brew install f3"
    inf "Dann manuell ausführen: sudo f3probe --destructive --time-ops ${DISK_PATH}"
  fi
fi

sep
echo ""
ok "USB Reset Tool abgeschlossen."
echo ""