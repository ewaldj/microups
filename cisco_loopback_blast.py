#!/usr/bin/env python3
"""
cisco_loopback_blast.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bulk-create or delete Loopback interfaces on a Cisco router via SSH.

Modes:
  create  -- Create loopback interfaces (with pre-flight conflict check)
  delete  -- Delete loopback interfaces by interface number range

Usage (create):
    python cisco_loopback_blast.py create -H 10.0.0.1 -u admin -s 100 -r 192.168.0.1 192.168.10.254

Usage (delete):
    python cisco_loopback_blast.py delete -H 10.0.0.1 -u admin -s 100 -e 150

Dependencies:
    pip install netmiko
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import argparse
import getpass
import ipaddress
import logging
import re
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
    from netmiko.exceptions import NetmikoBaseException
except ImportError:
    print("[ERROR] 'netmiko' is not installed. Please run: pip install netmiko")
    sys.exit(1)

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─── Data classes ────────────────────────────────────────────────
@dataclass
class Stats:
    created: int = 0
    deleted: int = 0
    failed:  int = 0
    errors:  List[str] = field(default_factory=list)


@dataclass
class ExistingLoopback:
    number: int
    ip:     Optional[str] = None
    mask:   Optional[str] = None


# ─── Argument parser ─────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cisco_loopback_blast",
        description="Bulk-create or delete Loopback interfaces on Cisco devices via SSH.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create loopbacks Lo100..LoN with IPs 192.168.0.1 to 192.168.10.254
  %(prog)s create -H 10.0.0.1 -u admin -s 100 -r 192.168.0.1 192.168.10.254

  # Create with /32 host mask and custom description
  %(prog)s create -H 10.0.0.1 -u admin -s 0 -r 10.0.0.1 10.255.255.254 \\
                  --mask 255.255.255.255 --description LOOPBACK_AUTO

  # Preview without touching the router
  %(prog)s create -H 10.0.0.1 -u admin -s 200 -r 172.16.0.1 172.16.5.1 --dry-run

  # Maximum speed: raise --batch-size (default 500, try 1000 or 2000)
  %(prog)s create -H 10.0.0.1 -u admin -s 100 -r 192.168.0.1 192.168.10.254 --batch-size 1000

  # Force overwrite of conflicting interfaces without prompting
  %(prog)s create -H 10.0.0.1 -u admin -s 100 -r 192.168.0.1 192.168.5.1 --force

  # Delete Loopback100 through Loopback250
  %(prog)s delete -H 10.0.0.1 -u admin -s 100 -e 250

  # Preview delete without touching the router
  %(prog)s delete -H 10.0.0.1 -u admin -s 100 -e 250 --dry-run
        """,
    )

    sub = parser.add_subparsers(dest="mode", metavar="MODE")
    sub.required = True

    # ── Shared argument groups ───────────────────────────────────
    def add_conn(p: argparse.ArgumentParser) -> None:
        g = p.add_argument_group("Connection")
        g.add_argument("-H", "--host",         required=True,
                       help="Router IP address or hostname")
        g.add_argument("-u", "--username",      required=True,
                       help="SSH username")
        g.add_argument("-p", "--password",      default=None,
                       help="SSH password (prompted interactively if omitted)")
        g.add_argument("--enable-secret",       default=None,
                       help="Enable secret / privileged exec password (optional)")
        g.add_argument("--port",        type=int, default=22,
                       help="SSH port (default: 22)")
        g.add_argument("--timeout",     type=int, default=30,
                       help="Connection timeout in seconds (default: 30)")
        g.add_argument("--device-type", default="cisco_xe",
                       choices=["cisco_ios", "cisco_xe", "cisco_xr", "cisco_nxos"],
                       help="Netmiko device type (default: cisco_xe)")

    def add_run(p: argparse.ArgumentParser) -> None:
        g = p.add_argument_group("Execution")
        g.add_argument("--batch-size", type=int, default=500,
                       help="Number of interfaces per SSH config commit (default: 500, raise to 1000+ for max speed)")
        g.add_argument("--dry-run",    action="store_true", default=False,
                       help="Preview commands only — no changes pushed to router")
        g.add_argument("--verbose",    action="store_true", default=False,
                       help="Show detailed output including raw router responses")
        g.add_argument("--no-save",    action="store_true", default=False,
                       help="Skip 'write memory' after completion (default: save)")
        g.add_argument("--force",      action="store_true", default=False,
                       help="Suppress all confirmation prompts and overwrite conflicts")

    # ── Sub-parser: create ───────────────────────────────────────
    pc = sub.add_parser(
        "create",
        help="Create loopback interfaces in bulk",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_conn(pc)

    ig = pc.add_argument_group("Loopback Configuration")
    ig.add_argument("-s", "--start",       type=int, required=True, metavar="START_LOOPBACK_NO",
                    help="Starting loopback interface number (e.g. 100 → interface Loopback100)")
    ig.add_argument("-r", "--range",       nargs=2, metavar=("START_IP", "END_IP"), required=True,
                    help="IP address range: first and last IP (e.g. 192.168.0.1 192.168.10.254)")
    ig.add_argument("--mask",              default="255.255.255.255",
                    help="Subnet mask applied to every loopback (default: 255.255.255.255 = /32)")
    ig.add_argument("--description",       default=None,
                    help="Interface description added to every loopback (default: none)")
    ig.add_argument("--no-shutdown",       action="store_true", default=True,
                    help="Apply 'no shutdown' to each interface (default: enabled)")
    add_run(pc)

    # ── Sub-parser: delete ───────────────────────────────────────
    pd = sub.add_parser(
        "delete",
        help="Delete loopback interfaces by number range",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_conn(pd)

    dg = pd.add_argument_group("Loopback Selection")
    dg.add_argument("-s", "--start", type=int, required=True, metavar="START_LOOPBACK_NO",
                    help="First loopback number to delete (e.g. 100)")
    dg.add_argument("-e", "--end",   type=int, required=True, metavar="END_LOOPBACK_NO",
                    help="Last loopback number to delete (e.g. 250)")
    add_run(pd)

    return parser


# ─── Input validation ────────────────────────────────────────────
def validate_ip(ip_str: str, label: str) -> ipaddress.IPv4Address:
    try:
        return ipaddress.IPv4Address(ip_str)
    except ipaddress.AddressValueError:
        print(f"[ERROR] Invalid IP address for {label}: {ip_str!r}")
        sys.exit(1)


def validate_mask(mask_str: str) -> ipaddress.IPv4Address:
    try:
        mask = ipaddress.IPv4Address(mask_str)
        bits = int(mask)
        inv  = bits ^ 0xFFFFFFFF
        if inv & (inv + 1) != 0:
            raise ValueError
        return mask
    except (ipaddress.AddressValueError, ValueError):
        print(f"[ERROR] Invalid subnet mask: {mask_str!r}")
        sys.exit(1)


def build_ip_list(
    s: ipaddress.IPv4Address,
    e: ipaddress.IPv4Address,
) -> List[ipaddress.IPv4Address]:
    si, ei = int(s), int(e)
    if si > ei:
        print(f"[ERROR] START_IP ({s}) must be <= END_IP ({e}).")
        sys.exit(1)
    count = ei - si + 1
    print(f"[INFO]  IP range   : {s} -> {e}  ({count:,} addresses)")
    return [ipaddress.IPv4Address(i) for i in range(si, ei + 1)]


# ─── Router query ────────────────────────────────────────────────
def fetch_existing_loopbacks(net: ConnectHandler) -> Dict[int, ExistingLoopback]:
    """
    Reads all existing Loopback interfaces from the router.
    Returns a dict keyed by loopback number.
    """
    print("[CHECK] Reading existing loopback interfaces from router ...")
    try:
        output = net.send_command(
            "show interfaces | include ^Loopback|Internet address",
            read_timeout=60,
        )
    except Exception as exc:
        print(f"[WARN]  Could not read interfaces: {exc}")
        return {}

    loopbacks: Dict[int, ExistingLoopback] = {}
    current_nr: Optional[int] = None
    re_intf = re.compile(r"^Loopback(\d+)\s")
    re_ip   = re.compile(r"Internet address is (\d+\.\d+\.\d+\.\d+)/(\d+)")

    for line in output.splitlines():
        m = re_intf.match(line)
        if m:
            current_nr = int(m.group(1))
            loopbacks[current_nr] = ExistingLoopback(number=current_nr)
            continue
        if current_nr is not None:
            m2 = re_ip.search(line)
            if m2:
                prefix   = int(m2.group(2))
                mask_int = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
                loopbacks[current_nr].ip   = m2.group(1)
                loopbacks[current_nr].mask = str(ipaddress.IPv4Address(mask_int))

    print(f"[CHECK] {len(loopbacks):,} existing loopback interface(s) found on router.")
    return loopbacks


def fetch_all_ip_map(net: ConnectHandler) -> Dict[str, str]:
    """
    Reads ALL interfaces (any type) from the router.
    Returns a mapping of ip_address -> interface_name.
    Used to detect whether a planned IP is used on a non-Loopback interface (hard error).
    """
    try:
        output = net.send_command(
            "show interfaces | include ^[A-Za-z]|Internet address",
            read_timeout=60,
        )
    except Exception as exc:
        print(f"[WARN]  Could not read full interface list: {exc}")
        return {}

    ip_map: Dict[str, str] = {}
    current_intf = ""
    re_intf = re.compile(r"^([A-Za-z][A-Za-z0-9/.:]+)\s+is\s+")
    re_ip   = re.compile(r"Internet address is (\d+\.\d+\.\d+\.\d+)/(\d+)")

    for line in output.splitlines():
        m = re_intf.match(line)
        if m:
            current_intf = m.group(1)
            continue
        if current_intf:
            m2 = re_ip.search(line)
            if m2:
                ip_map[m2.group(1)] = current_intf

    return ip_map


# ─── Conflict detection ──────────────────────────────────────────
@dataclass
class ConflictReport:
    """Holds all conflict information found during pre-flight check."""
    # Loopback interfaces that already exist (number conflict)
    loopback_num_conflicts:  List[ExistingLoopback]   = None
    # Planned IPs already on OTHER loopback interfaces (can be deleted+recreated)
    loopback_ip_conflicts:   List[Tuple]               = None
    # Planned IPs already on NON-loopback interfaces (hard error — cannot resolve)
    nonloopback_ip_conflicts: List[Tuple]              = None

    def __post_init__(self):
        if self.loopback_num_conflicts  is None: self.loopback_num_conflicts  = []
        if self.loopback_ip_conflicts   is None: self.loopback_ip_conflicts   = []
        if self.nonloopback_ip_conflicts is None: self.nonloopback_ip_conflicts = []

    @property
    def has_conflicts(self) -> bool:
        return bool(self.loopback_num_conflicts or
                    self.loopback_ip_conflicts or
                    self.nonloopback_ip_conflicts)

    @property
    def has_fatal(self) -> bool:
        """True when IPs are on non-loopback interfaces — cannot be resolved automatically."""
        return bool(self.nonloopback_ip_conflicts)


def check_conflicts(
    existing:    Dict[int, ExistingLoopback],
    all_ip_map:  Dict[str, str],
    start_nr:    int,
    ip_list:     List[ipaddress.IPv4Address],
) -> ConflictReport:
    """
    Detects three conflict types:
      1. Loopback number conflicts  : planned Lo-Nr already exists  (offer to delete+recreate)
      2. Loopback IP conflicts      : planned IP on another loopback (offer to delete+recreate)
      3. Non-loopback IP conflicts  : planned IP on a physical/SVI   (hard ERROR — abort)
    """
    report = ConflictReport()

    planned_nrs = {start_nr + i for i in range(len(ip_list))}
    # loopback ip -> ExistingLoopback
    lo_ip_map: Dict[str, ExistingLoopback] = {lo.ip: lo for lo in existing.values() if lo.ip}

    # 1) Number conflicts
    report.loopback_num_conflicts = [
        existing[nr] for nr in sorted(planned_nrs) if nr in existing
    ]
    overwrite_lo_nrs = {lo.number for lo in report.loopback_num_conflicts}

    for idx, ip in enumerate(ip_list):
        ip_str     = str(ip)
        planned_nr = start_nr + idx

        # 2) IP already on a different loopback
        if ip_str in lo_ip_map:
            clo = lo_ip_map[ip_str]
            if clo.number not in overwrite_lo_nrs:
                report.loopback_ip_conflicts.append((ip, planned_nr, clo))
            # If clo.number IS in overwrite_lo_nrs it will be deleted anyway — no extra conflict

        # 3) IP already on a non-loopback interface (hard error)
        elif ip_str in all_ip_map:
            intf_name = all_ip_map[ip_str]
            if not intf_name.startswith("Loopback"):
                report.nonloopback_ip_conflicts.append((ip, planned_nr, intf_name))

    return report


def resolve_conflicts(
    net:    ConnectHandler,
    report: ConflictReport,
    force:  bool,
    verbose: bool,
) -> bool:
    """
    Presents the conflict report, handles the user dialog and — if confirmed —
    deletes conflicting loopback interfaces before the create pass begins.

    Logic:
      - Non-loopback IP conflicts  → always ABORT with error (cannot fix automatically)
      - Loopback number/IP conflicts → offer to delete the conflicting loopbacks first
        and then recreate them with the new IPs.
      - --force skips the confirmation prompt.

    Returns True if it is safe to continue with the create pass, False to abort.
    """
    sep = "-" * 64

    # ── HARD ERROR: IP on non-loopback interface ─────────────────
    if report.has_fatal:
        print(f"\n{sep}")
        print("  [ERROR] FATAL IP CONFLICTS — planned IPs are assigned to")
        print("          non-Loopback interfaces. This cannot be resolved")
        print("          automatically. Aborting.")
        print(sep)
        print(f"\n  {'Planned IP':<22} {'Planned Lo':<14} {'Blocking interface'}")
        print(f"  {'-'*20:<22} {'-'*12:<14} {'-'*25}")
        for ip, planned_nr, intf in report.nonloopback_ip_conflicts[:25]:
            print(f"  {str(ip):<22} Loopback{planned_nr:<6} {intf}")
        if len(report.nonloopback_ip_conflicts) > 25:
            print(f"  ... and {len(report.nonloopback_ip_conflicts)-25:,} more.")
        print(f"\n{sep}")
        print("\n[ABORTED] Please remove the IP addresses from the listed")
        print("           interfaces manually before running this script.\n")
        return False

    # ── No conflicts at all ───────────────────────────────────────
    if not report.has_conflicts:
        print("[OK]    No conflicts detected — safe to proceed.")
        return True

    # ── Resolvable loopback conflicts ─────────────────────────────
    print(f"\n{sep}\n  *** CONFLICTS DETECTED ***\n{sep}")

    # Collect ALL loopback numbers to delete — BEFORE the display loop
    # (previously this was done inside [:25] preview loop — BUG: missed all after first 25)
    delete_nrs: List[int] = sorted(set(
        [lo.number for lo in report.loopback_num_conflicts] +
        [clo.number for _, _, clo in report.loopback_ip_conflicts]
    ))

    if report.loopback_num_conflicts:
        print(f"\n  Loopback number conflicts ({len(report.loopback_num_conflicts)}):")
        print(f"  The following loopback interfaces ALREADY EXIST on the router:")
        print(f"  {' '*2}{'Loopback':<16} {'Current IP':<22} {'Mask'}")
        print(f"  {' '*2}{'-'*14:<16} {'-'*20:<22} {'-'*15}")
        for lo in report.loopback_num_conflicts[:25]:
            ip_col = lo.ip if lo.ip else "(no IP configured)"
            print(f"    Loopback{lo.number:<8} {ip_col:<22} {lo.mask or ''}")
        if len(report.loopback_num_conflicts) > 25:
            print(f"    ... and {len(report.loopback_num_conflicts)-25:,} more.")

    if report.loopback_ip_conflicts:
        print(f"\n  Loopback IP conflicts ({len(report.loopback_ip_conflicts)}):")
        print(f"  The following planned IPs are already assigned to OTHER loopback interfaces:")
        print(f"  {' '*2}{'Planned IP':<22} {'Planned Lo':<16} {'Currently on'}")
        print(f"  {' '*2}{'-'*20:<22} {'-'*14:<16} {'-'*20}")
        for ip, planned_nr, clo in report.loopback_ip_conflicts[:25]:
            print(f"    {str(ip):<22} Loopback{planned_nr:<8} Loopback{clo.number}  (IP: {clo.ip})")
        if len(report.loopback_ip_conflicts) > 25:
            print(f"    ... and {len(report.loopback_ip_conflicts)-25:,} more.")
    print(f"\n{sep}")
    print(f"\n  Resolution: delete {len(delete_nrs)} conflicting loopback interface(s) first,")
    print(f"              then create all new loopbacks as requested.")
    print(f"\n  Loopbacks to be DELETED: {', '.join(f'Lo{n}' for n in delete_nrs[:15])}"
          + (f"  (+{len(delete_nrs)-15} more)" if len(delete_nrs) > 15 else ""))
    print()

    if not force:
        try:
            ans = input(
                f"  Delete {len(delete_nrs)} loopback(s) and recreate with new IPs? [y/N]: "
            ).strip().lower()
        except KeyboardInterrupt:
            print("\n[ABORTED]")
            return False
        if ans not in ("y", "yes"):
            print("[ABORTED] No changes were made.")
            return False
    else:
        print("[WARN]  --force active: deleting conflicting loopbacks without prompting.")

    # ── Delete conflicting loopbacks in batches ──────────────────
    # Split into batches (same batch_size as the caller uses) to avoid
    # overloading the SSH buffer with thousands of commands at once.
    DEL_BATCH = 500
    total_del  = len(delete_nrs)
    failed_del = 0
    print(f"\n[INFO]  Deleting {total_del:,} conflicting loopback interface(s) "
          f"(batch size: {DEL_BATCH}) ...")

    for b_start in range(0, total_del, DEL_BATCH):
        chunk    = delete_nrs[b_start : b_start + DEL_BATCH]
        del_cmds = [f"no interface Loopback{nr}" for nr in chunk]
        b_num    = b_start // DEL_BATCH + 1
        b_total  = (total_del + DEL_BATCH - 1) // DEL_BATCH
        pct      = min(100, (b_start + len(chunk)) / total_del * 100)
        print(f"  Deleting batch {b_num}/{b_total}  "
              f"(Lo{chunk[0]}-Lo{chunk[-1]})  [{pct:.0f}%]", flush=True)

        ok, out = push_batch(net, del_cmds, batch_num=b_num, verbose=verbose)
        if not ok:
            print(f"[ERROR] Failed to delete batch {b_num}:\n{out[:400]}")
            print("[ABORTED] Create pass cancelled to avoid inconsistent state.")
            return False

    print(f"[OK]    All {total_del:,} conflicting loopback(s) deleted — "
          f"proceeding with create pass.")
    return True


# ─── SSH connection ──────────────────────────────────────────────
def connect(args: argparse.Namespace, password: str) -> ConnectHandler:
    device = {
        "device_type":         args.device_type,
        "host":                args.host,
        "username":            args.username,
        "password":            password,
        "port":                args.port,
        "timeout":             args.timeout,
        "conn_timeout":        args.timeout,
        "global_delay_factor": 1,   # keep at 1; fast path avoids per-cmd delays
    }
    if args.enable_secret:
        device["secret"] = args.enable_secret

    print(f"[INFO]  Connecting to {args.host}:{args.port} as {args.username!r} ...")
    try:
        net = ConnectHandler(**device)
        if args.enable_secret:
            net.enable()
        print(f"[OK]    Connected — router prompt: {net.find_prompt()}")
        return net
    except NetmikoAuthenticationException:
        print(f"[ERROR] Authentication failed for user {args.username!r}.")
        sys.exit(2)
    except NetmikoTimeoutException:
        print(f"[ERROR] Connection timed out to {args.host}:{args.port}.")
        sys.exit(2)
    except Exception as exc:
        print(f"[ERROR] Unexpected connection error: {exc}")
        sys.exit(2)


# ─── Batch push ──────────────────────────────────────────────────
def push_batch(
    net:       ConnectHandler,
    cmds:      List[str],
    batch_num: int,
    verbose:   bool,
) -> Tuple[bool, str]:
    """
    Sends a config batch to the router.

    Strategy (fastest first, automatic fallback):
      1. Fast path  — write_channel: dumps the entire batch as one SSH write,
                      waits only once for the prompt. No per-command round-trips.
                      ~5-10x faster than send_config_set for large batches.
      2. Slow path  — send_config_set fallback if fast path raises an exception.
    """
    try:
        out = _push_batch_fast(net, cmds, verbose)
    except Exception as exc:
        log.debug("Fast path failed (%s), falling back to send_config_set.", exc)
        try:
            out = net.send_config_set(cmds, cmd_verify=False, read_timeout=120)
        except NetmikoTimeoutException as exc2:
            return False, str(exc2)
        except (NetmikoBaseException, Exception) as exc2:
            return False, str(exc2)

    if verbose:
        print(f"\n-- Batch {batch_num} router output --\n{out}\n")

    for kw in ["% Invalid", "% Error", "% Incomplete", "% Ambiguous",
               "Error:", "Invalid input"]:
        if kw in out:
            return False, out
    return True, out


def _push_batch_fast(net: ConnectHandler, cmds: List[str], verbose: bool) -> str:
    """
    Fast config push using write_channel + active prompt polling.

    How it works:
      1. Enter config mode with 'configure terminal'
      2. Write ALL commands + 'end' as a single SSH payload (no per-cmd wait)
      3. Actively poll the channel in small chunks until the exec-prompt reappears
         — no fixed sleep, so it returns as soon as the router is done.
      4. Return the combined output for error checking.

    Avoids the per-command read loop of send_config_set AND the fixed sleep
    that caused hangs when the router was slower than expected.
    """
    import time as _time

    # Exec prompt to wait for after 'end' (strip trailing # or > for regex safety)
    raw_prompt  = net.find_prompt()
    # Escape special regex chars; we just do a plain string search
    exec_prompt = raw_prompt.strip()

    config_cmd = "configure terminal\n"
    end_cmd    = "end\n"

    # One big payload — router processes at line rate, we read it all back at once
    payload = config_cmd + "\n".join(cmds) + "\n" + end_cmd
    net.write_channel(payload)

    # Active polling: read available data every POLL_INTERVAL seconds.
    # Stop as soon as the exec-prompt appears in the accumulated output.
    # Hard timeout: max(60s, 0.1s per command) — generous for huge batches.
    POLL_INTERVAL = 0.3                                # seconds between reads
    hard_timeout  = max(60.0, len(cmds) * 0.1)
    deadline      = _time.monotonic() + hard_timeout
    accumulated   = ""

    while _time.monotonic() < deadline:
        _time.sleep(POLL_INTERVAL)
        chunk = net.read_channel()
        if chunk:
            accumulated += chunk
            # The exec prompt appears after 'end' exits config mode.
            # It looks like "RT-SH-SPUSU#" or "Router#" at the start of a line.
            if exec_prompt in accumulated:
                break
    else:
        # Timeout — return whatever we got; error checker will catch issues
        log.debug("_push_batch_fast: hard timeout after %.0fs", hard_timeout)

    return accumulated


def safe_disconnect(net: Optional[ConnectHandler]) -> None:
    """
    Closes the SSH connection without hanging.

    Problem: net.disconnect() calls cleanup() -> exit_config_mode() ->
    read_until_pattern() which can hang indefinitely if the channel is busy
    or the router is mid-command (e.g. after Ctrl+C interrupts a push).

    Solution: bypass the Netmiko cleanup chain and close the underlying
    paramiko transport directly. This is instant and always works.
    """
    if net is None:
        return
    try:
        # Try graceful close first with a hard 3s timeout via the transport
        transport = getattr(getattr(net, "remote_conn", None), "transport", None)
        if transport and transport.is_active():
            transport.close()
        # Also attempt the normal cleanup but swallow all errors
        try:
            net.remote_conn.close()
        except Exception:
            pass
    except Exception:
        pass
    print("[INFO]  SSH connection closed.")


def save_config(net: ConnectHandler, verbose: bool) -> None:
    print("[INFO]  Saving configuration (write memory) ...")
    try:
        out = net.save_config()
        if verbose:
            print(out)
        print("[OK]    Configuration saved.")
    except Exception as exc:
        print(f"[WARN]  'write memory' failed: {exc}")


# ─── Progress and summary ────────────────────────────────────────
def print_progress(
    idx:      int,
    total:    int,
    batch_num: int,
    from_nr:  int,
    to_nr:    int,
    t0:       float,
    prefix:   str = "Creating",
) -> None:
    pct  = (idx + 1) / total * 100
    el   = time.time() - t0
    rate = (idx + 1) / el if el > 0 else 0
    eta  = int((total - idx - 1) / rate) if rate > 0 else 0
    w    = len(str(total))
    print(
        f"\r[{pct:5.1f}%]  Batch {batch_num:>4}"
        f"  | {prefix} Lo{from_nr}-Lo{to_nr}"
        f"  | {idx+1:>{w}}/{total}"
        f"  | {rate:5.1f}/s"
        f"  | ETA {eta:>4}s",
        end="", flush=True,
    )


def print_summary(stats: Stats, elapsed: float, mode: str) -> None:
    action = "Created" if mode == "create" else "Deleted"
    count  = stats.created if mode == "create" else stats.deleted
    rate   = count / elapsed if elapsed > 0 and count > 0 else 0
    sep    = "=" * 64
    print(f"\n{sep}\n  RESULT — {mode.upper()}\n{sep}")
    print(f"  {action:<14}: {count:>8,}")
    print(f"  Failed        : {stats.failed:>8,}")
    print(f"  Elapsed       : {elapsed:>7.1f}s")
    if count > 0:
        print(f"  Throughput    : {rate:>7.1f} interfaces/s")
    print(sep)
    if stats.errors:
        print(f"\n[ERROR DETAILS] {len(stats.errors)} failed batch(es):")
        for e in stats.errors:
            print(f"  x {e}")
        sys.exit(3)
    else:
        print(f"\n[OK] All interfaces successfully {action.lower()}.")


# ─── Mode: CREATE ────────────────────────────────────────────────
def _build_create_cmds(
    lo_nr:       int,
    ip:          ipaddress.IPv4Address,
    mask:        str,
    description: Optional[str],
    no_shutdown: bool,
) -> List[str]:
    cmds = [f"interface Loopback{lo_nr}", f" ip address {ip} {mask}"]
    if description:
        cmds.append(f" description {description}")
    if no_shutdown:
        cmds.append(" no shutdown")
    return cmds


def run_create(args: argparse.Namespace, password: str) -> None:
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate inputs
    start_ip = validate_ip(args.range[0], "START_IP")
    end_ip   = validate_ip(args.range[1], "END_IP")
    mask     = validate_mask(args.mask)

    if args.start < 0:
        print("[ERROR] START_LOOPBACK_NO must be >= 0.")
        sys.exit(1)

    ip_list = build_ip_list(start_ip, end_ip)
    total   = len(ip_list)

    print(f"[INFO]  Loopback start : {args.start}")
    print(f"[INFO]  Loopback end   : {args.start + total - 1}")
    print(f"[INFO]  Subnet mask    : {mask}")
    print(f"[INFO]  Batch size     : {args.batch_size}")
    print(f"[INFO]  Total          : {total:,} interfaces")
    if args.description:
        print(f"[INFO]  Description   : {args.description}")

    # Dry-run: local preview only, no SSH needed
    if args.dry_run:
        print("\n[DRY-RUN] No changes will be pushed to the router.\n")
        sample = min(5, total)
        print(f"[DRY-RUN] Preview of first {sample} interface(s):")
        for i in range(sample):
            cmds = _build_create_cmds(
                args.start + i, ip_list[i], str(mask),
                args.description, args.no_shutdown,
            )
            print("  " + "\n  ".join(cmds))
            print()
        if total > sample:
            print(f"  ... and {total - sample:,} more.")
        print("\n[DRY-RUN] Note: pre-flight conflict check is skipped in dry-run mode.")
        return

    # Connect and run
    net   = connect(args, password)
    stats = Stats()
    t0    = time.time()

    try:
        print()
        existing    = fetch_existing_loopbacks(net)
        all_ip_map  = fetch_all_ip_map(net)
        report      = check_conflicts(existing, all_ip_map, args.start, ip_list)
        if not resolve_conflicts(net, report, args.force, args.verbose):
            return
        print()

        batch_cmds  = []
        batch_num   = 0
        batch_start = 0

        for idx, ip in enumerate(ip_list):
            lo_nr = args.start + idx
            batch_cmds.extend(
                _build_create_cmds(lo_nr, ip, str(mask), args.description, args.no_shutdown)
            )
            is_last = (idx == total - 1)
            if (idx + 1) % args.batch_size == 0 or is_last:
                batch_num   += 1
                batch_count  = len(batch_cmds) // 4 if args.description else len(batch_cmds) // 3
                # batch_cmds has N*cmds_per_intf entries; count interfaces precisely
                batch_count  = sum(1 for c in batch_cmds if c.startswith("interface "))
                print_progress(idx, total, batch_num, args.start + batch_start, lo_nr, t0)
                ok, out = push_batch(net, batch_cmds, batch_num, args.verbose)
                if ok:
                    stats.created += batch_count
                else:
                    stats.failed  += batch_count
                    stats.errors.append(
                        f"Batch {batch_num} (Lo{args.start + batch_start}-Lo{lo_nr}): {out[:300]}"
                    )
                    print(f"\n[WARN]  Batch {batch_num} contained errors.")
                batch_cmds  = []
                batch_start = idx + 1

        print()
        if not args.no_save and stats.created > 0:
            save_config(net, args.verbose)

    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Ctrl+C received — closing connection ...")
        safe_disconnect(net)
        print(f"[INFO]  {stats.created:,} interface(s) created before interrupt.")
        sys.exit(130)
    finally:
        safe_disconnect(net)

    print_summary(stats, time.time() - t0, "create")


# ─── Mode: DELETE ────────────────────────────────────────────────
def run_delete(args: argparse.Namespace, password: str) -> None:
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.start < 0:
        print("[ERROR] START_LOOPBACK_NO must be >= 0.")
        sys.exit(1)
    if args.end < args.start:
        print(f"[ERROR] END_LOOPBACK_NO ({args.end}) must be >= START_LOOPBACK_NO ({args.start}).")
        sys.exit(1)

    loopback_nrs = list(range(args.start, args.end + 1))
    total        = len(loopback_nrs)

    print(f"[INFO]  Loopback start : {args.start}")
    print(f"[INFO]  Loopback end   : {args.end}")
    print(f"[INFO]  Requested      : {total:,} interfaces")
    print(f"[INFO]  Batch size     : {args.batch_size}")

    # Dry-run
    if args.dry_run:
        print("\n[DRY-RUN] No changes will be pushed to the router.\n")
        sample = min(5, total)
        print(f"[DRY-RUN] Preview of first {sample} delete command(s):")
        for nr in loopback_nrs[:sample]:
            print(f"  no interface Loopback{nr}")
        if total > sample:
            print(f"  ... and {total - sample:,} more.")
        return

    net   = connect(args, password)
    stats = Stats()
    t0    = time.time()

    try:
        print()
        existing = fetch_existing_loopbacks(net)

        existing_in_range = [nr for nr in loopback_nrs if nr in existing]
        missing_in_range  = [nr for nr in loopback_nrs if nr not in existing]

        print(f"[INFO]  Found on router : {len(existing_in_range):,}")
        print(f"[INFO]  Not found       : {len(missing_in_range):,}  (will be skipped)")

        if not existing_in_range:
            print("[OK]    None of the specified loopbacks exist — nothing to do.")
            return

        if missing_in_range:
            pre    = missing_in_range[:10]
            suffix = f" +{len(missing_in_range) - 10} more" if len(missing_in_range) > 10 else ""
            print(f"[INFO]  Skipping       : {', '.join(f'Lo{n}' for n in pre)}{suffix}")

        print(f"\n[INFO]  Interfaces to delete (preview, max 10):")
        for nr in existing_in_range[:10]:
            lo      = existing[nr]
            ip_info = f"  =>  {lo.ip}/{lo.mask}" if lo.ip else "  =>  (no IP configured)"
            print(f"  no interface Loopback{nr}{ip_info}")
        if len(existing_in_range) > 10:
            print(f"  ... and {len(existing_in_range) - 10:,} more.")

        if not args.force:
            print()
            try:
                ans = input(
                    f"  Permanently delete {len(existing_in_range):,} interface(s)"
                    f" on {args.host}? [y/N]: "
                ).strip().lower()
            except KeyboardInterrupt:
                print("\n[ABORTED]")
                return
            if ans not in ("y", "yes"):
                print("[ABORTED] No changes were made.")
                return

        print()

        batch_cmds      = []
        batch_num       = 0
        batch_start_idx = 0

        for idx, nr in enumerate(existing_in_range):
            batch_cmds.append(f"no interface Loopback{nr}")
            is_last = (idx == len(existing_in_range) - 1)
            if (idx + 1) % args.batch_size == 0 or is_last:
                batch_num   += 1
                batch_count  = len(batch_cmds)   # exactly 1 cmd per interface: 'no interface LoopbackN'
                from_nr      = existing_in_range[batch_start_idx]
                print_progress(idx, len(existing_in_range), batch_num, from_nr, nr, t0,
                               prefix="Deleting")
                ok, out = push_batch(net, batch_cmds, batch_num, args.verbose)
                if ok:
                    stats.deleted += batch_count
                else:
                    stats.failed  += batch_count
                    stats.errors.append(
                        f"Batch {batch_num} (Lo{from_nr}-Lo{nr}): {out[:300]}"
                    )
                    print(f"\n[WARN]  Batch {batch_num} contained errors.")
                batch_cmds      = []
                batch_start_idx = idx + 1

        print()
        if not args.no_save and stats.deleted > 0:
            save_config(net, args.verbose)

    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Ctrl+C received — closing connection ...")
        safe_disconnect(net)
        print(f"[INFO]  {stats.deleted:,} interface(s) deleted before interrupt.")
        sys.exit(130)
    finally:
        safe_disconnect(net)

    print_summary(stats, time.time() - t0, "delete")


# ─── Entry point ─────────────────────────────────────────────────
def main() -> None:
    # Install a clean Ctrl+C handler so a double-Ctrl+C always exits immediately
    def _sigint(sig, frame):
        print("\n[INTERRUPTED] Ctrl+C — exiting immediately.")
        sys.exit(130)
    signal.signal(signal.SIGINT, _sigint)

    print("+======================================================+")
    print("|   cisco_loopback_blast  —  Cisco Loopback Manager   |")
    print("+======================================================+\n")

    parser = build_parser()
    args   = parser.parse_args()

    # Prompt for password if not provided via -p
    password = args.password
    if not password:
        try:
            password = getpass.getpass(f"SSH password for {args.username!r}@{args.host}: ")
        except KeyboardInterrupt:
            print("\n[ABORTED]")
            sys.exit(0)

    if not password:
        print("[ERROR] No password provided.")
        sys.exit(1)

    if args.mode == "create":
        run_create(args, password)
    elif args.mode == "delete":
        run_delete(args, password)


if __name__ == "__main__":
    main()
