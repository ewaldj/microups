#!/usr/bin/env python3
"""
SNMP Interface Monitor  —  Cisco Router/Switch
pysnmp 7.x (asyncio API)
Features: Interface Description, Live Graph mit Zeitfenster-Auswahl
"""

import asyncio
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
import math
from datetime import datetime, timedelta
from collections import defaultdict, deque

# ── pysnmp 7.x ────────────────────────────────────────────────────────────────
try:
    from pysnmp.hlapi.v3arch.asyncio import (
        SnmpEngine, CommunityData, UsmUserData,
        UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity,
        get_cmd, next_cmd,
        usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol,
        usmHMAC128SHA224AuthProtocol, usmHMAC192SHA256AuthProtocol,
        usmDESPrivProtocol, usm3DESEDEPrivProtocol,
        usmAesCfb128Protocol, usmAesCfb192Protocol,
    )
    def isEndOfMib(vbs):
        return any(vb[1].__class__.__name__ in
                   ("EndOfMibView","NoSuchObject","NoSuchInstance")
                   for vb in vbs)
    PYSNMP_AVAILABLE = True
    _IMPORT_ERROR = ""
except ImportError as _e:
    PYSNMP_AVAILABLE = False
    _IMPORT_ERROR = str(_e)

# ── OIDs ──────────────────────────────────────────────────────────────────────
OID_SYSNAME          = "1.3.6.1.2.1.1.5.0"
OID_IF_DESCR         = "1.3.6.1.2.1.2.2.1.2"
OID_IF_ALIAS         = "1.3.6.1.2.1.31.1.1.1.18"   # ifAlias = Description
OID_IF_OPER_STATUS   = "1.3.6.1.2.1.2.2.1.8"
OID_IF_SPEED         = "1.3.6.1.2.1.2.2.1.5"
OID_IF_IN_OCTETS     = "1.3.6.1.2.1.2.2.1.10"
OID_IF_IN_UPKTS      = "1.3.6.1.2.1.2.2.1.11"
OID_IF_IN_ERRORS     = "1.3.6.1.2.1.2.2.1.14"
OID_IF_IN_DISCARDS   = "1.3.6.1.2.1.2.2.1.13"
OID_IF_OUT_OCTETS    = "1.3.6.1.2.1.2.2.1.16"
OID_IF_OUT_UPKTS     = "1.3.6.1.2.1.2.2.1.17"
OID_IF_OUT_ERRORS    = "1.3.6.1.2.1.2.2.1.20"
OID_IF_OUT_DISCARDS  = "1.3.6.1.2.1.2.2.1.19"
OID_IF_NAME          = "1.3.6.1.2.1.31.1.1.1.1"
OID_IF_HC_IN_OCT     = "1.3.6.1.2.1.31.1.1.1.6"
OID_IF_HC_OUT_OCT    = "1.3.6.1.2.1.31.1.1.1.10"
OID_IF_HC_IN_PKT     = "1.3.6.1.2.1.31.1.1.1.7"
OID_IF_HC_OUT_PKT    = "1.3.6.1.2.1.31.1.1.1.11"

STATUS_MAP = {1:"up",2:"down",3:"testing",4:"unknown",
              5:"dormant",6:"notPresent",7:"lowerLayerDown"}

AUTH_PROTOS = {
    "MD5":     usmHMACMD5AuthProtocol       if PYSNMP_AVAILABLE else None,
    "SHA":     usmHMACSHAAuthProtocol       if PYSNMP_AVAILABLE else None,
    "SHA-224": usmHMAC128SHA224AuthProtocol  if PYSNMP_AVAILABLE else None,
    "SHA-256": usmHMAC192SHA256AuthProtocol  if PYSNMP_AVAILABLE else None,
}
PRIV_PROTOS = {
    "DES":     usmDESPrivProtocol      if PYSNMP_AVAILABLE else None,
    "3DES":    usm3DESEDEPrivProtocol  if PYSNMP_AVAILABLE else None,
    "AES-128": usmAesCfb128Protocol    if PYSNMP_AVAILABLE else None,
    "AES-192": usmAesCfb192Protocol    if PYSNMP_AVAILABLE else None,
}

# Zeitfenster: Label -> Sekunden
TIME_WINDOWS = {
    "1 Minute":   60,
    "5 Minuten":  300,
    "15 Minuten": 900,
    "30 Minuten": 1800,
    "2 Stunden":  7200,
    "6 Stunden":  21600,
    "12 Stunden": 43200,
    "24 Stunden": 86400,
    "48 Stunden": 172800,
    "1 Woche":    604800,
}

# ── Farben ────────────────────────────────────────────────────────────────────
BG       = "#0d1117"
BG2      = "#161b22"
BG3      = "#21262d"
BG4      = "#1c2128"
ACCENT   = "#00d4aa"
ACCENT2  = "#0096ff"
TEXT     = "#e6edf3"
TEXT_DIM = "#8b949e"
GREEN    = "#3fb950"
RED      = "#f85149"
YELLOW   = "#d29922"
ORANGE   = "#db6d28"
BLUE     = "#0096ff"
FMONO    = ("Menlo", 9)
FUI      = ("Helvetica Neue", 10)
FHDR     = ("Helvetica Neue", 9, "bold")
FSMALL   = ("Helvetica Neue", 8)


# ── SNMP Helfer ───────────────────────────────────────────────────────────────
def _build_auth(cfg):
    if cfg["version"] == "v2c":
        return CommunityData(cfg["community"], mpModel=1)
    sec, u = cfg["security"], cfg["username"]
    if sec == "noAuthNoPriv":
        return UsmUserData(u)
    elif sec == "authNoPriv":
        return UsmUserData(u, authKey=cfg["auth_pass"],
                           authProtocol=AUTH_PROTOS[cfg["auth_proto"]])
    return UsmUserData(u, authKey=cfg["auth_pass"],
                       authProtocol=AUTH_PROTOS[cfg["auth_proto"]],
                       privKey=cfg["priv_pass"],
                       privProtocol=PRIV_PROTOS[cfg["priv_proto"]])


