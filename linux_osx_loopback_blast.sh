#!/usr/bin/env bash
# linux_osx_loopback_blast.sh - Loopback IP range manager (Linux/macOS)
# Temporary only - IPs are lost on reboot
VERSION="1.03"

set -euo pipefail

usage() {
    cat <<EOF
lo_manager.sh v${VERSION}
Usage: $0 <add|del> <start_ip> <end_ip>

Examples:
  $0 add 10.0.0.1 10.0.0.75
  $0 del 10.0.0.1 10.0.0.75
EOF
    exit 1
}

# Detect OS
OS=$(uname -s)
case "$OS" in
    Linux)  ;;
    Darwin) ;;
    *) echo "ERROR: Unsupported OS: $OS"; exit 1 ;;
esac

# Convert IPv4 to integer
ip_to_int() {
    local ip="$1"
    local a b c d
    IFS='.' read -r a b c d <<< "$ip"
    echo $(( (a << 24) + (b << 16) + (c << 8) + d ))
}

# Convert integer to IPv4
int_to_ip() {
    local n="$1"
    echo "$(( (n >> 24) & 255 )).$(( (n >> 16) & 255 )).$(( (n >> 8) & 255 )).$(( n & 255 ))"
}

# Validate IPv4
validate_ip() {
    local ip="$1"
    if ! [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
        echo "ERROR: Invalid IP: $ip"; exit 1
    fi
    local IFS='.'
    read -r a b c d <<< "$ip"
    for octet in $a $b $c $d; do
        if (( octet > 255 )); then
            echo "ERROR: Invalid octet in IP: $ip"; exit 1
        fi
    done
}

# pipefail-safe IP existence check: collect all IPs into var, then grep
ip_exists_macos() {
    local ip="$1"
    local addrs
    addrs=$(ifconfig lo0 | awk '/inet /{print $2}')
    echo "$addrs" | grep -qx "$ip"
}

ip_exists_linux() {
    local ip="$1"
    local addrs
    addrs=$(ip addr show dev lo)
    echo "$addrs" | grep -q "${ip}/32"
}

add_ip_linux() {
    local ip="$1"
    if ip_exists_linux "$ip"; then
        echo "SKIP  ${ip}/32 already exists"
    else
        ip addr add "${ip}/32" dev lo
        echo "ADD   ${ip}/32 -> lo"
    fi
}

del_ip_linux() {
    local ip="$1"
    if ip_exists_linux "$ip"; then
        ip addr del "${ip}/32" dev lo
        echo "DEL   ${ip}/32 -> lo"
    else
        echo "SKIP  ${ip}/32 not found"
    fi
}

add_ip_macos() {
    local ip="$1"
    if ip_exists_macos "$ip"; then
        echo "SKIP  ${ip}/32 already exists"
    else
        ifconfig lo0 alias "${ip}/32"
        echo "ADD   ${ip}/32 -> lo0"
    fi
}

del_ip_macos() {
    local ip="$1"
    if ip_exists_macos "$ip"; then
        ifconfig lo0 -alias "${ip}"
        echo "DEL   ${ip}/32 -> lo0"
    else
        echo "SKIP  ${ip}/32 not found"
    fi
}

# --- Main ---
[[ $# -ne 3 ]] && usage

ACTION="$1"
START_IP="$2"
END_IP="$3"

[[ "$ACTION" != "add" && "$ACTION" != "del" ]] && usage

validate_ip "$START_IP"
validate_ip "$END_IP"

START_INT=$(ip_to_int "$START_IP")
END_INT=$(ip_to_int "$END_IP")

if (( START_INT > END_INT )); then
    echo "ERROR: start_ip must be <= end_ip"; exit 1
fi

COUNT=$(( END_INT - START_INT + 1 ))
echo "$(echo "$ACTION" | tr '[:lower:]' '[:upper:]') ${COUNT} IPs: ${START_IP} - ${END_IP} (OS: ${OS})"
echo "---"

for (( i = START_INT; i <= END_INT; i++ )); do
    IP=$(int_to_ip "$i")
    case "$OS" in
        Linux)
            [[ "$ACTION" == "add" ]] && add_ip_linux "$IP" || del_ip_linux "$IP"
            ;;
        Darwin)
            [[ "$ACTION" == "add" ]] && add_ip_macos "$IP" || del_ip_macos "$IP"
            ;;
    esac
done

echo "---"
echo "Done."