#!/bin/bash
# Simple SNMPv3 VLAN context test for Cisco devices
# Author: ChatGPT

HOST="172.17.17.252"
USER="SNMP-V3-SECURE-USER-RO"
AUTH_PASS="SuperSecure"
PRIV_PASS="SecureSuper"
AUTH_PROTO="SHA"
PRIV_PROTO="AES"

OIDS="SNMPv2-MIB::sysName.0"

# VLAN contexts to test
VLANS=("vlan-1" "vlan-2" "vlan-3")

echo "=== SNMPv3 VLAN Context Test ==="
echo "Target device: $HOST"
echo "Testing OIDs: $OIDS"
echo

for VLAN in "${VLANS[@]}"; do
  echo "➡ Testing context: $VLAN"
  snmpget -v3 -l authPriv \
    -u "$USER" -a "$AUTH_PROTO" -A "$AUTH_PASS" \
    -x "$PRIV_PROTO" -X "$PRIV_PASS" \
    -n "$VLAN" "$HOST" $OIDS 2>&1 
  echo "-----------------------------------------"
done

