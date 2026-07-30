#!/usr/bin/env python3
"""
icmp_mtu_scan.py

Fast ICMP reachability and MTU-1500 scan for very large network ranges
(up to /8, e.g. 10.0.0.0/8 with about 16.7 million addresses).

How it works / performance:
  - Pure raw sockets (stdlib "socket", NO Scapy needed) -> minimal per-packet
    overhead.
  - A single pre-built ICMP Echo Request byte packet is reused for all
    targets (id/seq stay constant). Replies are matched to targets purely by
    the source IP of the reply, not by per-packet tracking. This avoids
    expensive bookkeeping for millions of targets.
  - Multiple sender threads (--workers) split the address space between them
    and send without artificial delay (optionally throttled via --rate).
  - A long-running receiver thread accepts all ICMP responses (Echo Reply as
    well as "Fragmentation Needed") and matches them via range/set lookups.

Phases:
  1) Reachability check: ICMP Echo Request to every host address in the
     given networks.
  2) MTU 1500 check: every host found reachable in phase 1 gets a 1500-byte
     packet with the DF bit set. The IP header is built by hand and sent
     unmodified via IP_HDRINCL (no IP_MTU_DISCOVER/PMTUDISC_DO). This is
     deliberate: PMTUDISC_DO lets the kernel maintain a path-MTU cache per
     destination route, which can settle on wrong/inherited MTU assumptions
     when probing thousands of different destinations in a short time. With
     IP_HDRINCL, only the actual network response decides the outcome.
     An explicit "Fragmentation Needed" message immediately and conclusively
     marks a host as MTU < 1500. If there is simply no reply, that is
     ambiguous (could also be a single lost probe) - such hosts are retried
     up to --retries times before being finally counted as MTU < 1500.

Output:
  - Live display on the console
  - reachable_hosts_<timestamp>.csv   (ip;timestamp)
  - mtu_below_1500_<timestamp>.csv    (ip;timestamp;reason)

Requirements:
  - Python 3, Linux (for DF-bit enforcement in phase 2), root/sudo
    (raw sockets require CAP_NET_RAW).

Examples:
    sudo python3 icmp_mtu_scan.py 10.0.0.0/8 --outdir ./scan_results
    sudo python3 icmp_mtu_scan.py 172.16.0.0/12 --workers 32 --rate 200000
"""

import argparse
import csv
import errno
import ipaddress
import os
import signal
import socket
import struct
import sys
import threading
import time
from datetime import datetime

# ---------------------------------------------------------------------------
# Console / colors
# ---------------------------------------------------------------------------
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

_print_lock = threading.Lock()


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    with _print_lock:
        print(msg)
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Linux-specific socket constant for IP_HDRINCL (fall back to the standard
# Linux value from linux/in.h if not present in the socket module)
# ---------------------------------------------------------------------------
IP_HDRINCL = getattr(socket, "IP_HDRINCL", 3)


# ---------------------------------------------------------------------------
# Checksum / packet construction
# ---------------------------------------------------------------------------
def checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) + data[i + 1]
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return (~total) & 0xFFFF


def build_icmp_echo(icmp_id: int, seq: int, payload: bytes) -> bytes:
    header = struct.pack("!BBHHH", 8, 0, 0, icmp_id, seq)  # type=8 (echo request)
    chk = checksum(header + payload)
    header = struct.pack("!BBHHH", 8, 0, chk, icmp_id, seq)
    return header + payload


def build_ip_header(src_ip: str, dst_ip: str, total_len: int, ident: int, df: bool, ttl: int = 64) -> bytes:
    """Builds a complete IPv4 header by hand, including a correct checksum.
    Used together with IP_HDRINCL so the DF bit is guaranteed and
    independent of any kernel-side path-MTU cache."""
    ver_ihl = (4 << 4) | 5  # IPv4, 5*4=20 byte header, no options
    tos = 0
    flags_frag = 0x4000 if df else 0  # bit 14 = DF
    proto = socket.IPPROTO_ICMP
    src = socket.inet_aton(src_ip)
    dst = socket.inet_aton(dst_ip)
    header_no_chk = struct.pack("!BBHHHBBH4s4s", ver_ihl, tos, total_len, ident,
                                 flags_frag, ttl, proto, 0, src, dst)
    chk = checksum(header_no_chk)
    return struct.pack("!BBHHHBBH4s4s", ver_ihl, tos, total_len, ident,
                        flags_frag, ttl, proto, chk, src, dst)


