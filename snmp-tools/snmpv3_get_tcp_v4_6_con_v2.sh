#!/bin/sh
set -eu

DEBUG=1
HOST=home.jeitler.guru
SNMP_USER=SNMP_RO
SNMP_AUTH_PROTO=SHA SNMP_AUTH_PASS='supersecure'
SNMP_PRIV_PROTO=AES SNMP_PRIV_PASS='supersecure'


# ========= User config =========
HOST="${HOST:-192.168.1.10}"

SNMP_USER="${SNMP_USER:-SNMPUSER}"
SNMP_AUTH_PROTO="${SNMP_AUTH_PROTO:-SHA}"   # MD5 oder SHA
SNMP_AUTH_PASS="${SNMP_AUTH_PASS:-AUTH_PASS}"
SNMP_PRIV_PROTO="${SNMP_PRIV_PROTO:-AES}"   # AES oder DES
SNMP_PRIV_PASS="${SNMP_PRIV_PASS:-PRIV_PASS}"

# Debug: DEBUG=1 ./snmpv3_get_tcp_con.sh
DEBUG="${DEBUG:-0}"
TAB="$(printf '\t')"

# ========= OIDs =========
# IPv4 only (RFC 1213)
TCP1213_STATE="1.3.6.1.2.1.6.13.1.1"        # tcpConnState

# v4+v6 (RFC 4022)
TCP4022_STATE="1.3.6.1.2.1.6.19.1.1"        # tcpConnectionState

# ========= SNMP helpers =========
SNMPWALK_NUM() {
  # numerische OIDs + kompakter Output (OID Wert)
  snmpwalk -v3 -l authPriv -u "$SNMP_USER" -a "$SNMP_AUTH_PROTO" -A "$SNMP_AUTH_PASS" \
           -x "$SNMP_PRIV_PROTO" -X "$SNMP_PRIV_PASS" -On -Oqn "$HOST" "$@"
}
SNMPWALK_TXT() {
  # textuelle OIDs (inkl. ipv6."…") + kompakter Output (OID Wert)
  snmpwalk -v3 -l authPriv -u "$SNMP_USER" -a "$SNMP_AUTH_PROTO" -A "$SNMP_AUTH_PASS" \
           -x "$SNMP_PRIV_PROTO" -X "$SNMP_PRIV_PASS" -Oq "$HOST" "$@"
}

# ========= Temp =========
TDIR="$(mktemp -d -t tcpcon.XXXXXX)"; trap 'rm -rf "$TDIR"' EXIT
F_V4="$TDIR/v4_1213.txt"
F_4022_NUM="$TDIR/v46_4022_num.txt"
F_4022_TXT="$TDIR/v46_4022_txt.txt"
F_ROWS="$TDIR/rows.tsv"

# ---------- RFC 1213 (IPv4) ----------
SNMPWALK_NUM "$TCP1213_STATE" 2>/dev/null > "$F_V4" || true

# ---------- RFC 4022 (v4/v6) numeric ----------
SNMPWALK_NUM "$TCP4022_STATE" 2>/dev/null > "$F_4022_NUM" || true

# ---------- RFC 4022 (v4/v6) textual Fallback ----------
# Nur wenn numeric nichts liefert (oder du explizit willst: setze FORCE_TXT=1)
FORCE_TXT="${FORCE_TXT:-0}"
if [ "$FORCE_TXT" = "1" ] || [ ! -s "$F_4022_NUM" ]; then
  SNMPWALK_TXT "$TCP4022_STATE" 2>/dev/null > "$F_4022_TXT" || true
fi

[ "$DEBUG" = "1" ] && { echo "# RAW V4  (1213): $F_V4"; echo "# RAW V46 (4022 num): $F_4022_NUM"; echo "# RAW V46 (4022 txt): $F_4022_TXT"; }

: > "$F_ROWS"

# ---------- Parser: RFC 1213 IPv4 ----------
awk -v base="$TCP1213_STATE" -v TAB="$TAB" '
function st(n,    s){ if(n==1)s="closed";else if(n==2)s="listen";else if(n==3)s="synSent";else if(n==4)s="synRecv";else if(n==5)s="established";else if(n==6)s="finWait1";else if(n==7)s="finWait2";else if(n==8)s="closeWait";else if(n==9)s="lastAck";else if(n==10)s="closing";else if(n==11)s="timeWait";else if(n==12)s="deleteTCB";else s=n; return s }
{
  oid=$1; state=$2; if(oid=="") next;
  sub(/^\./,"",oid); pref=base ".";
  if (index(oid,pref)!=1) next;
  suf=substr(oid,length(pref)+1);
  n=split(suf,a,"."); if(n<10) next;
  l=a[1] "." a[2] "." a[3] "." a[4]; lp=a[5];
  r=a[6] "." a[7] "." a[8] "." a[9]; rp=a[10];
  print "IPv4" TAB l ":" lp TAB r ":" rp TAB st(state);
}' "$F_V4" >> "$F_ROWS" || true

