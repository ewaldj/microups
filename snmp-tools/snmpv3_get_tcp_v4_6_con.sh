#!/bin/sh
# - - - - - - - - - - - - - - - - - - - - - - - -
# snmpv3_get_tcp_v4_6_con.sh by ewald@jeitler.cc 2025
# https://www.jeitler.guru 
# - - - - - - - - - - - - - - - - - - - - - - - -
set -eu

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

TAB="$(printf '\t')"

# ========= OIDs =========
# IPv4 only (RFC 1213)
TCP1213_STATE="1.3.6.1.2.1.6.13.1.1"        # tcpConnState

# v4+v6 (RFC 4022)
TCP4022_STATE="1.3.6.1.2.1.6.19.1.1"        # tcpConnectionState

# ========= SNMP helper =========
SNMPWALK() {
  snmpwalk -v3 -t 60 -l authPriv -u "$SNMP_USER" -a "$SNMP_AUTH_PROTO" -A "$SNMP_AUTH_PASS" \
           -x "$SNMP_PRIV_PROTO" -X "$SNMP_PRIV_PASS" -On -Oqn "$HOST" "$@"
}

TMP="$(mktemp -t tcpcon.XXXXXX)"; trap 'rm -f "$TMP"' EXIT

# ---------- IPv4 (RFC 1213) ----------
SNMPWALK "$TCP1213_STATE" 2>/dev/null | awk -v base="$TCP1213_STATE" -v TAB="$TAB" '
function st(n,    s){ if(n==1)s="closed";else if(n==2)s="listen";else if(n==3)s="synSent";else if(n==4)s="synRecv";else if(n==5)s="established";else if(n==6)s="finWait1";else if(n==7)s="finWait2";else if(n==8)s="closeWait";else if(n==9)s="lastAck";else if(n==10)s="closing";else if(n==11)s="timeWait";else if(n==12)s="deleteTCB";else s=n; return s }
{
  oid=$1; state=$2; sub(/^\./,"",oid); pref=base ".";
  if (index(oid,pref)!=1) next;
  suf=substr(oid,length(pref)+1);
  n=split(suf,a,"."); if(n<10) next;

  lAddr=a[1] "." a[2] "." a[3] "." a[4]; lPort=a[5];
  rAddr=a[6] "." a[7] "." a[8] "." a[9]; rPort=a[10];
  print "IPv4" TAB lAddr ":" lPort TAB rAddr ":" rPort TAB st(state);
}' >> "$TMP" || true

# ---------- v4/v6 (RFC 4022) ----------
SNMPWALK "$TCP4022_STATE" 2>/dev/null | awk -v base="$TCP4022_STATE" -v TAB="$TAB" '
function st(n,    s){ if(n==1)s="closed";else if(n==2)s="listen";else if(n==3)s="synSent";else if(n==4)s="synRecv";else if(n==5)s="established";else if(n==6)s="finWait1";else if(n==7)s="finWait2";else if(n==8)s="closeWait";else if(n==9)s="lastAck";else if(n==10)s="closing";else if(n==11)s="timeWait";else if(n==12)s="deleteTCB";else s=n; return s }
function ipv6_from(lb, len,   i,h,out){ out=""; # nimmt die ersten 16 Bytes (bei ipv6z evtl. mehr vorhanden)
  for(i=1;i<=16 && i<=len;i+=2){ h=sprintf("%02x%02x",lb[i],lb[i+1]); sub(/^000/,"",h); sub(/^00/,"",h); sub(/^0/,"",h); if(h=="")h="0"; out=out h (i<15?":":"") } return out }
{
  oid=$1; state=$2; sub(/^\./,"",oid); pref=base ".";
  if (index(oid,pref)!=1) next;
  suf=substr(oid,length(pref)+1); n=split(suf,a,"."); if(n<8) next;

  p=1; lType=a[p++]; lLen=a[p++];
  if (p+lLen>n) next; delete lb; for(i=1;i<=lLen;i++) lb[i]=a[p++]; lPort=a[p++];
  if (p>n) next; rType=a[p++]; rLen=a[p++];
  if (p+rLen>n) next; delete rb; for(i=1;i<=rLen;i++) rb[i]=a[p++]; rPort=a[p];

  # Local addr
  if (lType==1) { t="IPv4"; l=lb[1]"."lb[2]"."lb[3]"."lb[4] }
  else if (lType==2 || lType==4) { t="IPv6"; l=ipv6_from(lb,lLen) }  # 2=ipv6, 4=ipv6z
  else { t="T" lType; l="T" lType }
  # Remote addr
  if (rType==1) r=rb[1]"."rb[2]"."rb[3]"."rb[4];
  else if (rType==2 || rType==4) r=ipv6_from(rb,rLen);
  else r="T" rType;

  print t TAB l ":" lPort TAB r ":" rPort TAB st(state);
}' >> "$TMP" || true

# ---------- Ausgabe ----------
echo
echo "=== Active TCP Connections (IPv4 & IPv6 via RFC 1213 + RFC 4022) ==="
printf "%-6s %-39.39s %-39.39s %-12s\n" "Type" "Local" "Remote" "State"
printf -- "---------------------------------------------------------------------------------------------------------------\n"

if [ -s "$TMP" ]; then
  sort -t"$TAB" -u -k1,1 -k2,2 -k3,3 "$TMP" | awk -F"$TAB" '
  { printf "%-6s %-39.39s %-39.39s %-12s\n", $1,$2,$3,$4; total++; if($1=="IPv6")v6++; else if($1=="IPv4")v4++ }
  END{ printf "\nSumme: %d Verbindungen (IPv4: %d, IPv6: %d)\n", total+0, v4+0, v6+0 }'
else
  echo "[Hinweis] Keine TCP-Verbindungen via SNMP ermittelt."
  echo "          Prüfe SNMPv3-View: mib-2.tcp (1.3.6) und TCP-MIB (1.3.6.19) sollten erlaubt sein."
fi
