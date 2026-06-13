#!/bin/bash
# ================================================================
# pmtu-portable.sh — Path MTU Discovery via ICMP + PMTUD-Validierung
# Läuft unter Debian/Linux (iputils) UND macOS (BSD-Tools).
# Usage: bash pmtu-portable.sh <remote-IP> [interface]
# ================================================================

TARGET="${1}"
IFACE_ARG="${2:-}"

# ── OS-Erkennung ─────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
    Linux)  PLATFORM="linux" ;;
    Darwin) PLATFORM="macos" ;;
    *)      echo "Nicht unterstütztes OS: $OS"; exit 1 ;;
esac

# ── Farben ───────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'
CYN='\033[0;36m'; BLD='\033[1m';    RST='\033[0m'
GRY='\033[2;37m'; MGN='\033[0;35m'

# ── Konstanten ───────────────────────────────────────────────────
PINGS_NORMAL=3
PINGS_ADAPTIVE=6
THRESHOLD_OK=2
THRESHOLD_ADAPTIVE=1
TIMEOUT=2            # Sekunden pro Ping-Antwort
MIN_MTU=576
PING_IFACE=""        # gefüllt nach Plattform

# ── Hilfsfunktionen Darstellung ──────────────────────────────────
hdr() {
    local TITLE="$1"
    echo ""
    echo -e "${BLD}${MGN}── ${TITLE} ${RST}${GRY}$(printf '%0.s─' $(seq 1 $((52 - ${#TITLE}))))${RST}"
}
ok()   { echo -e "  ${GRN}✓${RST}  $*"; }
fail() { echo -e "  ${RED}✗${RST}  $*"; }
warn() { echo -e "  ${YLW}⚠${RST}  $*"; }
info() { echo -e "  ${GRY}→${RST}  $*"; }
row() {
    local LABEL="$1" VAL="$2" COLOR="${3:-$RST}"
    printf "  %-42s ${COLOR}${BLD}%s${RST}\n" "$LABEL" "$VAL"
}

# ── Portable Regex-Extraktion (Ersatz für grep -P) ───────────────
# extract_after PATTERN < text   — gibt Wort nach PATTERN aus
received_count() {
    # robust für iputils ("3 received") und BSD ("3 packets received")
    echo "$1" | awk '
        /received/ {
            for (i=1;i<=NF;i++)
                if ($(i)=="received" || $(i)=="packets") { print $(i-1); exit }
        }'
}
loss_pct() {
    echo "$1" | sed -n 's/.*[, ]\([0-9][0-9]*\)\(\.[0-9]*\)*% packet loss.*/\1/p' | head -1
}

# ── Plattform-Abstraktion: PING mit DF-Bit ───────────────────────
# build_ping_cmd PAYLOAD COUNT  → setzt globales Array PING_CMD
build_ping_cmd() {
    local PAYLOAD=$1 COUNT=$2
    if [[ "$PLATFORM" == "linux" ]]; then
        # -M do = DF-Bit setzen, -W = Antwort-Timeout (s)
        PING_CMD=(ping -M do -s "$PAYLOAD" -c "$COUNT" -W "$TIMEOUT")
    else
        # macOS/BSD: -D = DF-Bit, -t = Gesamttimeout (s) als Annäherung
        PING_CMD=(ping -D -s "$PAYLOAD" -c "$COUNT" -t "$((TIMEOUT * COUNT + 2))")
    fi
    # Interface/Quelle anhängen (plattformabhängig in PING_IFACE_ARGS)
    [[ -n "${PING_IFACE_ARGS:-}" ]] && PING_CMD+=($PING_IFACE_ARGS)
    PING_CMD+=("$TARGET")
}

# einfacher Reachability-Ping (ohne DF)
reach_ping() {
    if [[ "$PLATFORM" == "linux" ]]; then
        ping -c 4 -W 2 ${PING_IFACE_ARGS:-} "$TARGET" 2>&1
    else
        ping -c 4 -t 6 ${PING_IFACE_ARGS:-} "$TARGET" 2>&1
    fi
}

