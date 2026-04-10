#!/bin/sh
# - - - - - - - - - - - - - - - - - - - - - - - -
# snmpv3_get_cpu_mem.sh by ewald@jeitler.cc 2025
# https://www.jeitler.guru 
# - - - - - - - - - - - - - - - - - - - - - - - -

set -eu

HOST=home.jeitler.guru
SNMP_USER=SNMP_RO
SNMP_AUTH_PROTO=SHA SNMP_AUTH_PASS='supersecure' 
SNMP_PRIV_PROTO=AES SNMP_PRIV_PASS='supersecure'

# ========= User config (per ENV änderbar) =========
HOST="${HOST:-192.168.1.10}"

SNMP_USER="${SNMP_USER:-SNMPUSER}"
SNMP_AUTH_PROTO="${SNMP_AUTH_PROTO:-SHA}"   # MD5 oder SHA
SNMP_AUTH_PASS="${SNMP_AUTH_PASS:-AUTH_PASS}"
SNMP_PRIV_PROTO="${SNMP_PRIV_PROTO:-AES}"   # AES oder DES
SNMP_PRIV_PASS="${SNMP_PRIV_PASS:-PRIV_PASS}"

TAB="$(printf '\t')"

# ========= OIDs =========
# CISCO-PROCESS-MIB (CPU)
CPM_BASE="1.3.6.1.4.1.9.9.109.1.1.1.1"
OID_cpmPhysIdx="${CPM_BASE}.2"   # cpmCPUTotalPhysicalIndex.<cpmIndex> -> entPhysicalIndex
OID_cpm5s="${CPM_BASE}.6"        # cpmCPUTotal5secRev.<cpmIndex>
OID_cpm1m="${CPM_BASE}.7"        # cpmCPUTotal1minRev.<cpmIndex>
OID_cpm5m="${CPM_BASE}.8"        # cpmCPUTotal5minRev.<cpmIndex>

# ENTITY-MIB
OID_entName="1.3.6.1.2.1.47.1.1.1.1.7"     # entPhysicalName.<entIdx>
OID_entDescr="1.3.6.1.2.1.47.1.1.1.1.2"    # entPhysicalDescr.<entIdx>

# CISCO-MEMORY-POOL-MIB (Memory)
MEM_BASE="1.3.6.1.4.1.9.9.48.1.1.1"
OID_memName="${MEM_BASE}.2"      # ciscoMemoryPoolName.<poolIndex>
OID_memUsed="${MEM_BASE}.5"      # ciscoMemoryPoolUsed.<poolIndex>   (Bytes)
OID_memFree="${MEM_BASE}.6"      # ciscoMemoryPoolFree.<poolIndex>   (Bytes)

# ========= SNMP helpers =========
SNMPWALK() {
  snmpwalk -v3 -t 60 -l authPriv -u "$SNMP_USER" -a "$SNMP_AUTH_PROTO" -A "$SNMP_AUTH_PASS" \
           -x "$SNMP_PRIV_PROTO" -X "$SNMP_PRIV_PASS" -On -Oqn "$HOST" "$@"
}
SNMPGET() {
  snmpget  -v3 -t 60 -l authPriv -u "$SNMP_USER" -a "$SNMP_AUTH_PROTO" -A "$SNMP_AUTH_PASS" \
           -x "$SNMP_PRIV_PROTO" -X "$SNMP_PRIV_PASS" -On -Oqv "$HOST" "$@"
}

# ========= Temp-Dateien =========
TMPDIR="$(mktemp -d -t cpmem.XXXXXX)"; trap 'rm -rf "$TMPDIR"' EXIT
CPU_PHYS="$TMPDIR/cpu_phys.tmp"
CPU_5S="$TMPDIR/cpu_5s.tmp"
CPU_1M="$TMPDIR/cpu_1m.tmp"
CPU_5M="$TMPDIR/cpu_5m.tmp"
ENT_MAP="$TMPDIR/ent_map.tsv"

MEM_NAME="$TMPDIR/mem_name.tmp"
MEM_USED="$TMPDIR/mem_used.tmp"
MEM_FREE="$TMPDIR/mem_free.tmp"

