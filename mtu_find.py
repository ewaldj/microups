#!/usr/bin/env python3
import subprocess
import ipaddress

RANGES = [
    "104.16.0.0/13",
    "151.101.0.0/16",
    "23.27.192.0/19",
    "185.65.134.0/24",
]

MIN_MTU = 1200
MAX_MTU = 1500

def ping_df(ip, size):
    try:
        # macOS: -D sets DF-bit, -s sets payload size
        cmd = ["ping", "-c", "1", "-D", "-s", str(size), ip]
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
        return out.returncode == 0
    except Exception:
        return False

def find_pmtu(ip):
    # First check reachability
    if not ping_df(ip, 0):
        return None

    low, high = MIN_MTU, MAX_MTU
    while low < high:
        mid = (low + high + 1) // 2
        if ping_df(ip, mid):
            low = mid
        else:
            high = mid - 1
    return low

def main():
    for r in RANGES:
        print(f"\nScanning {r}")
        for ip in ipaddress.ip_network(r):
            pmtu = find_pmtu(str(ip))
            if pmtu is None:
                continue
            if pmtu < 1500:
                print(f"  {ip} → PMTU {pmtu}")

if __name__ == "__main__":
    main()