# ── Cache-Flush (plattformabhängig, best effort) ─────────────────
flush_cache() {
    if [[ "$PLATFORM" == "linux" ]]; then
        ip route flush cache 2>/dev/null
        ip -s -s neigh flush all 2>/dev/null
        local OLD_EXP
        OLD_EXP=$(sysctl -n net.ipv4.route.mtu_expires 2>/dev/null || echo 600)
        sysctl -qw net.ipv4.route.mtu_expires=0 2>/dev/null
        sysctl -qw net.ipv4.route.mtu_expires="$OLD_EXP" 2>/dev/null
    else
        # macOS: PMTU steckt in der Routing-Tabelle. -f flusht alle Routen
        # (zu invasiv) → wir löschen gezielt die Host-Route, der Kernel
        # legt sie beim nächsten Paket neu an. Braucht root; sonst no-op.
        if [[ $EUID -eq 0 ]]; then
            route -n delete -host "$TARGET" 2>/dev/null
        fi
    fi
}

# ── Probe-Funktion ───────────────────────────────────────────────
probe() {
    local PAYLOAD=$1
    local RESULT RECEIVED

    flush_cache

    build_ping_cmd "$PAYLOAD" "$PINGS_NORMAL"
    RESULT=$( "${PING_CMD[@]}" 2>&1 )

    if echo "$RESULT" | grep -qiE "too long|frag needed|mtu=|unreachable|net unreachable|message too long"; then
        return 1
    fi

    RECEIVED=$(received_count "$RESULT"); RECEIVED=${RECEIVED:-0}

    if [[ "$RECEIVED" -ge "$THRESHOLD_OK" ]]; then
        return 0
    fi

    # Grenzfall → adaptiver Retry
    if [[ "$RECEIVED" -ge "$THRESHOLD_ADAPTIVE" ]]; then
        flush_cache
        build_ping_cmd "$PAYLOAD" "$PINGS_ADAPTIVE"
        RESULT=$( "${PING_CMD[@]}" 2>&1 )
        RECEIVED=$(received_count "$RESULT"); RECEIVED=${RECEIVED:-0}
        local THRESH_A=$(( PINGS_ADAPTIVE * 67 / 100 ))
        [[ "$RECEIVED" -ge "$THRESH_A" ]] && return 0
        return 2
    fi
    return 1
}

# ── Argumente prüfen ─────────────────────────────────────────────
if [[ -z "$TARGET" ]]; then
    echo -e "${RED}Usage: $0 <remote-IP> [interface]${RST}"
    echo    "  Beispiele:"
    echo    "    $0 1.1.1.1"
    echo    "    $0 10.180.0.101 tun0"
    exit 1
fi

echo ""
echo -e "${BLD}${CYN}  Path MTU Discovery & PMTUD Validator v7.0-portable${RST}"
echo -e "  ${GRY}$(date '+%Y-%m-%d %H:%M:%S')  |  Plattform: ${PLATFORM}${RST}"
echo -e "  Ziel: ${BLD}${TARGET}${RST}   Pings/Test: ${BLD}${PINGS_NORMAL}${RST} (adaptiv: ${PINGS_ADAPTIVE})"

# ── Root-Hinweis (nur Linux zwingend für sysctl/neigh) ───────────
if [[ "$PLATFORM" == "linux" && $EUID -ne 0 ]]; then
    echo ""
    echo -e "  ${YLW}⚠${RST}  Root-Rechte empfohlen (sysctl + neigh flush)"
    echo -e "  ${GRY}→  Starte mit sudo neu ...${RST}"
    echo ""
    exec sudo bash "$0" "$@"
elif [[ "$PLATFORM" == "macos" && $EUID -ne 0 ]]; then
    echo ""
    info "Hinweis: ohne root kann die Host-Route nicht geflusht werden —"
    info "         macOS cached die PMTU pro Route. Für saubere Messung:"
    info "         ${BLD}sudo bash $0 $*${RST}"
fi