async def async_get(cfg, oid):
    engine = SnmpEngine()
    try:
        tr = await UdpTransportTarget.create(
            (cfg["host"], int(cfg["port"])),
            timeout=cfg["timeout"], retries=1)
        ei, es, _, vbs = await get_cmd(
            engine, _build_auth(cfg), tr, ContextData(),
            ObjectType(ObjectIdentity(oid)))
        if ei or es: return None
        return vbs[0][1] if vbs else None
    finally:
        engine.close_dispatcher()


async def async_walk(cfg, base_oid):
    results = {}
    engine  = SnmpEngine()
    try:
        tr = await UdpTransportTarget.create(
            (cfg["host"], int(cfg["port"])),
            timeout=cfg["timeout"], retries=1)
        cursor = [ObjectType(ObjectIdentity(base_oid))]
        while True:
            ei, es, _, vbs = await next_cmd(
                engine, _build_auth(cfg), tr, ContextData(), *cursor)
            if ei or es or not vbs: break
            if isEndOfMib(vbs):    break
            nxt, stop = [], False
            for vb in vbs:
                s = str(vb[0])
                if not s.startswith(base_oid + "."):
                    stop = True; break
                results[s[len(base_oid)+1:]] = vb[1]
                nxt.append(ObjectType(ObjectIdentity(s)))
            if stop or not nxt: break
            cursor = nxt
    finally:
        engine.close_dispatcher()
    return results


async def poll_device(cfg):
    sysname  = await async_get(cfg, OID_SYSNAME)
    if_names = await async_walk(cfg, OID_IF_NAME)
    if not if_names:
        if_names = await async_walk(cfg, OID_IF_DESCR)

    # ifAlias = Beschreibung die der Admin setzt
    if_alias  = await async_walk(cfg, OID_IF_ALIAS)
    if_descr  = await async_walk(cfg, OID_IF_DESCR)
    if_status = await async_walk(cfg, OID_IF_OPER_STATUS)
    if_speed  = await async_walk(cfg, OID_IF_SPEED)

    in_oct  = await async_walk(cfg, OID_IF_HC_IN_OCT)
    out_oct = await async_walk(cfg, OID_IF_HC_OUT_OCT)
    in_pkt  = await async_walk(cfg, OID_IF_HC_IN_PKT)
    out_pkt = await async_walk(cfg, OID_IF_HC_OUT_PKT)
    if not in_oct:
        in_oct  = await async_walk(cfg, OID_IF_IN_OCTETS)
        out_oct = await async_walk(cfg, OID_IF_OUT_OCTETS)
        in_pkt  = await async_walk(cfg, OID_IF_IN_UPKTS)
        out_pkt = await async_walk(cfg, OID_IF_OUT_UPKTS)

    in_err   = await async_walk(cfg, OID_IF_IN_ERRORS)
    out_err  = await async_walk(cfg, OID_IF_OUT_ERRORS)
    in_disc  = await async_walk(cfg, OID_IF_IN_DISCARDS)
    out_disc = await async_walk(cfg, OID_IF_OUT_DISCARDS)

    return dict(
        sysname  = str(sysname) if sysname else "",
        if_names = if_names, if_alias  = if_alias,
        if_descr = if_descr,  if_status = if_status,
        if_speed = if_speed,
        in_oct=in_oct, out_oct=out_oct, in_pkt=in_pkt, out_pkt=out_pkt,
        in_err=in_err, out_err=out_err, in_disc=in_disc, out_disc=out_disc,
    )


def safe_int(v, d=0):
    try: return int(v)
    except: return d

def _fmt_bps(b):
    if b >= 1e9: return f"{b/1e9:.2f} Gbps"
    if b >= 1e6: return f"{b/1e6:.2f} Mbps"
    if b >= 1e3: return f"{b/1e3:.1f} kbps"
    return f"{b:.0f} bps"

def _fmt_bps_short(b):
    if b >= 1e9: return f"{b/1e9:.1f}G"
    if b >= 1e6: return f"{b/1e6:.1f}M"
    if b >= 1e3: return f"{b/1e3:.0f}k"
    return f"{b:.0f}"

def _fmt_speed(s):
    if s == 0: return "—"
    if s >= 1_000_000_000: return f"{s//1_000_000_000}G"
    if s >= 1_000_000:     return f"{s//1_000_000}M"
    if s >= 1_000:         return f"{s//1_000}K"
    return str(s)


# ── Serien-Definition ─────────────────────────────────────────────────────────
# Jede Serie: (key, label, Linienfarbe, Füllfarbe, Formatfunktion, Y-Achse)
#   Y-Achse: "bps" -> Bit/s Skala,  "cnt" -> Count Skala (rechte Achse)
SERIES = [
    ("in_bps",   "▬ In Bit/s",   GREEN,      "#1a3a2a", "bps"),
    ("out_bps",  "▬ Out Bit/s",  ORANGE,     "#2a1a0a", "bps"),
    ("in_pps",   "▬ In Pkt/s",   "#64b5f6",  "#0a1a2a", "pps"),
    ("out_pps",  "▬ Out Pkt/s",  "#ffb74d",  "#2a1500", "pps"),
    ("in_err",   "▬ In Err/s",   "#e05ce0",  "#2a0a2a", "cnt"),
    ("out_err",  "▬ Out Err/s",  RED,        "#2a0a0a", "cnt"),
    ("in_disc",  "▬ In Disc/s",  "#5ce0e0",  "#0a2a2a", "cnt"),
    ("out_disc", "▬ Out Disc/s", YELLOW,     "#2a1a00", "cnt"),
]
SERIES_KEYS = [s[0] for s in SERIES]