# ========= Helpers =========
# Parsen von Zeilen: ".<BASE>.<COL>.<index> <value>" -> "index <value>"
_extract_index_value() {
  base="$1"
  awk -v base="$base" '
  {
    oid=$1; val=$2;
    sub(/^\./,"",oid);
    pref=base ".";
    if (index(oid,pref)!=1) next;
    idx=substr(oid,length(pref)+1);
    print idx, val;
  }'
}

# ========= CPU: Werte einsammeln =========
SNMPWALK "$OID_cpmPhysIdx" 2>/dev/null | _extract_index_value "$OID_cpmPhysIdx" > "$CPU_PHYS" || true
SNMPWALK "$OID_cpm5s"     2>/dev/null | _extract_index_value "$OID_cpm5s"     > "$CPU_5S"   || true
SNMPWALK "$OID_cpm1m"     2>/dev/null | _extract_index_value "$OID_cpm1m"     > "$CPU_1M"   || true
SNMPWALK "$OID_cpm5m"     2>/dev/null | _extract_index_value "$OID_cpm5m"     > "$CPU_5M"   || true

# ========= ENTITY: Name/Descr je physIdx holen (nur benötigte) =========
# Sammle unique physIdx aus CPU_PHYS und hole Name/Descr je Eintrag
: > "$ENT_MAP"
if [ -s "$CPU_PHYS" ]; then
  awk '{print $2}' "$CPU_PHYS" | sort -u | while read -r ent; do
    [ -z "$ent" ] && continue
    name="$(SNMPGET "${OID_entName}.${ent}" 2>/dev/null || true)"
    descr="$(SNMPGET "${OID_entDescr}.${ent}" 2>/dev/null || true)"
    # noSuchInstance/noSuchObject -> N/A
    case "$name" in noSuch*|"" ) name="N/A";; esac
    case "$descr" in noSuch*|"" ) descr="N/A";; esac
    printf "%s%s%s%s%s\n" "$ent" "$TAB" "$name" "$TAB" "$descr" >> "$ENT_MAP"
  done
fi

# ========= CPU: Ausgabe =========
echo
echo "=== CPU Utilization (logical instances via CISCO-PROCESS-MIB) ==="
printf "%-6s %-6s %-6s %-6s %-8s %-20.20s %-40.40s\n" "Index" "5sec" "1min" "5min" "PhysIdx" "Name" "Description"
printf -- "---------------------------------------------------------------------------------------------\n"

if [ -s "$CPU_5S" ] || [ -s "$CPU_1M" ] || [ -s "$CPU_5M" ]; then
  # Join der vier CPU-Dateien + ENT_MAP auf cpmIndex bzw. physIdx
  # Schritt 1: baue eine Tabelle per awk (mit assoziativen Arrays *im awk*, kompatibel)
  awk -v TAB="$TAB" -v ENT="$ENT_MAP" '
  BEGIN{
    # ENT-Map laden: entIdx -> name/descr
    while ((getline line < ENT) > 0) {
      split(line, f, TAB);
      entidx=f[1]; ename[f[1]]=f[2]; edesc[f[1]]=f[3];
    }
  }
  FNR==NR { c5s[$1]=$2; idxs[$1]=1; next }                  # CPU_5S
  FNR!=NR && NR==FNR+NR1 { c1m[$1]=$2; idxs[$1]=1; next }   # CPU_1M (handled by passing files in order)
  { ; }' /dev/null >/dev/null 2>&1
fi

# Da das direkte Mehrdatei-Join mit FNR/NR trickreich ist, machen wir es prozedural:
# Erzeuge eine Liste aller cpmIndex (aus allen drei Value-Dateien), dann drucke pro Index.

ALL_IDX="$TMPDIR/cpu_all_idx.tmp"
( cut -d' ' -f1 "$CPU_5S" 2>/dev/null
  cut -d' ' -f1 "$CPU_1M" 2>/dev/null
  cut -d' ' -f1 "$CPU_5M" 2>/dev/null ) | sort -n | uniq > "$ALL_IDX"