# ── Interface-Argument plattformgerecht aufbauen ─────────────────
if [[ -n "$IFACE_ARG" ]]; then
    if [[ "$PLATFORM" == "linux" ]]; then
        PING_IFACE_ARGS="-I $IFACE_ARG"
    else
        # macOS: -b bindet ans Interface (verfügbar ab neueren Versionen),
        # Fallback auf -S mit Quell-IP des Interfaces.
        if ping -b "$IFACE_ARG" -c1 -t1 "$TARGET" &>/dev/null; then
            PING_IFACE_ARGS="-b $IFACE_ARG"
        else
            SRC_OF_IFACE=$(ifconfig "$IFACE_ARG" 2>/dev/null | awk '/inet /{print $2; exit}')
            [[ -n "$SRC_OF_IFACE" ]] && PING_IFACE_ARGS="-S $SRC_OF_IFACE"
        fi
    fi
fi

# ── 1: Erreichbarkeit ────────────────────────────────────────────
hdr "1/6  Erreichbarkeit & Latenz"

REACH=$(reach_ping)
if ! echo "$REACH" | grep -q "bytes from"; then
    fail "Ziel ${TARGET} nicht erreichbar — Abbruch."
    exit 1
fi

# RTT-Zeile: Linux "rtt min/avg/max/mdev = a/b/c/d ms"
#            macOS "round-trip min/avg/max/stddev = a/b/c/d ms"
RTT_LINE=$(echo "$REACH" | grep -iE "min/avg/max")
RTT_MIN=$(echo "$RTT_LINE" | awk -F'= ' '{print $2}' | awk -F'/' '{printf "%.2f",$1}')
RTT_AVG=$(echo "$RTT_LINE" | awk -F'= ' '{print $2}' | awk -F'/' '{printf "%.2f",$2}')
RTT_MAX=$(echo "$RTT_LINE" | awk -F'= ' '{print $2}' | awk -F'/' '{printf "%.2f",$3}')
PKT_LOSS=$(loss_pct "$REACH")

ok "Erreichbar  |  RTT min/avg/max: ${RTT_MIN:-?} / ${RTT_AVG:-?} / ${RTT_MAX:-?} ms"
if [[ "${PKT_LOSS:-0}" -gt 0 ]]; then
    warn "Bereits ${PKT_LOSS}% Paketverlust im Basis-Test — Ergebnisse können unscharf sein"
else
    ok "Kein Paketverlust im Basis-Test"
fi

# ── 2: Interface & lokale MTU ────────────────────────────────────
hdr "2/6  Lokale Interface-MTU"

if [[ "$PLATFORM" == "linux" ]]; then
    if [[ -n "$IFACE_ARG" ]]; then IFACE="$IFACE_ARG"
    else IFACE=$(ip route get "$TARGET" 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1); fi
    LOCAL_MTU=$(ip link show "$IFACE" 2>/dev/null | sed -n 's/.* mtu \([0-9]*\).*/\1/p')
    GW=$(ip route get "$TARGET" 2>/dev/null | sed -n 's/.* via \([^ ]*\).*/\1/p' | head -1)
    SRC_IP=$(ip route get "$TARGET" 2>/dev/null | sed -n 's/.* src \([^ ]*\).*/\1/p' | head -1)
else
    if [[ -n "$IFACE_ARG" ]]; then IFACE="$IFACE_ARG"
    else IFACE=$(route -n get "$TARGET" 2>/dev/null | awk '/interface:/{print $2}'); fi
    LOCAL_MTU=$(ifconfig "$IFACE" 2>/dev/null | awk '/mtu/{for(i=1;i<=NF;i++) if($i=="mtu") print $(i+1)}' | head -1)
    GW=$(route -n get "$TARGET" 2>/dev/null | awk '/gateway:/{print $2}')
    SRC_IP=$(ifconfig "$IFACE" 2>/dev/null | awk '/inet /{print $2; exit}')
fi
LOCAL_MTU=${LOCAL_MTU:-1500}

ok "Interface: ${BLD}${IFACE}${RST}  |  MTU: ${BLD}${LOCAL_MTU}${RST} Bytes"
[[ -n "$GW" ]]     && info "Gateway  : ${GW}"
[[ -n "$SRC_IP" ]] && info "Source IP: ${SRC_IP}"

