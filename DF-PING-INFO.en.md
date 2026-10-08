# DF-PING-INFO – Ping with the DF bit set (Don't Fragment)

Cheat sheet for testing path MTU with a ping that has the DF bit set.
Covers Linux, Windows, macOS, BSD, ESXi and common network operating systems.

Last updated: 2026-10-07

---

## 1. Basics: payload vs. packet size

For a 1500-byte IPv4 packet:

```
1500-byte IP packet = 20-byte IPv4 header + 8-byte ICMP header + 1472-byte payload
```

| Protocol | IP header | ICMP header | Payload for a 1500-byte packet |
|----------|-----------|-------------|--------------------------------|
| IPv4     | 20 bytes  | 8 bytes     | **1472**                       |
| IPv6     | 40 bytes  | 8 bytes     | **1452**                       |

**Important:** In most tools (Linux, Windows, macOS, BSD, Juniper, Huawei, Arista) the size
option (`-s` / `-l` / `size`) specifies the **payload only**.
On **Cisco IOS / IOS-XE / NX-OS** and **MikroTik**, `size` is the **total size of the IP packet**
(i.e. simply `1500`).

Rule of thumb: if payload 1472 works with DF set but 1473 does not, the path MTU is 1500.

---

## 2. Commands per operating system (IPv4, 1500-byte packet)

| System | Command |
|--------|---------|
| **Linux (iputils)** | `ping -M do -s 1472 <target>` |
| **Windows (cmd/PowerShell)** | `ping -f -l 1472 <target>` |
| **Windows PowerShell 7+** | `Test-Connection <target> -DontFragment -BufferSize 1472 -Count 4` |
| **macOS** | `ping -D -s 1472 <target>` |
| **FreeBSD / OpenBSD** | `ping -D -s 1472 <target>` |
| **VMware ESXi** | `vmkping -d -s 1472 <target>` (optionally `-I vmkX`) |
| **Cisco IOS / IOS-XE** | `ping <target> size 1500 df-bit` |
| **Cisco NX-OS** | `ping <target> packet-size 1500 df-bit` |
| **Cisco IOS-XR** | `ping <target> size 1500 donot-frag` (syntax varies by release, otherwise use extended ping) |
| **Cisco ASA** | no DF parameter on `ping`; test from a neighboring device |
| **Juniper Junos** | `ping <target> size 1472 do-not-fragment` |
| **Arista EOS** | `ping <target> size 1472 df-bit` |
| **Huawei VRP** | `ping -f -s 1472 <target>` |
| **MikroTik RouterOS** | `/ping <target> size=1500 do-not-fragment` |
| **Fortinet FortiOS** | `execute ping-options data-size 1472` + `execute ping-options df-bit yes` + `execute ping <target>` |

### Limiting the count

```bash
ping -c 4 -M do -s 1472 <target>      # Linux / macOS (macOS: -D instead of -M do)
ping -n 4 -f -l 1472 <target>         # Windows
```

---

## 3. IPv6

With IPv6, routers never fragment, and there is no DF bit. Only the sender may fragment.
Oversized packets are answered with ICMPv6 "Packet Too Big". Payload for 1500 bytes: **1452**.

| System | Command |
|--------|---------|
| **Linux** | `ping -6 -M do -s 1452 <target>` |
| **Windows** | `ping -6 -l 1452 <target>` |
| **macOS** | `ping6 -D -s 1452 <target>` |
| **FreeBSD** | `ping6 -D -s 1452 <target>` |
| **Cisco IOS** | `ping ipv6 <target> size 1500` |

Note: ICMPv6 "Packet Too Big" must not be filtered anywhere, otherwise path MTU discovery breaks.

---

## 4. Linux: there are several ping implementations

On Linux, `ping` is not always the same `ping`.

| Implementation | Found on | Can set the DF bit? |
|----------------|----------|---------------------|
| **iputils-ping** | Debian, Ubuntu, RHEL/Rocky/Alma, Fedora, SUSE (default) | **Yes:** `-M do` |
| **inetutils-ping** (GNU) | minimal installs, some Arch setups | **No**, no `-M` option |
| **BusyBox ping** | Alpine, embedded, containers, router firmware | **No**, only `-s` for the size |
| **BSD ping** | rarely on Linux | `-D` |

### Finding out which version is installed

```bash
ping -V                      # iputils: "ping from iputils 20221126"
type -a ping
ls -l "$(command -v ping)"   # BusyBox: symlink to /bin/busybox
ping -h 2>&1 | head -5       # show available options
```

### What does NOT work on Linux

| Attempt | Result |
|---------|--------|
| `ping -f -l 1472 <target>` (Windows syntax) | `-f` = **flood ping** (root only), `-l` = preload. **No DF!** Can flood the target. |
| `ping -D -s 1472 <target>` (macOS/BSD syntax) | In iputils `-D` means "print timestamps", **not DF**. The ping runs without a DF guarantee. |
| `ping -M do` on BusyBox / inetutils | `invalid option` or `unrecognized option` |
| `ping -s 1500 -M do <target>` | The packet is 1528 bytes and is rejected locally: `ping: local error: message too long, mtu=1500` |
| `ping -s 1472 <target>` **without** `-M do` | Linux defaults to `-M want`: DF is set, but if the MTU is too small the packet is fragmented locally. The result is misleading ("works") although the path does not carry that size unfragmented. |
| `ping -M do` as a normal user without privileges | In containers without `CAP_NET_RAW` or with a restrictive `net.ipv4.ping_group_range`, ping fails entirely (`Operation not permitted`). |