if [ -s "$ALL_IDX" ]; then
  while read -r idx; do
    v5s="$(awk -v i="$idx" '$1==i{print $2; exit}' "$CPU_5S" 2>/dev/null || true)"; [ -z "$v5s" ] && v5s="N/A"
    v1m="$(awk -v i="$idx" '$1==i{print $2; exit}' "$CPU_1M" 2>/dev/null || true)"; [ -z "$v1m" ] && v1m="N/A"
    v5m="$(awk -v i="$idx" '$1==i{print $2; exit}' "$CPU_5M" 2>/dev/null || true)"; [ -z "$v5m" ] && v5m="N/A"
    phys="$(awk -v i="$idx" '$1==i{print $2; exit}' "$CPU_PHYS" 2>/dev/null || true)"; [ -z "$phys" ] && phys=""

    if [ -n "$phys" ]; then
      ename="$(awk -F"$TAB" -v p="$phys" '$1==p{print $2; exit}' "$ENT_MAP" 2>/dev/null || true)"; [ -z "$ename" ] && ename="N/A"
      edesc="$(awk -F"$TAB" -v p="$phys" '$1==p{print $3; exit}' "$ENT_MAP" 2>/dev/null || true)"; [ -z "$edesc" ] && edesc="N/A"
    else
      ename="N/A"; edesc="N/A"
    fi

    printf "%-6s %-6s %-6s %-6s %-8s %-20.20s %-40.40s\n" "$idx" "$v5s" "$v1m" "$v5m" "${phys:-}" "$ename" "$edesc"
  done < "$ALL_IDX"

  # Hinweis bei nur 1 CPU-Zeile
  lines="$(wc -l < "$ALL_IDX" | tr -d ' ')"
  if [ "${lines:-0}" -le 1 ]; then
    echo
    echo "[Hinweis] Gerät liefert über SNMP nur eine logische CPU (Gesamtlast)."
  fi
else
  echo "[Hinweis] Keine CPU-Daten gefunden (cpmCPUTotal*Rev). Prüfe SNMPv3-View und MIB-Unterstützung."
fi

# ========= Memory: Werte einsammeln =========
SNMPWALK "$OID_memName" 2>/dev/null | _extract_index_value "$OID_memName" > "$MEM_NAME" || true
SNMPWALK "$OID_memUsed" 2>/dev/null | _extract_index_value "$OID_memUsed" > "$MEM_USED" || true
SNMPWALK "$OID_memFree" 2>/dev/null | _extract_index_value "$OID_memFree" > "$MEM_FREE" || true

echo
echo "=== Memory Pools (CISCO-MEMORY-POOL-MIB) ==="
printf "%-6s %-20.20s %-12s %-12s %-12s %-6s\n" "Index" "PoolName" "Used(B)" "Free(B)" "Total(B)" "Used%"
printf -- "-----------------------------------------------------------------------------\n"

if [ -s "$MEM_NAME" ]; then
  # Alle Pool-Indizes
  MEM_IDX="$TMPDIR/mem_idx.tmp"
  cut -d' ' -f1 "$MEM_NAME" | sort -n | uniq > "$MEM_IDX"

  while read -r pidx; do
    pname="$(awk -v i="$pidx" 'BEGIN{ofs=" "} $1==i{ $1=""; sub(/^ /,""); print; exit }' "$MEM_NAME" 2>/dev/null || true)"
    [ -z "$pname" ] && pname="(unnamed)"
    used="$(awk -v i="$pidx" '$1==i{print $2; exit}' "$MEM_USED" 2>/dev/null || true)"; [ -z "$used" ] && used="0"
    free="$(awk -v i="$pidx" '$1==i{print $2; exit}' "$MEM_FREE" 2>/dev/null || true)"; [ -z "$free" ] && free="0"
    # ensure numbers
    case "$used" in ''|*[!0-9]* ) used=0;; esac
    case "$free" in ''|*[!0-9]* ) free=0;; esac
    total=$(( used + free ))
    if [ "$total" -gt 0 ]; then
      pct=$(( used * 100 / total ))
    else
      pct=0
    fi
    printf "%-6s %-20.20s %-12s %-12s %-12s %-6s\n" "$pidx" "$pname" "$used" "$free" "$total" "$pct"
  done < "$MEM_IDX"
else
  echo "[Hinweis] Keine Memory-Pool-Daten gefunden. Prüfe SNMPv3-View (1.3.6.1.4.1.9.9.48)."
fi