# ── Graph Widget ──────────────────────────────────────────────────────────────
class InterfaceGraph(tk.Frame):
    """
    Canvas-Graph mit 6 Serien (In/Out Bit/s, Err/s, Disc/s),
    Zeitfenster-Auswahl und Ein/Aus-Checkboxen pro Serie.
    History: {if_idx: deque([(ts, in_bps, out_bps, in_err, out_err, in_disc, out_disc)])}
    """
    MAX_POINTS = 604800

    def __init__(self, master, **kw):
        super().__init__(master, bg=BG2, **kw)
        self.if_idx      = None
        self.if_name     = ""
        self.time_window = tk.StringVar(value="5 Minuten")
        self.history     = defaultdict(lambda: deque(maxlen=self.MAX_POINTS))

        # BooleanVar pro Serie (sichtbar/unsichtbar)
        self.series_vars = {key: tk.BooleanVar(value=(key in ("in_bps","out_bps")))
                            for key, *_ in SERIES}
        self._build()

    # ── GUI ───────────────────────────────────────────────────────────────────
    def _build(self):
        # ── Row 1: Interface-Name + Beschreibung ──
        hdr = tk.Frame(self, bg=BG3, height=30)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        self.lbl_name = tk.Label(hdr, text="Kein Interface ausgewählt",
                                  bg=BG3, fg=ACCENT,
                                  font=("Helvetica Neue",10,"bold"))
        self.lbl_name.pack(side="left", padx=12)
        self.lbl_desc = tk.Label(hdr, text="", bg=BG3, fg=TEXT_DIM, font=FUI)
        self.lbl_desc.pack(side="left", padx=4)

        # ── Row 2: Checkboxen + Zeitfenster ──
        ctrl = tk.Frame(self, bg=BG3, height=28)
        ctrl.pack(fill="x")
        ctrl.pack_propagate(False)

        # Zeitfenster rechts
        tk.Label(ctrl, text="Zeitfenster:", bg=BG3,
                 fg=TEXT_DIM, font=FSMALL).pack(side="right", padx=(0,4))
        cb = ttk.Combobox(ctrl, textvariable=self.time_window,
                          values=list(TIME_WINDOWS.keys()),
                          state="readonly", width=12, font=FSMALL)
        cb.pack(side="right", padx=(0,8))
        cb.bind("<<ComboboxSelected>>", lambda _: self._redraw())

        # Checkboxen links
        for key, label, color, _, _ in SERIES:
            var = self.series_vars[key]
            cb2 = tk.Checkbutton(ctrl, text=label, variable=var,
                                  command=self._redraw,
                                  bg=BG3, fg=color,
                                  selectcolor=BG3,
                                  activebackground=BG3,
                                  activeforeground=color,
                                  font=FSMALL,
                                  relief="flat", bd=0)
            cb2.pack(side="left", padx=6)

        # ── Canvas ──
        self.canvas = tk.Canvas(self, bg=BG2, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=2, pady=2)
        self.canvas.bind("<Configure>", lambda _: self._redraw())

        # ── Stats Bar ──
        sb = tk.Frame(self, bg=BG3, height=22)
        sb.pack(fill="x")
        sb.pack_propagate(False)
        self._stat_lbls = {}
        for key, label, color, _, _ in SERIES:
            short = label.replace("▬ ","").replace(" Bit/s","").replace("/s","")
            lbl = tk.Label(sb, text=f"{short}: —", bg=BG3,
                           fg=color, font=FSMALL)
            lbl.pack(side="left", padx=8)
            self._stat_lbls[key] = lbl

    # ── Public API ────────────────────────────────────────────────────────────
    def select_interface(self, if_idx, if_name, if_desc=""):
        self.if_idx  = if_idx
        self.if_name = if_name
        self.lbl_name.config(text=if_name if if_name else "Kein Interface ausgewählt")
        self.lbl_desc.config(text=f"  {if_desc}" if if_desc else "")
        self._redraw()

    def add_point(self, if_idx, ts, in_bps, out_bps,
                  in_pps=0.0, out_pps=0.0,
                  in_err=0.0, out_err=0.0, in_disc=0.0, out_disc=0.0):
        """Nur History befüllen — kein Tk-Call. Redraw erfolgt separat."""
        self.history[if_idx].append(
            (ts, in_bps, out_bps, in_pps, out_pps,
             in_err, out_err, in_disc, out_disc))

    def redraw_if_selected(self, if_idx):
        """Expliziter Redraw — nur aufrufen wenn im Main-Thread."""
        if if_idx == self.if_idx:
            self._redraw()

    # ── Data helpers ─────────────────────────────────────────────────────────
    def _window_pts(self):
        if self.if_idx is None:
            return []
        cutoff = time.time() - TIME_WINDOWS.get(self.time_window.get(), 300)
        return [p for p in self.history[self.if_idx] if p[0] >= cutoff]

    @staticmethod
    def _series_vals(pts, key):
        col = SERIES_KEYS.index(key)  # col 0=in_bps,1=out_bps,...
        return [p[col + 1] for p in pts]   # +1 because pts[0]=ts

    # ── Draw ─────────────────────────────────────────────────────────────────
    def _redraw(self):
        c = self.canvas
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 20 or H < 20:
            return

        PAD_L, PAD_T, PAD_B = 68, 14, 32

        pts = self._window_pts()
        if not pts or self.if_idx is None:
            c.create_text(W//2, H//2,
                          text="Wähle ein Interface in der Tabelle aus",
                          fill=TEXT_DIM, font=FUI)
            self._clear_stats()
            return

        secs  = TIME_WINDOWS.get(self.time_window.get(), 300)
        now   = time.time()
        t_min = now - secs

        # Aktive Serien nach Y-Achse trennen
        active_bps = [s for s in SERIES if self.series_vars[s[0]].get() and s[4]=="bps"]
        active_pps = [s for s in SERIES if self.series_vars[s[0]].get() and s[4]=="pps"]
        active_cnt = [s for s in SERIES if self.series_vars[s[0]].get() and s[4]=="cnt"]

        # Dynamisches PAD_R: Platz für cnt und/oder pps rechte Achsen
        has_cnt = bool(active_cnt)
        has_pps = bool(active_pps)
        PAD_R_DYN = 16 + (52 if has_cnt else 0) + (52 if has_pps else 0)

        GW = W - PAD_L - PAD_R_DYN
        GH = H - PAD_T - PAD_B

        c.create_rectangle(PAD_L, PAD_T, W-PAD_R_DYN, H-PAD_B,
                           fill=BG4, outline=BG3)

        # Y-Skala berechnen
        def calc_max(series_list):
            vals = []
            for s in series_list:
                vals += self._series_vals(pts, s[0])
            mx = max(vals) if vals else 0
            if mx <= 0: return 1.0
            mag = 10 ** math.floor(math.log10(mx))
            return math.ceil(mx / mag) * mag

        vmax_bps = calc_max(active_bps) if active_bps else 1.0
        vmax_pps = calc_max(active_pps) if active_pps else 1.0
        vmax_cnt = calc_max(active_cnt) if active_cnt else 1.0

        def tx(ts):
            return PAD_L + max(0, min(GW, (ts - t_min) / secs * GW))

        def ty_bps(v): return PAD_T + GH - (v / vmax_bps) * GH
        def ty_pps(v): return PAD_T + GH - (v / vmax_pps) * GH
        def ty_cnt(v): return PAD_T + GH - (v / vmax_cnt) * GH

        ty_map = {"bps": ty_bps, "pps": ty_pps, "cnt": ty_cnt}

        # ── Horizontale Grid-Linien (linke Achse = bps) ──
        n_h = 4
        for i in range(n_h + 1):
            v = vmax_bps * i / n_h
            y = ty_bps(v)
            c.create_line(PAD_L, y, W-PAD_R_DYN, y,
                          fill=BG3, width=1, dash=(3,4))
            c.create_text(PAD_L-4, y, text=_fmt_bps_short(v),
                          anchor="e", fill=TEXT_DIM, font=FSMALL)

        # Rechte Achse 1: pps (hellblau)
        x_pps = W - PAD_R_DYN + 4
        if has_pps:
            for i in range(n_h + 1):
                v   = vmax_pps * i / n_h
                y   = ty_pps(v)
                lbl = f"{v:.0f}" if v < 1000 else f"{v/1000:.1f}k"
                c.create_text(x_pps, y, text=lbl,
                              anchor="w", fill="#64b5f6", font=FSMALL)
            c.create_text(x_pps, PAD_T-2, text="Pkt/s",
                          anchor="sw", fill="#64b5f6", font=FSMALL)

        # Rechte Achse 2: cnt (versetzt wenn pps auch aktiv)
        x_cnt = W - PAD_R_DYN + 4 + (52 if has_pps else 0)
        if has_cnt:
            for i in range(n_h + 1):
                v   = vmax_cnt * i / n_h
                y   = ty_cnt(v)
                lbl = f"{v:.0f}" if v < 1000 else f"{v/1000:.1f}k"
                c.create_text(x_cnt, y, text=lbl,
                              anchor="w", fill=TEXT_DIM, font=FSMALL)
            c.create_text(x_cnt, PAD_T-2, text="Cnt/s",
                          anchor="sw", fill=TEXT_DIM, font=FSMALL)

        # ── Vertikale Zeit-Linien ──
        n_t = min(6, max(2, GW // 100))
        for i in range(n_t + 1):
            ts = t_min + secs * i / n_t
            x  = tx(ts)
            c.create_line(x, PAD_T, x, H-PAD_B,
                          fill=BG3, width=1, dash=(3,4))
            dt  = datetime.fromtimestamp(ts)
            lbl = dt.strftime("%H:%M") if secs <= 86400 else dt.strftime("%d.%m %H:%M")
            c.create_text(x, H-PAD_B+4, text=lbl,
                          anchor="n", fill=TEXT_DIM, font=FSMALL)

        # ── Serien zeichnen (Füllung zuerst, dann Linien) ──
        if len(pts) >= 2:
            for key, _, color, fill_col, yaxis in SERIES:
                if not self.series_vars[key].get():
                    continue
                ty_fn = ty_map[yaxis]
                vals  = self._series_vals(pts, key)
                poly  = [PAD_L, H-PAD_B]
                for i, p in enumerate(pts):
                    poly += [tx(p[0]), ty_fn(vals[i])]
                poly += [tx(pts[-1][0]), H-PAD_B]
                if len(poly) >= 6:
                    c.create_polygon(poly, fill=fill_col, outline="")

            for key, _, color, _, yaxis in SERIES:
                if not self.series_vars[key].get():
                    continue
                ty_fn  = ty_map[yaxis]
                vals   = self._series_vals(pts, key)
                coords = []
                for i, p in enumerate(pts):
                    coords += [tx(p[0]), ty_fn(vals[i])]
                if len(coords) >= 4:
                    c.create_line(*coords, fill=color, width=2, smooth=False)

        # ── Border ──
        c.create_rectangle(PAD_L, PAD_T, W-PAD_R_DYN, H-PAD_B,
                           outline=BG3, width=1)

        # Linke Achsen-Beschriftung
        if active_bps:
            c.create_text(PAD_L-2, PAD_T-2, text="Bit/s",
                          anchor="se", fill=TEXT_DIM, font=FSMALL)

        # ── Stats-Bar aktualisieren ──
        for key, _, color, _, yaxis in SERIES:
            vals = self._series_vals(pts, key)
            if vals and self.series_vars[key].get():
                last = vals[-1]
                mx   = max(vals)
                avg  = sum(vals) / len(vals)
                short = (key.replace("_bps","").replace("_pps","")
                            .replace("_err","err").replace("_disc","disc")
                            .replace("_"," "))
                if yaxis == "bps":
                    self._stat_lbls[key].config(
                        text=f"{short}: {_fmt_bps(last)}  max:{_fmt_bps(mx)}  avg:{_fmt_bps(avg)}")
                elif yaxis == "pps":
                    self._stat_lbls[key].config(
                        text=f"{short}: {last:.1f}p/s  max:{mx:.1f}  avg:{avg:.1f}")
                else:
                    self._stat_lbls[key].config(
                        text=f"{short}: {last:.1f}/s  max:{mx:.1f}  avg:{avg:.1f}")
            else:
                self._stat_lbls[key].config(text="")

    def _clear_stats(self):
        for lbl in self._stat_lbls.values():
            lbl.config(text="")


# ── Haupt-App ─────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SNMP Interface Monitor  —  Cisco")
        self.configure(bg=BG)
        self.minsize(1150, 750)
        self.resizable(True, True)

        self.running     = False
        self.poll_thread = None
        self.prev_data   = {}
        self.prev_time   = {}
        self.prev_errs   = {}
        self.poll_count  = 0
        self.device_name = tk.StringVar(value="—")
        # idx -> description cache
        self.if_desc_cache = {}

        self._style()
        self._ui()
        self.protocol("WM_DELETE_WINDOW", lambda: (
            setattr(self, "running", False), self.destroy()))

        if not PYSNMP_AVAILABLE:
            messagebox.showerror("Import-Fehler",
                f"pysnmp konnte nicht geladen werden:\n{_IMPORT_ERROR}\n\n"
                "Installation:\n  pip install pysnmp --break-system-packages")

    # ── Style ─────────────────────────────────────────────────────────────────
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=TEXT,
                    fieldbackground=BG3, font=FUI)
        for n, kw in [
            ("TFrame",           dict(background=BG)),
            ("TLabel",           dict(background=BG, foreground=TEXT)),
            ("TEntry",           dict(fieldbackground=BG3, foreground=TEXT,
                                      insertcolor=TEXT)),
            ("TCombobox",        dict(fieldbackground=BG3, foreground=TEXT,
                                      selectbackground=BG3, selectforeground=TEXT)),
            ("TLabelframe",          dict(background=BG, bordercolor=BG3)),
            ("TLabelframe.Label",    dict(background=BG, foreground=ACCENT,
                                          font=("Helvetica Neue",9,"bold"))),
            ("Start.TButton",        dict(background=ACCENT, foreground=BG,
                                          font=("Helvetica Neue",9,"bold"))),
            ("Stop.TButton",         dict(background=RED, foreground=TEXT,
                                          font=("Helvetica Neue",9,"bold"))),
            ("Neutral.TButton",      dict(background=BG3, foreground=TEXT)),
            ("Treeview",             dict(background=BG2, foreground=TEXT,
                                          fieldbackground=BG2, rowheight=22,
                                          font=FMONO)),
            ("Treeview.Heading",     dict(background=BG3, foreground=ACCENT,
                                          font=FHDR, relief="flat")),
            ("TNotebook",            dict(background=BG, borderwidth=0)),
            ("TNotebook.Tab",        dict(background=BG3, foreground=TEXT_DIM,
                                          padding=[12,4])),
            ("TPanedwindow",         dict(background=BG)),
            ("TSeparator",           dict(background=BG3)),
        ]:
            s.configure(n, **kw)
        s.map("TCombobox",
              fieldbackground=[("readonly",BG3)],
              selectbackground=[("readonly",BG3)])
        s.map("Treeview",
              background=[("selected",BG3)],
              foreground=[("selected",ACCENT)])
        s.map("TNotebook.Tab",
              background=[("selected",BG2)],
              foreground=[("selected",TEXT)])

    # ── UI ────────────────────────────────────────────────────────────────────
    def _ui(self):
        # Topbar
        tb = tk.Frame(self, bg=BG3, height=48)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        tk.Label(tb, text="⬡  SNMP Interface Monitor",
                 bg=BG3, fg=ACCENT,
                 font=("Helvetica Neue",13,"bold")).pack(side="left", padx=16, pady=10)
        tk.Label(tb, textvariable=self.device_name,
                 bg=BG3, fg=ACCENT2,
                 font=("Helvetica Neue",10,"bold")).pack(side="left", padx=8)
        self._sdot = tk.Label(tb, text="●", bg=BG3, fg=TEXT_DIM,
                              font=("Helvetica Neue",14))
        self._sdot.pack(side="right", padx=6)
        self._slbl = tk.Label(tb, text="Gestoppt", bg=BG3, fg=TEXT_DIM, font=FUI)
        self._slbl.pack(side="right")
        self._plbl = tk.Label(tb, text="Polls: 0", bg=BG3, fg=TEXT_DIM, font=FUI)
        self._plbl.pack(side="right", padx=16)

        # Horizontal pane: left config | right content
        h_pw = ttk.PanedWindow(self, orient="horizontal")
        h_pw.pack(fill="both", expand=True)

        lf = ttk.Frame(h_pw, width=300)
        lf.pack_propagate(False)
        h_pw.add(lf, weight=0)
        self._cfg_panel(lf)

        rf = ttk.Frame(h_pw)
        h_pw.add(rf, weight=1)

        # Vertical pane: top table | bottom graph
        v_pw = ttk.PanedWindow(rf, orient="vertical")
        v_pw.pack(fill="both", expand=True)

        top_frame = ttk.Frame(v_pw)
        v_pw.add(top_frame, weight=3)
        self._table_panel(top_frame)

        bot_frame = tk.Frame(v_pw, bg=BG2, height=220)
        v_pw.add(bot_frame, weight=2)
        self.graph = InterfaceGraph(bot_frame)
        self.graph.pack(fill="both", expand=True)

    # ── Config Panel ──────────────────────────────────────────────────────────
    def _cfg_panel(self, p):
        pad = {"padx":8,"pady":3}

        gf = ttk.LabelFrame(p, text="  GERÄT  ")
        gf.pack(fill="x", padx=8, pady=(10,4))
        self.e_host     = self._erow(gf, 0, "Host / IP",     "192.168.1.1", pad)
        self.e_port     = self._erow(gf, 1, "Port",          "161",         pad)
        self.e_timeout  = self._erow(gf, 2, "Timeout (s)",   "3",           pad)
        self.e_interval = self._erow(gf, 3, "Intervall (s)", "5",           pad)
        gf.columnconfigure(1, weight=1)

        vf = ttk.LabelFrame(p, text="  SNMP VERSION  ")
        vf.pack(fill="x", padx=8, pady=4)
        self.snmp_ver = tk.StringVar(value="v2c")
        for i, v in enumerate(("v2c","v3")):
            tk.Radiobutton(vf, text=f"SNMP{v}", variable=self.snmp_ver,
                           value=v, command=self._toggle_ver,
                           bg=BG, fg=TEXT, selectcolor=BG3,
                           activebackground=BG, activeforeground=ACCENT,
                           font=FUI).grid(row=0, column=i, padx=16, pady=6)

        self.frm_v2 = ttk.LabelFrame(p, text="  SNMPv2c  ")
        self.frm_v2.pack(fill="x", padx=8, pady=4)
        ttk.Label(self.frm_v2, text="Community").grid(
            row=0, column=0, sticky="w", **pad)
        self.e_community = ttk.Entry(self.frm_v2, width=18)
        self.e_community.insert(0, "public")
        self.e_community.grid(row=0, column=1, sticky="ew", **pad)
        self.frm_v2.columnconfigure(1, weight=1)

        self.frm_v3 = ttk.LabelFrame(p, text="  SNMPv3  ")
        self.frm_v3.pack(fill="x", padx=8, pady=4)
        self.e_v3 = {}
        for i, (lbl, val) in enumerate([("Username","snmpv3user"),
                                         ("Auth-Pass","authpass123"),
                                         ("Priv-Pass","privpass123")]):
            ttk.Label(self.frm_v3, text=lbl).grid(
                row=i, column=0, sticky="w", **pad)
            e = ttk.Entry(self.frm_v3, width=18,
                          show="*" if "Pass" in lbl else "")
            e.insert(0, val)
            e.grid(row=i, column=1, sticky="ew", **pad)
            self.e_v3[lbl] = e
        for i, (lbl, attr, vals, dflt) in enumerate([
            ("Security",  "cb_sec",  ["noAuthNoPriv","authNoPriv","authPriv"], "authPriv"),
            ("Auth Proto","cb_auth", list(AUTH_PROTOS.keys()),                 "SHA"),
            ("Priv Proto","cb_priv", list(PRIV_PROTOS.keys()),                 "AES-128"),
        ], start=3):
            ttk.Label(self.frm_v3, text=lbl).grid(
                row=i, column=0, sticky="w", **pad)
            cb = ttk.Combobox(self.frm_v3, width=16,
                              state="readonly", values=vals)
            cb.set(dflt)
            cb.grid(row=i, column=1, sticky="ew", **pad)
            setattr(self, attr, cb)
        self.cb_sec.bind("<<ComboboxSelected>>", self._toggle_v3)
        self.frm_v3.columnconfigure(1, weight=1)

        ff = ttk.LabelFrame(p, text="  FILTER  ")
        ff.pack(fill="x", padx=8, pady=4)
        ttk.Label(ff, text="Interface (leer = alle)").pack(
            anchor="w", padx=8, pady=(4,0))
        self.e_filter = ttk.Entry(ff)
        self.e_filter.pack(fill="x", padx=8, pady=(2,4))
        self.var_skip_down = tk.BooleanVar(value=True)
        tk.Checkbutton(ff, text="Down-Interfaces ausblenden",
                       variable=self.var_skip_down,
                       bg=BG, fg=TEXT, selectcolor=BG3,
                       activebackground=BG, activeforeground=ACCENT,
                       font=FUI).pack(anchor="w", padx=8, pady=(0,6))

        bf = tk.Frame(p, bg=BG)
        bf.pack(fill="x", padx=8, pady=8)
        self.btn_start = ttk.Button(bf, text="▶  Start",
            style="Start.TButton", command=self._start)
        self.btn_start.pack(fill="x", pady=2)
        self.btn_stop = ttk.Button(bf, text="■  Stop",
            style="Stop.TButton", command=self._stop, state="disabled")
        self.btn_stop.pack(fill="x", pady=2)
        ttk.Button(bf, text="↺  Einmalig abfragen",
            style="Neutral.TButton", command=self._once).pack(fill="x", pady=2)
        ttk.Button(bf, text="✕  Tabelle leeren",
            style="Neutral.TButton", command=self._clear).pack(fill="x", pady=2)

        self._toggle_ver()
        self._toggle_v3()

    @staticmethod
    def _erow(frame, row, label, default, pad):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", **pad)
        e = ttk.Entry(frame, width=20)
        e.insert(0, default)
        e.grid(row=row, column=1, sticky="ew", **pad)
        return e

    # ── Table Panel ───────────────────────────────────────────────────────────
    def _table_panel(self, p):
        nb = ttk.Notebook(p)
        nb.pack(fill="both", expand=True, padx=4, pady=4)

        tl = ttk.Frame(nb)
        nb.add(tl, text="  📊  Interface Stats  ")

        cols = ("if_idx","name","description","status","speed",
                "in_bps","out_bps","in_pps","out_pps",
                "in_err","out_err","in_disc","out_disc","updated")
        self.tree = ttk.Treeview(tl, columns=cols,
                                  show="headings", selectmode="browse")
        for c, (t, w) in {
            "if_idx":     ("Idx",    42),
            "name":       ("Interface", 140),
            "description":("Description", 180),
            "status":     ("Status",  60),
            "speed":      ("Speed",   68),
            "in_bps":     ("In Bit/s", 96),
            "out_bps":    ("Out Bit/s",96),
            "in_pps":     ("In Pkt/s", 82),
            "out_pps":    ("Out Pkt/s",82),
            "in_err":     ("In Err",   64),
            "out_err":    ("Out Err",  64),
            "in_disc":    ("In Disc",  64),
            "out_disc":   ("Out Disc", 64),
            "updated":    ("Zeit",     68),
        }.items():
            self.tree.heading(c, text=t, command=lambda x=c: self._sort(x))
            self.tree.column(c, width=w, minwidth=36, anchor="center")
        self.tree.column("name",        anchor="w")
        self.tree.column("description", anchor="w")

        for tag, fg in [("up",GREEN),("down",RED),
                         ("other",YELLOW),("errors",ORANGE)]:
            self.tree.tag_configure(tag, foreground=fg)

        vsb = ttk.Scrollbar(tl, orient="vertical",   command=self.tree.yview)
        hsb = ttk.Scrollbar(tl, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        hsb.pack(side="bottom", fill="x")
        vsb.pack(side="right",  fill="y")
        self.tree.pack(fill="both", expand=True)

        # Klick auf Row -> Graph aktualisieren
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

        # Tab Log
        tlog = ttk.Frame(nb)
        nb.add(tlog, text="  📋  Log  ")
        ttk.Button(tlog, text="Log leeren", style="Neutral.TButton",
                   command=lambda: self.log.delete("1.0","end")).pack(
                       anchor="e", padx=6, pady=4)
        self.log = scrolledtext.ScrolledText(
            tlog, bg=BG2, fg=TEXT_DIM, font=("Menlo",9),
            insertbackground=TEXT, relief="flat",
            borderwidth=0, state="disabled")
        self.log.pack(fill="both", expand=True, padx=4, pady=(0,4))
        for tag, fg in [("info",ACCENT2),("ok",GREEN),
                         ("warn",YELLOW),("error",RED),("dim",TEXT_DIM)]:
            self.log.tag_configure(tag, foreground=fg)

    def _on_row_select(self, _event=None):
        sel = self.tree.selection()
        if not sel: return
        vals = self.tree.item(sel[0])["values"]
        if not vals: return
        idx  = str(vals[0])
        name = str(vals[1])
        desc = str(vals[2]) if vals[2] else ""
        self.graph.select_interface(idx, name, desc)

    # ── Toggle ────────────────────────────────────────────────────────────────
    def _toggle_ver(self):
        if self.snmp_ver.get() == "v2c":
            self.frm_v3.pack_forget()
            self.frm_v2.pack(fill="x", padx=8, pady=4)
        else:
            self.frm_v2.pack_forget()
            self.frm_v3.pack(fill="x", padx=8, pady=4)

    def _toggle_v3(self, *_):
        sec = self.cb_sec.get()
        sa  = "normal" if sec in ("authNoPriv","authPriv") else "disabled"
        sp  = "normal" if sec == "authPriv" else "disabled"
        for w in (self.e_v3["Auth-Pass"], self.cb_auth): w.configure(state=sa)
        for w in (self.e_v3["Priv-Pass"], self.cb_priv): w.configure(state=sp)

    # ── Config ────────────────────────────────────────────────────────────────
    def _cfg(self):
        try:    to = float(self.e_timeout.get())
        except: to = 3.0
        return {
            "host":      self.e_host.get().strip(),
            "port":      self.e_port.get().strip() or "161",
            "timeout":   to,
            "version":   self.snmp_ver.get(),
            "community": self.e_community.get().strip(),
            "username":  self.e_v3["Username"].get().strip(),
            "auth_pass": self.e_v3["Auth-Pass"].get(),
            "priv_pass": self.e_v3["Priv-Pass"].get(),
            "security":  self.cb_sec.get(),
            "auth_proto":self.cb_auth.get(),
            "priv_proto":self.cb_priv.get(),
        }

    # ── Polling ───────────────────────────────────────────────────────────────
    def _start(self):
        if not PYSNMP_AVAILABLE:
            messagebox.showerror("Fehler","pysnmp nicht geladen!")
            return
        if self.running: return
        self.running = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._setstatus("Läuft", ACCENT)
        self._log("Polling gestartet.", "info")
        self.poll_thread = threading.Thread(target=self._loop, daemon=True)
        self.poll_thread.start()

    def _stop(self):
        self.running = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self._setstatus("Gestoppt", TEXT_DIM)
        self._log("Polling gestoppt.", "warn")

    def _once(self):
        if not PYSNMP_AVAILABLE:
            messagebox.showerror("Fehler","pysnmp nicht geladen!")
            return
        threading.Thread(target=self._poll, daemon=True).start()

    def _loop(self):
        while self.running:
            self._poll()
            try:    iv = float(self.e_interval.get())
            except: iv = 5.0
            for _ in range(int(iv * 10)):
                if not self.running: return
                time.sleep(0.1)

    def _poll(self):
        cfg = self._cfg()
        if not cfg["host"]:
            self._log("Kein Host angegeben!", "error")
            return
        self._log(f"Abfrage {cfg['host']} SNMP{cfg['version']} ...", "dim")
        # Tk-Widget-Werte JETZT lesen (noch im Main-Thread via _loop→sleep→hier)
        # _poll wird aus threading.Thread aufgerufen → muss Tk-Reads vermeiden.
        # Daher: Filter-Werte werden als Snapshot an _process übergeben.
        try:
            flt       = self.e_filter.get().strip().lower()
            skip_down = self.var_skip_down.get()
        except Exception:
            flt, skip_down = "", True
        try:
            data = asyncio.run(poll_device(cfg))
        except Exception as exc:
            self._log(f"Fehler: {exc}", "error")
            self._setstatus("Fehler", RED)
            return
        self._process(data, flt, skip_down)

    # ── Verarbeitung ──────────────────────────────────────────────────────────
    def _process(self, data, flt="", skip_down=True):
        """
        Läuft im Worker-Thread.
        Alle Berechnungen hier, KEINE direkten Tk-Aufrufe.
        Tk-Updates nur via self.after(0, ...).
        """
        now = time.time()

        # Sysname — sicher via after
        if data["sysname"]:
            n = data["sysname"]
            self.after(0, lambda: self.device_name.set(n))

        rows        = []   # Tabellen-Daten
        graph_pts   = []   # (idx, ts, in_bps, out_bps, ipps, opps, ie_r, oe_r, id_r, od_r)

        for idx, raw in data["if_names"].items():
            name = str(raw)
            if flt and flt not in name.lower():
                continue
            oper = safe_int(data["if_status"].get(idx, 2))
            if skip_down and oper != 1:
                continue

            alias       = str(data["if_alias"].get(idx, "")).strip()
            descr       = str(data["if_descr"].get(idx, "")).strip()
            description = alias if alias else descr
            self.if_desc_cache[idx] = description

            curr = {
                "io": safe_int(data["in_oct"].get(idx,  0)),
                "oo": safe_int(data["out_oct"].get(idx, 0)),
                "ip": safe_int(data["in_pkt"].get(idx,  0)),
                "op": safe_int(data["out_pkt"].get(idx, 0)),
            }
            ibps = obps = ipps = opps = 0.0
            prev  = self.prev_data.get(idx)
            tprev = self.prev_time.get(idx)
            if prev and tprev:
                dt = now - tprev
                if dt > 0:
                    ibps = max(0, (curr["io"] - prev["io"]) * 8 / dt)
                    obps = max(0, (curr["oo"] - prev["oo"]) * 8 / dt)
                    ipps = max(0, (curr["ip"] - prev["ip"]) / dt)
                    opps = max(0, (curr["op"] - prev["op"]) / dt)
            self.prev_data[idx] = curr
            self.prev_time[idx] = now

            ie  = safe_int(data["in_err"].get(idx,  0))
            oe  = safe_int(data["out_err"].get(idx, 0))
            idv = safe_int(data["in_disc"].get(idx, 0))
            odv = safe_int(data["out_disc"].get(idx, 0))

            ie_rate = oe_rate = id_rate = od_rate = 0.0
            prev_e = self.prev_errs.get(idx)
            if prev_e and tprev:
                dt2 = now - tprev
                if dt2 > 0:
                    ie_rate = max(0, (ie  - prev_e["ie"])  / dt2)
                    oe_rate = max(0, (oe  - prev_e["oe"])  / dt2)
                    id_rate = max(0, (idv - prev_e["idv"]) / dt2)
                    od_rate = max(0, (odv - prev_e["odv"]) / dt2)
            self.prev_errs[idx] = {"ie": ie, "oe": oe, "idv": idv, "odv": odv}

            # Graph-Punkt sammeln (kein Tk-Call!)
            graph_pts.append((idx, now, ibps, obps, ipps, opps,
                               ie_rate, oe_rate, id_rate, od_rate))

            tag = "up" if oper == 1 else "down" if oper == 2 else "other"
            if ie > 0 or oe > 0:
                tag = "errors"

            rows.append(dict(
                idx=idx, name=name,
                description=description,
                status=STATUS_MAP.get(oper, str(oper)),
                speed=_fmt_speed(safe_int(data["if_speed"].get(idx, 0))),
                in_bps=_fmt_bps(ibps),  out_bps=_fmt_bps(obps),
                in_pps=f"{ipps:.1f}",   out_pps=f"{opps:.1f}",
                in_err=str(ie),  out_err=str(oe),
                in_disc=str(idv), out_disc=str(odv),
                updated=datetime.now().strftime("%H:%M:%S"),
                tag=tag,
            ))

        self.poll_count += 1

        # ── Alle Tk-Updates gebündelt via after(0) ──────────────────────────
        def _tk_update():
            # Graph-Punkte eintragen (nur history-append, kein Tk-Call in add_point)
            updated_idxs = set()
            for pt in graph_pts:
                self.graph.add_point(*pt)
                updated_idxs.add(pt[0])
            # Einmaliger Redraw wenn das aktive Interface dabei war
            if self.graph.if_idx in updated_idxs:
                self.graph._redraw()
            # Tabelle aktualisieren
            self._update(rows)
            # Poll-Counter
            self._plbl.config(text=f"Polls: {self.poll_count}")

        self.after(0, _tk_update)
        self._log(f"OK - {len(rows)} Interface(s) @ "
                  f"{datetime.now().strftime('%H:%M:%S')}", "ok")

    def _update(self, rows):
        existing = {self.tree.item(i)["values"][0]: i
                    for i in self.tree.get_children()}
        for r in rows:
            vals = (r["idx"], r["name"], r["description"],
                    r["status"], r["speed"],
                    r["in_bps"], r["out_bps"],
                    r["in_pps"], r["out_pps"],
                    r["in_err"], r["out_err"],
                    r["in_disc"], r["out_disc"],
                    r["updated"])
            if r["idx"] in existing:
                self.tree.item(existing[r["idx"]], values=vals, tags=(r["tag"],))
            else:
                self.tree.insert("", "end", values=vals, tags=(r["tag"],))
        cur = {r["idx"] for r in rows}
        for iid, tiid in list(existing.items()):
            if iid not in cur:
                self.tree.delete(tiid)

    def _clear(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        self.prev_data.clear()
        self.prev_time.clear()
        self.prev_errs.clear()
        self.if_desc_cache.clear()
        self.poll_count = 0
        self._plbl.config(text="Polls: 0")
        self.device_name.set("—")
        self.graph.history.clear()
        self.graph.select_interface(None, "Kein Interface ausgewählt")
        self._log("Tabelle geleert.", "dim")

    _sort_rev = defaultdict(bool)

    def _sort(self, col):
        rev  = self._sort_rev[col]
        data = [(self.tree.set(k, col), k)
                for k in self.tree.get_children("")]
        try:
            def key(t):
                v = (t[0].replace("Gbps","e9").replace("Mbps","e6")
                         .replace("kbps","e3").replace("bps","")
                         .replace("G","e9").replace("M","e6")
                         .replace("K","e3").replace("—","0").strip())
                return float(v) if v else 0.0
            data.sort(key=key, reverse=rev)
        except ValueError:
            data.sort(reverse=rev)
        for i, (_, k) in enumerate(data): self.tree.move(k, "", i)
        self._sort_rev[col] = not rev

    def _log(self, msg, level="info"):
        def _a():
            self.log.configure(state="normal")
            p = {"info":"i","ok":"v","warn":"!","error":"x","dim":"."}
            self.log.insert("end",
                f"[{datetime.now().strftime('%H:%M:%S')}]"
                f" {p.get(level,'.')} {msg}\n", level)
            self.log.see("end")
            self.log.configure(state="disabled")
        self.after(0, _a)

    def _setstatus(self, text, color):
        self.after(0, lambda: [
            self._slbl.config(text=text, fg=color),
            self._sdot.config(fg=color)])


if __name__ == "__main__":
    App().mainloop()