### `-M` options (iputils)

| Value | Meaning |
|-------|---------|
| `do` | Set DF, never fragment (use this for MTU tests) |
| `want` | Path MTU discovery, fragment if necessary (default) |
| `dont` | Do not set DF |
| `probe` | Set DF, but ignore the known path MTU (newer iputils) |

### Typical Linux output

```
ping: local error: message too long, mtu=1500        -> local interface MTU too small
From 10.0.0.1 icmp_seq=1 Frag needed and DF set (mtu = 1400)   -> router reports MTU 1400
(no reply, 100% loss)                                -> ICMP "Frag needed" is filtered (blackhole)
```

---

## 5. Alternatives if `ping` cannot set DF (or for cross-checking)

### tracepath (iputils) – discovers the path MTU automatically

```bash
tracepath -n <target>
tracepath -n -m 15 <target>
tracepath -6 <target>
```

The output contains e.g. `pmtu 1500`, and `pmtu 1400` at a bottleneck.

### traceroute (modern, Linux)

```bash
traceroute -n --mtu <target>        # sets DF and shows the MTU at bottlenecks
traceroute -n -F <target> 1500      # -F = DF, 1500 = total packet size
```

### fping

```bash
fping -M -b 1472 -c 3 <target>      # -M = set DF, -b = payload size
```

### hping3 (requires root)

```bash
hping3 -1 -y -d 1472 -c 3 <target>  # -1 = ICMP, -y = DF, -d = payload size
```

### nping (Nmap package, requires root)

```bash
nping --icmp --df --data-length 1472 -c 3 <target>
```

### Alpine / BusyBox: install a full-featured ping

```bash
apk add iputils
```

### Debian/Ubuntu: iputils instead of inetutils

```bash
apt install iputils-ping
```

### Show local MTU and cached path MTU

```bash
ip link show                      # interface MTUs
ip route get <target>             # may show "mtu 1400" from the path MTU cache
```

### Windows

```powershell
netsh interface ipv4 show subinterfaces     # interface MTUs
Test-Connection <target> -DontFragment -BufferSize 1472   # PowerShell 7+ only
```

Windows PowerShell 5.1 has no DF option in `Test-Connection`; use `ping -f -l` there.

---

## 6. Finding the largest working payload (Linux)

```bash
#!/usr/bin/env bash
# df-ping-find-mtu.sh <target>  - finds the maximum payload via binary search (IPv4, iputils)
target="$1"
lo=0; hi=1472
while [ "$lo" -lt "$hi" ]; do
  mid=$(( (lo + hi + 1) / 2 ))
  if ping -c 1 -W 1 -M do -s "$mid" "$target" >/dev/null 2>&1; then
    lo=$mid
  else
    hi=$(( mid - 1 ))
  fi
done
echo "Max payload: $lo bytes  ->  path MTU: $(( lo + 28 )) bytes"
```

For larger MTUs (jumbo frames), raise `hi` accordingly, e.g. `hi=8972` (MTU 9000).

---

## 7. Common test sizes

| Target MTU | IPv4 payload (`-s` / `-l`) | IPv6 payload | Cisco IOS `size` |
|------------|----------------------------|--------------|------------------|
| 1500       | 1472                       | 1452         | 1500             |
| 1492 (PPPoE) | 1464                     | 1444         | 1492             |
| 1400       | 1372                       | 1352         | 1400             |
| 9000 (jumbo) | 8972                     | 8952         | 9000             |
| 9216 (jumbo switch) | 9188              | 9168         | 9216             |

---

## 8. Notes for overlays/fabrics (VXLAN, MPLS, IPsec, MACsec)

Additional header overhead (approximate):

| Technology | Overhead |
|------------|----------|
| VXLAN (IPv4 underlay) | approx. 50 bytes |
| MPLS per label | 4 bytes |
| MACsec | approx. 32 bytes |
| GRE | 24 bytes |
| IPsec (ESP, tunnel mode) | approx. 50–73 bytes, depending on the algorithms |
| PPPoE | 8 bytes |

For a 1500-byte packet to pass through the overlay unfragmented, the underlay MTU must be
correspondingly larger (e.g. 1600 or jumbo 9216). Test with a DF ping from VM to VM or host to host
across the overlay, then cross-check with a DF ping between the underlay loopbacks or on the transit links.

---

## 9. Troubleshooting – interpreting results

| Observation | Possible cause |
|-------------|----------------|
| Reply at 1472, none at 1473 | Path MTU = 1500, everything is fine |
| "needs to be fragmented" / "Frag needed" message | A hop with a smaller MTU; the message usually states the value |
| Small pings work, large ones do not, **no** error message | ICMP "Fragmentation needed" is being filtered (PMTUD blackhole) → check firewall/ACL, consider TCP MSS clamping |
| Windows: "Request timed out" at large sizes | As above, or the target does not answer large ICMP packets |
| Cisco IOS: character `M` | "could not fragment": DF set and MTU too small |
| Cisco IOS: character `.` | Timeout |
| Cisco IOS: character `!` | Reply received |

---

## Sources and notes

- Syntax on network devices can differ between releases. Use `?` in the CLI if something deviates.
- The Linux information refers to iputils (e.g. 20221126 and newer).
