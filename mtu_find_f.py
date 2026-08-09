#!/usr/bin/env python3
from scapy.all import *
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed

RANGES = [
    "104.16.0.0/13",
    "151.101.0.0/16",
    "23.27.192.0/19",
    "185.65.134.0/24",
]

MIN_MTU = 1200
MAX_MTU = 1500
THREADS = 16   # Scapy braucht weniger Threads als raw sockets

def send_icmp_df(ip, size):
    pkt = IP(dst=ip, flags="DF")/ICMP()/Raw(b"A"*size)
    ans = sr1(pkt, timeout=1, verbose=0)

    if ans is None:
        return False

    # ICMP Echo Reply → Paket ging durch
    if ans.haslayer(ICMP) and ans.getlayer(ICMP).type == 0:
        return True

    # ICMP Frag Needed → MTU zu klein
    if ans.haslayer(ICMP) and ans.getlayer(ICMP).type == 3 and ans.getlayer(ICMP).code == 4:
        return False

    return False

def find_pmtu(ip):
    # Reachability check
    if not send_icmp_df(ip, 0):
        return None

    low, high = MIN_MTU, MAX_MTU
    while low < high:
        mid = (low + high + 1) // 2
        if send_icmp_df(ip, mid):
            low = mid
        else:
            high = mid - 1
    return low

def scan_ip(ip):
    pmtu = find_pmtu(str(ip))
    if pmtu is not None and pmtu < 1500:
        return f"{ip} → PMTU {pmtu}"
    return None

def main():
    print(f"Scapy‑PMTU Scan using {THREADS} threads\n")

    for r in RANGES:
        print(f"Scanning {r}")
        ips = list(ipaddress.ip_network(r))

        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            futures = {executor.submit(scan_ip, ip): ip for ip in ips}

            for f in as_completed(futures):
                result = f.result()
                if result:
                    print("  " + result)

if __name__ == "__main__":
    main()