# ── 3: PMTUD-Funktionstest ───────────────────────────────────────
hdr "3/6  PMTUD-Funktionstest (ICMP DF-Bit)"
PMTUD_STATUS="UNBEKANNT"

build_ping_cmd 548 3
if "${PING_CMD[@]}" &>/dev/null; then
    ok "DF-Bit klein  (576B  / payload 548B):  ${GRN}OK${RST}"
else
    fail "DF-Bit klein  (576B  / payload 548B):  FEHLER"
fi

OVER_PAYLOAD=$(( LOCAL_MTU - 28 + 100 ))
build_ping_cmd "$OVER_PAYLOAD" 3
OVER_RESULT=$( "${PING_CMD[@]}" 2>&1 )

if echo "$OVER_RESULT" | grep -qiE "too long|frag needed|mtu=|message too long"; then
    ok "DF-Bit oversized: ICMP Type 3 Code 4 ${GRN}empfangen${RST} — PMTUD funktionsfähig"
    PMTUD_STATUS="FUNKTIONIERT"
elif echo "$OVER_RESULT" | grep -q "bytes from"; then
    warn "DF-Bit oversized: Paket kam an trotz überschrittener MTU"
    info "Kernel/NIC-Offload (TSO/GSO) fragmentiert trotz DF-Bit — PMTUD umgangen"
    PMTUD_STATUS="OFFLOAD_BYPASS"
else
    warn "DF-Bit oversized: kein Echo und kein ICMP Type 3 Code 4 zurück"
    info "ICMP Type 3 Code 4 wird im Pfad gefiltert (Firewall / Service Provider)"
    info "Bedeutung: Bei echter PMTUD-Nutzung entsteht ein 'Black Hole'"
    info "           → große TCP-Segmente werden am Engpass still gedroppt,"
    info "             der Sender bekommt kein Signal zur Reduktion der MSS"
    info "           → TCP hängt, kleine Pakete (ACK, SSH) laufen,"
    info "             große (HTTP-Body, Bulk-Transfer) nie ankommen"
    info "Empfehlung: MSS-Clamp fix konfigurieren, nicht auf PMTUD verlassen"
    PMTUD_STATUS="ICMP_GEFILTERT"
fi

# ── 4: Binäre Suche ──────────────────────────────────────────────
hdr "4/6  Binäre Suche Path-MTU"
info "Suchbereich: ${MIN_MTU} – ${LOCAL_MTU} Bytes  |  Threshold: ${THRESHOLD_OK}/${PINGS_NORMAL} Pakete"
echo ""

LOW=$MIN_MTU
# HIGH eins über die lokale MTU, damit MID == LOCAL_MTU getestet werden
# kann. Sonst wird die obere Grenze nur angenähert (1499 statt 1500) und
# ein engpassfreier Pfad meldet fälschlich 1 Byte zu wenig.
HIGH=$(( LOCAL_MTU + 1 ))
ITERATIONS=0
UNCERTAIN_STEPS=()

while [[ $(( HIGH - LOW )) -gt 1 ]]; do
    MID=$(( (LOW + HIGH) / 2 ))
    PAYLOAD=$(( MID - 28 ))
    ITERATIONS=$(( ITERATIONS + 1 ))

    probe "$PAYLOAD"
    RC=$?

    case $RC in
        0) STATUS="${GRN}✓ OK${RST}";                      LOW=$MID  ;;
        1) STATUS="${RED}✗ DROP${RST}";                    HIGH=$MID ;;
        2) STATUS="${YLW}? UNSICHER (adaptiv→DROP)${RST}"; HIGH=$MID
           UNCERTAIN_STEPS+=($MID) ;;
    esac

    printf "  Test %2d:  MTU %4d B  (payload %4d B)  —  %b\n" \
           "$ITERATIONS" "$MID" "$PAYLOAD" "$STATUS"
done
PMTU=$LOW

# ── 5: Grenzwert-Verifikation ────────────────────────────────────
hdr "5/6  Grenzwert-Verifikation"
echo ""