# ---------- Parser: RFC 4022 numeric (v4/v6) ----------
awk -v base="$TCP4022_STATE" -v TAB="$TAB" '
function st(n,    s){ if(n==1)s="closed";else if(n==2)s="listen";else if(n==3)s="synSent";else if(n==4)s="synRecv";else if(n==5)s="established";else if(n==6)s="finWait1";else if(n==7)s="finWait2";else if(n==8)s="closeWait";else if(n==9)s="lastAck";else if(n==10)s="closing";else if(n==11)s="timeWait";else if(n==12)s="deleteTCB";else s=n; return s }
function ipv6_from(lb, len,   i,h,out){ out=""; for(i=1;i<=16 && i<=len;i+=2){ h=sprintf("%02x%02x",lb[i],lb[i+1]); sub(/^000/,"",h); sub(/^00/,"",h); sub(/^0/,"",h); if(h=="")h="0"; out=out h (i<15?":":"") } return out }
{
  oid=$1; state=$2; if(oid=="") next;
  sub(/^\./,"",oid); pref=base ".";
  if (index(oid,pref)!=1) next;
  suf=substr(oid,length(pref)+1); n=split(suf,a,"."); if(n<8) next;

  p=1; lType=a[p++]; lLen=a[p++]; if (p+lLen>n) next;
  delete lb; for(i=1;i<=lLen;i++) lb[i]=a[p++]; lPort=a[p++];
  if (p>n) next; rType=a[p++]; rLen=a[p++]; if (p+rLen>n) next;
  delete rb; for(i=1;i<=rLen;i++) rb[i]=a[p++]; rPort=a[p];

  # InetAddressType: 1=ipv4, 2=ipv6, 3=ipv4z, 4=ipv6z
  t="T" lType; l="T" lType;
  if (lType==1 || lType==3) { t="IPv4"; l=lb[1]"."lb[2]"."lb[3]"."lb[4] }
  else if (lType==2 || lType==4) { t="IPv6"; l=ipv6_from(lb,lLen) }

  if (rType==1 || rType==3) r=rb[1]"."rb[2]"."rb[3]"."rb[4];
  else if (rType==2 || rType==4) r=ipv6_from(rb,rLen);
  else r="T" rType;

  print t TAB l ":" lPort TAB r ":" rPort TAB st(state);
}' "$F_4022_NUM" >> "$F_ROWS" || true

# ---------- Parser: RFC 4022 textual Fallback (v4/v6) ----------
# erwartet Zeilen wie:
# TCP-MIB::tcpConnectionState.ipv6."2a:04:...:01".2005.ipv6."2a:04:...:3a".55780 5
if [ -s "$F_4022_TXT" ]; then
  awk -v TAB="$TAB" '
  function st(n,    s){ if(n==1)s="closed";else if(n==2)s="listen";else if(n==3)s="synSent";else if(n==4)s="synRecv";else if(n==5)s="established";else if(n==6)s="finWait1";else if(n==7)s="finWait2";else if(n==8)s="closeWait";else if(n==9)s="lastAck";else if(n==10)s="closing";else if(n==11)s="timeWait";else if(n==12)s="deleteTCB";else s=n; return s }
  {
    # Split Wert (letztes Feld) ab
    state=$NF
    $NF=""; sub(/[[:space:]]+$/,"",$0)
    line=$0

    # extrahiere local type, addr, port; remote type, addr, port
    # IPv6/IPv4 sind als   ... .ipv6."addr".port.ipv6."addr".port
    # Wir machen das in Schritten
    # 1) entferne Prefix bis tcpConnectionState.
    sub(/^.*tcpConnectionState\./,"",line)

    # 2) local type
    if (match(line,/^(ipv[46]z?|unknown|ipv4|ipv6)\./)) {
      ltype=substr(line,RSTART,RLENGTH); line=substr(line,RLENGTH+2)  # skip the dot
    } else next

    # 3) local addr (in Anführungszeichen)
    if (match(line,/^"[^"]*"\./)) {
      laddr=substr(line,2,RLENGTH-4); line=substr(line,RLENGTH+1)
    } else next

    # 4) local port (Zahl)
    if (match(line,/^[0-9]+\./)) {
      lport=substr(line,RSTART,RLENGTH-1); line=substr(line,RLENGTH+1)
    } else next

    # 5) remote type
    if (match(line,/^(ipv[46]z?|unknown|ipv4|ipv6)\./)) {
      rtype=substr(line,RSTART,RLENGTH); line=substr(line,RLENGTH+2)
    } else next

    # 6) remote addr
    if (match(line,/^"[^"]*"\./)) {
      raddr=substr(line,2,RLENGTH-4); line=substr(line,RLENGTH+1)
    } else next

    # 7) remote port (Zahl am Ende)
    if (match(line,/^[0-9]+$/)) {
      rport=line
    } else next

    # Label
    t = (ltype ~ /^ipv6/ ? "IPv6" : (ltype ~ /^ipv4/ ? "IPv4" : "T"))

    print t TAB laddr ":" lport TAB raddr ":" rport TAB st(state)
  }' "$F_4022_TXT" >> "$F_ROWS" || true
fi

# ---------- Ausgabe ----------
echo
echo "=== Active TCP Connections (IPv4 & IPv6 via RFC 1213 + RFC 4022) ==="
printf "%-6s %-39.39s %-39.39s %-12s\n" "Type" "Local" "Remote" "State"
printf -- "---------------------------------------------------------------------------------------------------------------\n"

if [ -s "$F_ROWS" ]; then
  # sort & dedupe
  sort -t"$TAB" -u -k1,1 -k2,2 -k3,3 "$F_ROWS" | awk -F"$TAB" '
  { printf "%-6s %-39.39s %-39.39s %-12s\n", $1,$2,$3,$4; total++; if($1=="IPv6")v6++; else if($1=="IPv4")v4++ }
  END{ printf "\nSumme: %d Verbindungen (IPv4: %d, IPv6: %d)\n", total+0, v4+0, v6+0 }'
else
  echo "[Hinweis] Keine TCP-Verbindungen via SNMP ermittelt."
  echo "          Prüfe 1) mib-2.tcp (1.3.6) und 2) TCP-MIB (1.3.6.19) Zugriff."
fi