def get_local_source_ip(probe_ip: str = "1.1.1.1", probe_port: int = 80) -> str:
    """Determines the local source IP for outgoing packets based on the
    default route (a UDP 'connect' only triggers the routing lookup, no
    packet is actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((probe_ip, probe_port))
        return s.getsockname()[0]
    finally:
        s.close()


def int_to_ip(ip_int: int) -> str:
    return socket.inet_ntoa(struct.pack("!I", ip_int))


# ---------------------------------------------------------------------------
# Collect target ranges (as start/end integer intervals, not materialized
# -> negligible memory footprint even for a /8)
# ---------------------------------------------------------------------------
def collect_ranges(networks, targets_file):
    specs = list(networks)
    if targets_file:
        with open(targets_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    specs.append(line)

    ranges = []
    for spec in specs:
        try:
            net = ipaddress.ip_network(spec, strict=False)
        except ValueError as e:
            log(f"{RED}Invalid target '{spec}': {e}{RESET}")
            continue
        if net.num_addresses <= 2:
            start = int(net.network_address)
            end = int(net.broadcast_address)
        else:
            start = int(net.network_address) + 1
            end = int(net.broadcast_address) - 1
        ranges.append((start, end))
    return ranges


def total_addresses(ranges):
    return sum(e - s + 1 for s, e in ranges)


def partition_ranges(ranges, n_workers):
    """Splits a list of (start,end) intervals as evenly as possible across
    n_workers, even if a single interval (e.g. a /8) has to be cut across
    multiple workers."""
    total = total_addresses(ranges)
    if total == 0:
        return [[] for _ in range(n_workers)]

    # Size per worker: distribute the remainder evenly across the first
    # workers so the sum exactly equals "total" (no rounding gaps).
    base = total // n_workers
    extra = total % n_workers
    sizes = [base + (1 if i < extra else 0) for i in range(n_workers)]

    workers = [[] for _ in range(n_workers)]
    w = 0
    remaining = sizes[0]
    for s, e in ranges:
        cur = s
        while cur <= e:
            while remaining <= 0:
                w += 1
                remaining = sizes[w]
            take = min(remaining, e - cur + 1)
            workers[w].append((cur, cur + take - 1))
            cur += take
            remaining -= take
    return workers


# ---------------------------------------------------------------------------
# CSV writer helper (writes+flushes immediately -> nothing lost on abort)
# ---------------------------------------------------------------------------
class CsvLogger:
    def __init__(self, path, header):
        self.file = open(path, "w", newline="", encoding="utf-8")
        self.writer = csv.writer(self.file, delimiter=";")
        self.writer.writerow(header)
        self.file.flush()
        self.lock = threading.Lock()

    def write(self, row):
        with self.lock:
            self.writer.writerow(row)
            self.file.flush()

    def close(self):
        self.file.close()


# ---------------------------------------------------------------------------
# Receiver: runs for the entire program lifetime, handles both phase 1 and
# phase 2 responses
# ---------------------------------------------------------------------------
class Receiver(threading.Thread):
    def __init__(self, ranges, reachable_csv, mtu_csv):
        super().__init__(daemon=True)
        self.ranges = ranges
        self.reachable_csv = reachable_csv
        self.mtu_csv = mtu_csv

        self.reachable_seen = set()
        self.reachable_count = 0

        # phase2_unresolved is repopulated each test round (only hosts that
        # have not yet received a reply/Fragmentation-Needed message this
        # round). ok_mtu / below_mtu, on the other hand, accumulate across
        # all rounds.
        self.phase2_unresolved = set()
        self.phase2_lock = threading.Lock()
        self.ok_mtu = set()
        self.below_mtu = set()

        self._stop = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        self.sock.settimeout(1.0)

    def in_target_ranges(self, ip_int):
        for s, e in self.ranges:
            if s <= ip_int <= e:
                return True
        return False

    def run(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                continue

            if len(data) < 20:
                continue
            ihl = (data[0] & 0x0F) * 4
            if len(data) < ihl + 2:
                continue
            icmp_type = data[ihl]
            icmp_code = data[ihl + 1]

            if icmp_type == 0:  # Echo Reply
                src = addr[0]
                src_int = struct.unpack("!I", socket.inet_aton(src))[0]

                # Check phase 2 first (smaller, more specific target set)
                with self.phase2_lock:
                    is_phase2_target = src_int in self.phase2_unresolved
                    if is_phase2_target:
                        self.phase2_unresolved.discard(src_int)
                        self.ok_mtu.add(src_int)
                if is_phase2_target:
                    log(f"{GREEN}[MTU OK]{RESET} {src:<15} accepted 1500 bytes (DF)")
                    continue

                if src_int not in self.reachable_seen and self.in_target_ranges(src_int):
                    self.reachable_seen.add(src_int)
                    self.reachable_count += 1
                    row_ts = ts()
                    log(f"{GREEN}[OK]{RESET}  {src:<15} reachable")
                    self.reachable_csv.write([src, row_ts])

            elif icmp_type == 3 and icmp_code == 4:  # Fragmentation Needed
                inner_off = ihl + 8
                if len(data) < inner_off + 20:
                    continue
                inner_dst_bytes = data[inner_off + 16:inner_off + 20]
                if len(inner_dst_bytes) != 4:
                    continue
                orig_dst_int = struct.unpack("!I", inner_dst_bytes)[0]
                with self.phase2_lock:
                    is_pending = orig_dst_int in self.phase2_unresolved
                    if is_pending:
                        self.phase2_unresolved.discard(orig_dst_int)
                        self.below_mtu.add(orig_dst_int)
                if is_pending:
                    orig_dst = int_to_ip(orig_dst_int)
                    row_ts = ts()
                    log(f"{YELLOW}[MTU<1500]{RESET} {orig_dst:<15} - Fragmentation Needed (ICMP)")
                    self.mtu_csv.write([orig_dst, row_ts, "fragmentation_needed"])

    def reset_phase2(self):
        """Call once before the first test round."""
        with self.phase2_lock:
            self.ok_mtu = set()
            self.below_mtu = set()

    def start_phase2_round(self, targets):
        """Sets the set of hosts still open (unanswered) for this round.
        Hosts already confirmed as below_mtu via an explicit
        Fragmentation-Needed message are not tested again (the message is
        unambiguous -> no retry needed)."""
        with self.phase2_lock:
            self.phase2_unresolved = set(t for t in targets if t not in self.below_mtu)

    def get_unresolved_snapshot(self):
        with self.phase2_lock:
            return set(self.phase2_unresolved)

    def finalize_phase2(self):
        """After the last retry round: anything that received neither a
        1500-byte reply nor an explicit Fragmentation-Needed message is
        logged as MTU<1500 (ambiguous, no reply)."""
        with self.phase2_lock:
            leftover = list(self.phase2_unresolved)
            self.phase2_unresolved.clear()
        for ip_int in leftover:
            self.below_mtu.add(ip_int)
            ip_str = int_to_ip(ip_int)
            row_ts = ts()
            log(f"{YELLOW}[MTU<1500]{RESET} {ip_str:<15} - no reply to 1500-byte packet (after all attempts)")
            self.mtu_csv.write([ip_str, row_ts, "no_reply_on_1500"])

    def stop(self):
        self._stop.set()


# ---------------------------------------------------------------------------
# Sender
# ---------------------------------------------------------------------------
def make_send_socket(use_hdrincl: bool):
    if use_hdrincl:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
        sock.setsockopt(socket.IPPROTO_IP, IP_HDRINCL, 1)
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    return sock


def sender_worker(assigned_ranges, build_packet, use_hdrincl: bool, delay: float, counter: list, idx: int,
                   error_counts: list):
    sock = make_send_socket(use_hdrincl)
    local_errors = {}
    try:
        for s, e in assigned_ranges:
            for ip_int in range(s, e + 1):
                dst = int_to_ip(ip_int)
                packet = build_packet(dst, ip_int)
                try:
                    sock.sendto(packet, (dst, 0))
                except OSError as ex:
                    key = ex.errno if ex.errno is not None else -1
                    local_errors[key] = local_errors.get(key, 0) + 1
                counter[idx] += 1
                if delay:
                    time.sleep(delay)
    finally:
        sock.close()
        error_counts[idx] = local_errors


def run_send_phase(ranges_or_list, build_packet, use_hdrincl, n_workers, rate, label):
    """ranges_or_list: list of (start,end) intervals.
    build_packet(dst_ip_str, dst_ip_int) -> bytes, called once per target address."""
    total = total_addresses(ranges_or_list)
    if total == 0:
        return
    n_workers = max(1, n_workers)
    shards = partition_ranges(ranges_or_list, n_workers)
    counter = [0] * n_workers
    error_counts = [dict() for _ in range(n_workers)]
    delay = (n_workers / rate) if rate and rate > 0 else 0.0

    threads = []
    for i, shard in enumerate(shards):
        t = threading.Thread(target=sender_worker,
                              args=(shard, build_packet, use_hdrincl, delay, counter, i, error_counts),
                              daemon=True)
        threads.append(t)

    log(f"{CYAN}--- {label}: sending to {total} addresses ({n_workers} threads) ---{RESET}")
    start_time = time.time()
    for t in threads:
        t.start()

    # Progress monitor
    while any(t.is_alive() for t in threads):
        time.sleep(2)
        sent = sum(counter)
        elapsed = max(time.time() - start_time, 0.001)
        pps = int(sent / elapsed)
        pct = (sent / total) * 100 if total else 100
        log(f"{CYAN}... {label}: {sent}/{total} ({pct:.1f}%), ~{pps} pkt/s{RESET}")

    for t in threads:
        t.join()

    sent = sum(counter)
    elapsed = round(time.time() - start_time, 1)
    log(f"{CYAN}{label}: send complete ({sent} packets in {elapsed}s){RESET}")

    total_errors = {}
    for d in error_counts:
        for k, v in d.items():
            total_errors[k] = total_errors.get(k, 0) + v
    if total_errors:
        details = ", ".join(
            f"{errno.errorcode.get(k, 'errno ' + str(k))} ({os.strerror(k) if k > 0 else 'unknown'}): {v}x"
            for k, v in sorted(total_errors.items())
        )
        log(f"{YELLOW}Warning - sendto() errors during {label}: {details}{RESET}")
        if any(k == errno.EMSGSIZE for k in total_errors):
            log(f"{YELLOW}  -> EMSGSIZE means: the local interface/route does not allow a "
                f"1500-byte DF packet, the affected packets were NEVER sent. "
                f"Check the local MTU/route of this scanning machine.{RESET}")


def ints_to_singleton_ranges(int_iterable):
    return [(i, i) for i in int_iterable]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Fast ICMP reachability and MTU-1500 scan for large network ranges (up to /8)."
    )
    parser.add_argument("networks", nargs="*", help="CIDR networks or single IPs, e.g. 10.0.0.0/8")
    parser.add_argument("--targets-file", help="File with one target (CIDR/IP) per line")
    parser.add_argument("--outdir", default=".", help="Output directory for the CSV files")
    parser.add_argument("--workers", type=int, default=16, help="Number of parallel sender threads (default 16)")
    parser.add_argument("--rate", type=int, default=0, help="Maximum total rate in packets/second (0 = unlimited)")
    parser.add_argument("--timeout", type=float, default=5.0, help="Wait time for replies per send round (s)")
    parser.add_argument("--mtu", type=int, default=1500, help="Packet size in bytes to test (default 1500)")
    parser.add_argument("--retries", type=int, default=2,
                         help="Additional attempts in phase 2 for hosts without a reply (default 2, "
                              "i.e. up to 3 attempts total). A single packet loss for large DF packets "
                              "(e.g. due to ICMP rate limiting) would otherwise easily produce a false "
                              "'MTU<1500' result.")
    args = parser.parse_args()

    if not args.networks and not args.targets_file:
        parser.error("Please specify at least one network or use --targets-file.")

    if hasattr(os, "geteuid") and os.geteuid() != 0:
        log(f"{RED}Error: raw ICMP sockets require root privileges. Please run with sudo.{RESET}")
        sys.exit(1)

    if not sys.platform.startswith("linux"):
        log(f"{YELLOW}Note: IP_HDRINCL/DF-bit enforcement (phase 2) is tested on Linux. "
            f"May be limited on other platforms.{RESET}")

    os.makedirs(args.outdir, exist_ok=True)

    ranges = collect_ranges(args.networks, args.targets_file)
    if not ranges:
        log(f"{RED}No valid target addresses found.{RESET}")
        sys.exit(1)

    total = total_addresses(ranges)
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    reachable_path = os.path.join(args.outdir, f"reachable_hosts_{run_ts}.csv")
    mtu_path = os.path.join(args.outdir, f"mtu_below_1500_{run_ts}.csv")

    reachable_csv = CsvLogger(reachable_path, ["ip", "timestamp"])
    mtu_csv = CsvLogger(mtu_path, ["ip", "timestamp", "reason"])

    log(f"{CYAN}Total targets: {total}{RESET}")
    log(f"{CYAN}Output: {reachable_path}, {mtu_path}{RESET}")

    icmp_id = os.getpid() & 0xFFFF
    phase1_packet = build_icmp_echo(icmp_id, 1, b"icmp-mtu-scan" + b"\x00" * 19)
    payload_size = max(args.mtu - 28, 0)  # 20 bytes IP header + 8 bytes ICMP header
    phase2_icmp = build_icmp_echo(icmp_id, 2, b"X" * payload_size)

    try:
        local_src_ip = get_local_source_ip()
    except OSError as e:
        log(f"{RED}Could not determine local source IP (is there a default route?): {e}{RESET}")
        sys.exit(1)
    log(f"{CYAN}Local source IP for phase 2 (IP_HDRINCL): {local_src_ip}{RESET}")

    def build_phase1_packet(dst_ip, dst_int):
        return phase1_packet

    def build_phase2_packet(dst_ip, dst_int):
        ident = dst_int & 0xFFFF
        ip_header = build_ip_header(local_src_ip, dst_ip, args.mtu, ident, df=True)
        return ip_header + phase2_icmp

    receiver = Receiver(ranges, reachable_csv, mtu_csv)
    receiver.start()

    start = time.time()
    try:
        # Phase 1: reachability
        run_send_phase(ranges, build_phase1_packet, use_hdrincl=False, n_workers=args.workers,
                        rate=args.rate, label="Phase 1 (reachability)")
        log(f"{CYAN}Waiting {args.timeout}s for pending replies (phase 1)...{RESET}")
        time.sleep(args.timeout)

        reachable_ints = set(receiver.reachable_seen)
        log(f"{CYAN}Reachable: {len(reachable_ints)} hosts{RESET}")

        if reachable_ints:
            receiver.reset_phase2()
            max_rounds = max(1, args.retries + 1)
            current_targets = reachable_ints
            round_num = 1
            while current_targets and round_num <= max_rounds:
                receiver.start_phase2_round(current_targets)
                phase2_ranges = ints_to_singleton_ranges(current_targets)
                label = f"Phase 2 (MTU 1500 / DF) - round {round_num}/{max_rounds}"
                run_send_phase(phase2_ranges, build_phase2_packet, use_hdrincl=True,
                                n_workers=min(args.workers, max(1, len(current_targets))),
                                rate=args.rate, label=label)
                log(f"{CYAN}Waiting {args.timeout}s for pending replies (round {round_num})...{RESET}")
                time.sleep(args.timeout)
                current_targets = receiver.get_unresolved_snapshot()
                if current_targets and round_num < max_rounds:
                    log(f"{YELLOW}{len(current_targets)} hosts without a reply - retrying "
                        f"(round {round_num + 1}/{max_rounds})...{RESET}")
                round_num += 1
            receiver.finalize_phase2()

    except KeyboardInterrupt:
        log(f"{RED}Aborted by user - saving results collected so far.{RESET}")
    finally:
        receiver.stop()
        reachable_csv.close()
        mtu_csv.close()

    elapsed = round(time.time() - start, 1)
    log(f"{CYAN}--- Summary ---{RESET}")
    log(f"Scanned addresses : {total}")
    log(f"Reachable         : {len(receiver.reachable_seen)}")
    log(f"MTU 1500 OK       : {len(receiver.ok_mtu)}")
    log(f"MTU < 1500        : {len(receiver.below_mtu)}")
    log(f"Duration          : {elapsed}s")
    log(f"CSV reachable     : {reachable_path}")
    log(f"CSV MTU<1500      : {mtu_path}")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.default_int_handler)
    main()