VERIFY_OK_PAYLOAD=$(( PMTU - 28 ))
VERIFY_FAIL_PAYLOAD=$(( PMTU - 27 ))

# Sonderfall: PMTU == lokale MTU → der Pfad hat keinen Engpass, die
# Grenze liegt an unserem eigenen Interface. PMTU+1 zu testen würde nur
# das lokale NIC verletzen (sendto: Message too long), nicht den Pfad.
# Das ist KEIN Black Hole und wird separat gemeldet.
NO_BOTTLENECK=false
[[ "$PMTU" -ge "$LOCAL_MTU" ]] && NO_BOTTLENECK=true

V_OK_COUNT=0
for i in 1 2 3; do
    flush_cache
    build_ping_cmd "$VERIFY_OK_PAYLOAD" 3
    R=$( "${PING_CMD[@]}" 2>&1 )
    RX=$(received_count "$R"); RX=${RX:-0}
    [[ "$RX" -ge 2 ]] && V_OK_COUNT=$(( V_OK_COUNT + 1 ))
done

V_FAIL_COUNT=0
for i in 1 2 3; do
    flush_cache
    build_ping_cmd "$VERIFY_FAIL_PAYLOAD" 3
    R=$( "${PING_CMD[@]}" 2>&1 )
    RX=$(received_count "$R"); RX=${RX:-0}
    IS_ICMP=$(echo "$R" | grep -cE "too long|frag needed|unreachable|message too long")
    [[ "$RX" -le 1 || "${IS_ICMP:-0}" -ge 1 ]] && V_FAIL_COUNT=$(( V_FAIL_COUNT + 1 ))
done

if [[ "$V_OK_COUNT" -ge 2 ]]; then
    ok "MTU ${PMTU}B     payload ${VERIFY_OK_PAYLOAD}B:  ${GRN}stabil empfangen${RST}  (${V_OK_COUNT}/3)"
    VERIFY_OK=true
else
    warn "MTU ${PMTU}B     payload ${VERIFY_OK_PAYLOAD}B:  instabil (${V_OK_COUNT}/3) — Pfad hat Verlust"
    VERIFY_OK=false
fi

if $NO_BOTTLENECK; then
    ok "MTU $((PMTU+1))B   ${GRN}Pfad hat keinen Engpass${RST} — Path-MTU = lokale MTU (${LOCAL_MTU}B)"
    info "PMTU+1 würde nur das lokale Interface überschreiten, kein Pfad-Test nötig"
    VERIFY_FAIL=true
elif [[ "$V_FAIL_COUNT" -ge 2 ]]; then
    ok "MTU $((PMTU+1))B   payload ${VERIFY_FAIL_PAYLOAD}B:  ${GRN}korrekt geblockt${RST}  (${V_FAIL_COUNT}/3)"
    VERIFY_FAIL=true
else
    warn "MTU $((PMTU+1))B   payload ${VERIFY_FAIL_PAYLOAD}B:  unscharf (${V_FAIL_COUNT}/3) — Grenzwert ±1B"
    VERIFY_FAIL=false
fi

# Kernel-PMTU-Cache plattformabhängig
if [[ "$PLATFORM" == "linux" ]]; then
    KERNEL_PMTU=$(ip route get "$TARGET" 2>/dev/null | sed -n 's/.* mtu \([0-9]*\).*/\1/p' | head -1)
else
    KERNEL_PMTU=$(route -n get "$TARGET" 2>/dev/null | awk '/mtu:/{print $2}')
fi

# ── 6: Ergebnis ──────────────────────────────────────────────────
hdr "6/6  Ergebnis"
echo ""

MSS_BASE=$(( PMTU - 40 ))

if $VERIFY_OK && $VERIFY_FAIL && [[ ${#UNCERTAIN_STEPS[@]} -eq 0 ]]; then
    CONF_TXT="${GRN}HOCH${RST}"
elif $VERIFY_OK || $VERIFY_FAIL; then
    CONF_TXT="${YLW}MITTEL${RST}"
else
    CONF_TXT="${RED}NIEDRIG${RST}"
fi

case "$PMTUD_STATUS" in
    FUNKTIONIERT)   PMTUD_TXT="${GRN}funktionsfähig${RST}  (ICMP Type 3 Code 4 empfangen)" ;;
    ICMP_GEFILTERT) PMTUD_TXT="${YLW}ICMP Type 3/4 gefiltert${RST}  → Black-Hole-Risiko" ;;
    OFFLOAD_BYPASS) PMTUD_TXT="${YLW}NIC/Kernel Offload umgeht DF-Bit${RST}" ;;
    *)              PMTUD_TXT="${GRY}unbekannt${RST}" ;;
esac

row "Path-MTU (gemessen):"        "${PMTU} Bytes"
[[ -n "$KERNEL_PMTU" ]] && \
row "Path-MTU (Kernel-Cache):"    "${KERNEL_PMTU} Bytes"
echo -e "  $(printf '%-42s' 'Konfidenz:') ${CONF_TXT}"
echo -e "  $(printf '%-42s' 'PMTUD-Status:') ${PMTUD_TXT}"
row "Iterationen:"                "${ITERATIONS}"
echo ""

echo -e "  ${BLD}MSS-Empfehlungen  (ip tcp adjust-mss)${RST}"
echo -e "  ${GRY}$(printf '%0.s─' $(seq 1 52))${RST}"
mss_row() {
    local LABEL="$1" OVERHEAD=$2
    local MSS=$(( MSS_BASE - OVERHEAD ))
    local EXTRA=""
    [[ $MSS -lt 576 ]] && EXTRA="  ${RED}← unter IPv4-Minimum!${RST}"
    printf "  %-40s ${BLD}%4d Bytes${RST}%b\n" "$LABEL" "$MSS" "$EXTRA"
}
mss_row "Reines TCP/IP (kein Tunnel):"          0
mss_row "GRE (8B):"                             8
mss_row "GRE + MPLS 1 Label (12B):"            12
mss_row "GRE + MPLS 2 Labels (16B):"           16
mss_row "GRE + MPLS 3 Labels (20B):"           20
mss_row "GRE + IPsec ESP AES (46B):"           46
mss_row "GRE + IPsec ESP AES + MPLS 1L (50B):" 50
mss_row "MACsec (32B):"                        32
mss_row "MACsec + GRE (40B):"                  40
mss_row "VXLAN (50B):"                         50
mss_row "WireGuard (60B):"                     60

echo ""
echo -e "  ${GRY}Overhead-Referenz:  IP 20B  TCP 20B  GRE 8B  IPsec ESP ~38B"
echo -e "  MACsec 32B  MPLS/Label 4B  VXLAN 50B  WireGuard 60B${RST}"

echo ""
if [[ "$PMTUD_STATUS" != "FUNKTIONIERT" ]]; then
    warn "PMTUD nicht zuverlässig — ${BLD}MSS-Clamp fix setzen${RST} auf Tunnel-Interface"
fi
if [[ ${#UNCERTAIN_STEPS[@]} -gt 0 ]]; then
    warn "Unsichere Messpunkte: ${UNCERTAIN_STEPS[*]} — etwas konservativer MSS wählen"
fi
if [[ "${PKT_LOSS:-0}" -gt 5 ]]; then
    warn "Hoher Hintergrundverlust (${PKT_LOSS}%) — Messung bei stabilerem Pfad wiederholen"
fi

echo ""
info "Manuelle Verifikation:"
if [[ "$PLATFORM" == "linux" ]]; then
    echo    "    ping -M do -s ${VERIFY_OK_PAYLOAD} -c 10 ${TARGET}   # muss klappen"
    echo    "    ping -M do -s ${VERIFY_FAIL_PAYLOAD} -c 10 ${TARGET}  # muss scheitern"
else
    echo    "    ping -D -s ${VERIFY_OK_PAYLOAD} -c 10 ${TARGET}   # muss klappen"
    echo    "    ping -D -s ${VERIFY_FAIL_PAYLOAD} -c 10 ${TARGET}  # muss scheitern"
fi
echo ""
