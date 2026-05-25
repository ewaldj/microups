#!/usr/bin/env python3
import re
import sys
import argparse
import json
from typing import Optional, Tuple, Dict, Any

# --- LTE Bandtabelle (wie zuvor, FDD/TDD/SDL) ---

BANDS_LTE: Dict[int, Dict[str, Any]] = {
    1:  {"type": "FDD", "FDL_low": 2110.0, "NDL_off": 0,    "FUL_low": 1920.0, "NUL_off": 18000},
    2:  {"type": "FDD", "FDL_low": 1930.0, "NDL_off": 600,  "FUL_low": 1850.0, "NUL_off": 18600},
    3:  {"type": "FDD", "FDL_low": 1805.0, "NDL_off": 1200, "FUL_low": 1710.0, "NUL_off": 19200},
    4:  {"type": "FDD", "FDL_low": 2110.0, "NDL_off": 1950, "FUL_low": 1710.0, "NUL_off": 19950},
    5:  {"type": "FDD", "FDL_low": 869.0,  "NDL_off": 2400, "FUL_low": 824.0,  "NUL_off": 20400},
    6:  {"type": "FDD", "FDL_low": 875.0,  "NDL_off": 2650, "FUL_low": 830.0,  "NUL_off": 20650},
    7:  {"type": "FDD", "FDL_low": 2620.0, "NDL_off": 2750, "FUL_low": 2500.0, "NUL_off": 20750},
    8:  {"type": "FDD", "FDL_low": 925.0,  "NDL_off": 3450, "FUL_low": 880.0,  "NUL_off": 21450},
    9:  {"type": "FDD", "FDL_low": 1844.9, "NDL_off": 3800, "FUL_low": 1749.9, "NUL_off": 21800},
    10: {"type": "FDD", "FDL_low": 2110.0, "NDL_off": 4150, "FUL_low": 1710.0, "NUL_off": 22150},
    11: {"type": "FDD", "FDL_low": 1475.9, "NDL_off": 4750, "FUL_low": 1427.9, "NUL_off": 22750},
    12: {"type": "FDD", "FDL_low": 729.0,  "NDL_off": 5000, "FUL_low": 699.0,  "NUL_off": 23000},
    13: {"type": "FDD", "FDL_low": 746.0,  "NDL_off": 5180, "FUL_low": 777.0,  "NUL_off": 23180},
    14: {"type": "FDD", "FDL_low": 758.0,  "NDL_off": 5280, "FUL_low": 788.0,  "NUL_off": 23280},
    17: {"type": "FDD", "FDL_low": 734.0,  "NDL_off": 5730, "FUL_low": 704.0,  "NUL_off": 23730},
    18: {"type": "FDD", "FDL_low": 860.0,  "NDL_off": 5850, "FUL_low": 815.0,  "NUL_off": 23850},
    19: {"type": "FDD", "FDL_low": 875.0,  "NDL_off": 6000, "FUL_low": 830.0,  "NUL_off": 24000},
    20: {"type": "FDD", "FDL_low": 791.0,  "NDL_off": 6150, "FUL_low": 832.0,  "NUL_off": 24150},
    21: {"type": "FDD", "FDL_low": 1495.9, "NDL_off": 6450, "FUL_low": 1447.9, "NUL_off": 24450},
    22: {"type": "FDD", "FDL_low": 3510.0, "NDL_off": 6600, "FUL_low": 3410.0, "NUL_off": 24600},
    23: {"type": "FDD", "FDL_low": 2180.0, "NDL_off": 7500, "FUL_low": 2000.0, "NUL_off": 25500},
    24: {"type": "FDD", "FDL_low": 1525.0, "NDL_off": 7700, "FUL_low": 1626.5,"NUL_off": 25700},
    25: {"type": "FDD", "FDL_low": 1930.0, "NDL_off": 8040, "FUL_low": 1850.0, "NUL_off": 26040},
    26: {"type": "FDD", "FDL_low": 859.0,  "NDL_off": 8690, "FUL_low": 814.0,  "NUL_off": 26690},
    27: {"type": "FDD", "FDL_low": 852.0,  "NDL_off": 9040, "FUL_low": 807.0,  "NUL_off": 27040},
    28: {"type": "FDD", "FDL_low": 758.0,  "NDL_off": 9210, "FUL_low": 703.0,  "NUL_off": 27210},
    30: {"type": "FDD", "FDL_low": 2350.0, "NDL_off": 9870, "FUL_low": 2305.0, "NUL_off": 27660},
    31: {"type": "FDD", "FDL_low": 462.5,  "NDL_off": 9920, "FUL_low": 452.5,  "NUL_off": 27660},
    29: {"type": "SDL", "FDL_low": 717.0, "NDL_off": 9770},
    32: {"type": "SDL", "FDL_low": 1452.0, "NDL_off": 9920},
    33: {"type": "TDD", "FDL_low": 1900.0, "NDL_off": 36000},
    34: {"type": "TDD", "FDL_low": 2010.0, "NDL_off": 36200},
    35: {"type": "TDD", "FDL_low": 1850.0, "NDL_off": 36350},
    36: {"type": "TDD", "FDL_low": 1930.0, "NDL_off": 36950},
    37: {"type": "TDD", "FDL_low": 1910.0, "NDL_off": 37550},
    38: {"type": "TDD", "FDL_low": 2570.0, "NDL_off": 37750},
    39: {"type": "TDD", "FDL_low": 1880.0, "NDL_off": 38250},
    40: {"type": "TDD", "FDL_low": 2300.0, "NDL_off": 38650},
    41: {"type": "TDD", "FDL_low": 2496.0, "NDL_off": 39650},
    42: {"type": "TDD", "FDL_low": 3400.0, "NDL_off": 41590},
    43: {"type": "TDD", "FDL_low": 3600.0, "NDL_off": 43590},
    44: {"type": "TDD", "FDL_low": 703.0,  "NDL_off": 45590},
    45: {"type": "TDD", "FDL_low": 1447.0, "NDL_off": 46590},
    46: {"type": "TDD", "FDL_low": 5150.0, "NDL_off": 46790},
    47: {"type": "TDD", "FDL_low": 5855.0, "NDL_off": 54590},
    48: {"type": "TDD", "FDL_low": 3550.0, "NDL_off": 55240},
    49: {"type": "TDD", "FDL_low": 3550.0, "NDL_off": 56740},
    50: {"type": "TDD", "FDL_low": 1432.0, "NDL_off": 58240},
    51: {"type": "TDD", "FDL_low": 1427.0, "NDL_off": 59090},
    52: {"type": "TDD", "FDL_low": 3300.0, "NDL_off": 59140},
    53: {"type": "TDD", "FDL_low": 2483.5,"NDL_off": 60140},
}

# --- NR (5G) – stark vereinfachte Bandtabelle (FR1) ---

NR_BANDS: Dict[int, Dict[str, Any]] = {
    # Beispielhafte Auswahl, erweiterbar
    1:  {"FR": "FR1", "F_low": 2110.0, "N_off": 422000},
    3:  {"FR": "FR1", "F_low": 1805.0, "N_off": 361000},
    7:  {"FR": "FR1", "F_low": 2620.0, "N_off": 524000},
    8:  {"FR": "FR1", "F_low": 925.0,  "N_off": 185000},
    20: {"FR": "FR1", "F_low": 791.0,  "N_off": 158200},
    28: {"FR": "FR1", "F_low": 758.0,  "N_off": 151600},
    78: {"FR": "FR1", "F_low": 3300.0, "N_off": 620000},
    77: {"FR": "FR1", "F_low": 3300.0, "N_off": 620000},
}

# --- UMTS (3G) – einfache UARFCN-Berechnung (Beispiel) ---

UMTS_DL_TABLE = {
    # Band: (F_low, N_off)
    1: (2112.4, 10562),
    8: (925.2, 2712),
}

# --- GSM (2G) – einfache ARFCN-Berechnung (900/1800) ---

def gsm_arfcn_to_freq(arfcn: int) -> Optional[float]:
    # stark vereinfacht, nur als grobe Orientierung
    if 0 <= arfcn <= 124:  # GSM 900
        return 935.0 + 0.2 * (arfcn - 1)
    if 512 <= arfcn <= 885:  # DCS 1800
        return 1805.2 + 0.2 * (arfcn - 512)
    return None

PEAK_RATES_LTE = {
    1.4: (10.0, 5.0),
    3.0: (25.0, 12.5),
    5.0: (37.5, 18.75),
    10.0: (75.0, 37.5),
    15.0: (112.5, 56.25),
    20.0: (150.0, 75.0),
}

# --- RAT-Erkennung ---

def detect_rat(text: str) -> str:
    t = text.lower()
    if "5g" in t or "nr " in t or "rat selected = nr" in t:
        return "5G"
    if "lte" in t or "rat selected = lte" in t:
        return "4G"
    if "umts" in t or "wcdma" in t or "rat selected = umts" in t:
        return "3G"
    if "gsm" in t or "geran" in t or "rat selected = gsm" in t:
        return "2G"
    return "unknown"

# --- Parser für LTE-typischen Output ---

def find_int(text: str, pattern: str) -> Optional[int]:
    m = re.search(pattern, text, re.IGNORECASE)
    return int(m.group(1)) if m else None

def find_float(text: str, pattern: str) -> Optional[float]:
    m = re.search(pattern, text, re.IGNORECASE)
    return float(m.group(1)) if m else None

def parse_lte(text: str) -> Dict[str, Optional[float]]:
    ndl = find_int(text, r"Rx Channel Number.*?(\d+)")
    nul = find_int(text, r"Tx Channel Number.*?(\d+)")
    band = find_int(text, r"LTE Band\s*=\s*B(\d+)")
    bw_mhz = find_float(text, r"Bandwidth\s*=\s*([\d\.]+)\s*MHz")
    rsrp = find_float(text, r"RSRP\s*=\s*([-]?\d+)")
    rsrq = find_float(text, r"RSRQ\s*=\s*([-]?\d+)")
    snr  = find_float(text, r"SNR\s*=\s*([-]?\d+\.?\d*)")
    return {
        "ndl": ndl,
        "nul": nul,
        "band": band,
        "bw_mhz": bw_mhz,
        "rsrp": rsrp,
        "rsrq": rsrq,
        "snr": snr,
    }

def calc_freq_lte(band: Optional[int], ndl: Optional[int], nul: Optional[int]) -> Tuple[Optional[float], Optional[float]]:
    if band is None or band not in BANDS_LTE:
        return None, None
    b = BANDS_LTE[band]
    fdl = ful = None
    if ndl is not None:
        fdl = b["FDL_low"] + 0.1 * (ndl - b["NDL_off"])
    if b["type"] == "FDD" and nul is not None:
        ful = b["FUL_low"] + 0.1 * (nul - b["NUL_off"])
    return fdl, ful

def calc_peak_rates_lte(bw_mhz: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
    if bw_mhz is None:
        return None, None
    for bw_key in sorted(PEAK_RATES_LTE.keys()):
        if abs(bw_mhz - bw_key) < 0.2:
            return PEAK_RATES_LTE[bw_key]
    dl = 7.5 * bw_mhz
    ul = 2.5 * bw_mhz
    return dl, ul

def quality_status_rsrp(rsrp: Optional[float]) -> str:
    if rsrp is None:
        return "unknown"
    if rsrp >= -80:
        return "excellent"
    if rsrp >= -90:
        return "good"
    if rsrp >= -100:
        return "fair"
    return "poor"

# --- 5G NR: einfache ARFCN->Frequenz ---

def nr_arfcn_to_freq(nr_arfcn: int, band: Optional[int] = None) -> Optional[float]:
    # vereinfachte Formel: F = F_low + 0.005 * (N - N_off)
    if band is None or band not in NR_BANDS:
        return None
    b = NR_BANDS[band]
    return b["F_low"] + 0.005 * (nr_arfcn - b["N_off"])

# --- UMTS: UARFCN->Frequenz (DL) ---

def umts_uarfcn_to_freq(uarfcn: int, band: int = 1) -> Optional[float]:
    if band not in UMTS_DL_TABLE:
        return None
    f_low, n_off = UMTS_DL_TABLE[band]
    return f_low + 0.2 * (uarfcn - n_off)

# --- Ergebnisaufbau je RAT ---

def build_result(text: str) -> Dict[str, Any]:
    rat = detect_rat(text)
    result: Dict[str, Any] = {"rat": rat}

    if rat == "4G":
        parsed = parse_lte(text)
        ndl = parsed["ndl"]
        nul = parsed["nul"]
        band = parsed["band"]
        bw_mhz = parsed["bw_mhz"]
        rsrp = parsed["rsrp"]
        rsrq = parsed["rsrq"]
        snr  = parsed["snr"]
        fdl, ful = calc_freq_lte(band, ndl, nul)
        dl_rate, ul_rate = calc_peak_rates_lte(bw_mhz)
        result.update({
            "band": band,
            "band_type": BANDS_LTE.get(band, {}).get("type") if band in BANDS_LTE else None,
            "bandwidth_mhz": bw_mhz,
            "earfcn_dl": ndl,
            "earfcn_ul": nul,
            "freq_dl_mhz": fdl,
            "freq_ul_mhz": ful,
            "peak_dl_mbps": dl_rate,
            "peak_ul_mbps": ul_rate,
            "rsrp_dbm": rsrp,
            "rsrq_db": rsrq,
            "snr_db": snr,
            "rsrp_status": quality_status_rsrp(rsrp),
        })
    elif rat == "5G":
        # sehr generisch: NR-ARFCN und Band suchen
        nr_arfcn = find_int(text, r"NR ARFCN.*?(\d+)")
        nr_band  = find_int(text, r"NR Band\s*=\s*n?(\d+)")
        freq = nr_arfcn_to_freq(nr_arfcn, nr_band) if nr_arfcn and nr_band else None
        ssb_rsrp = find_float(text, r"SSB RSRP\s*=\s*([-]?\d+)")
        ssb_sinr = find_float(text, r"SSB SINR\s*=\s*([-]?\d+\.?\d*)")
        result.update({
            "nr_arfcn": nr_arfcn,
            "nr_band": nr_band,
            "nr_freq_mhz": freq,
            "ssb_rsrp_dbm": ssb_rsrp,
            "ssb_sinr_db": ssb_sinr,
        })
    elif rat == "3G":
        uarfcn_dl = find_int(text, r"UARFCN DL.*?(\d+)")
        band = find_int(text, r"UMTS Band\s*=\s*(\d+)")
        freq = umts_uarfcn_to_freq(uarfcn_dl, band or 1) if uarfcn_dl else None
        rscp = find_float(text, r"RSCP\s*=\s*([-]?\d+)")
        ecno = find_float(text, r"Ec/No\s*=\s*([-]?\d+)")
        result.update({
            "umts_band": band,
            "uarfcn_dl": uarfcn_dl,
            "freq_dl_mhz": freq,
            "rscp_dbm": rscp,
            "ecno_db": ecno,
        })
    elif rat == "2G":
        arfcn = find_int(text, r"ARFCN.*?(\d+)")
        freq = gsm_arfcn_to_freq(arfcn) if arfcn is not None else None
        rxlev = find_int(text, r"RxLev\s*=\s*(\d+)")
        result.update({
            "arfcn": arfcn,
            "freq_dl_mhz": freq,
            "rxlev": rxlev,
        })
    else:
        # unknown RAT – wir geben nur das RAT zurück
        pass

    return result

# --- CLI-Ausgabe ---

def print_cli(result: Dict[str, Any]) -> None:
    rat = result.get("rat", "unknown")
    print("=== Cellular Radio Analyzer ===")
    print(f"RAT:            {rat}")
    print("")

    if rat == "4G":
        if result.get("band"):
            print(f"Band:           B{result['band']} ({result.get('band_type')})")
        else:
            print("Band:           unbekannt")
        if result.get("bandwidth_mhz") is not None:
            print(f"Bandwidth:      {result['bandwidth_mhz']:.1f} MHz")
        else:
            print("Bandwidth:      unbekannt")
        print("")
        print("=== EARFCN / Frequenzen ===")
        if result.get("earfcn_dl") is not None:
            if result.get("freq_dl_mhz") is not None:
                print(f"EARFCN DL:      {result['earfcn_dl']:6d}  →  {result['freq_dl_mhz']:.3f} MHz")
            else:
                print(f"EARFCN DL:      {result['earfcn_dl']:6d}  (Band nicht in Tabelle)")
        else:
            print("EARFCN DL:      nicht gefunden")
        if result.get("earfcn_ul") is not None:
            if result.get("freq_ul_mhz") is not None:
                print(f"EARFCN UL:      {result['earfcn_ul']:6d}  →  {result['freq_ul_mhz']:.3f} MHz")
            else:
                print(f"EARFCN UL:      {result['earfcn_ul']:6d}  (Band nicht in Tabelle)")
        else:
            print("EARFCN UL:      nicht gefunden")
        print("")
        print("=== Theoretische Max-Raten (idealisiert) ===")
        if result.get("peak_dl_mbps") is not None:
            print(f"Downlink:       {result['peak_dl_mbps']:.1f} Mbit/s")
        else:
            print("Downlink:       unbekannt")
        if result.get("peak_ul_mbps") is not None:
            print(f"Uplink:         {result['peak_ul_mbps']:.1f} Mbit/s")
        else:
            print("Uplink:         unbekannt")
        print("")
        print("=== Funkqualitätsindikatoren ===")
        if result.get("rsrp_dbm") is not None:
            print(f"RSRP:           {result['rsrp_dbm']:.0f} dBm ({result.get('rsrp_status')})")
        else:
            print("RSRP:           nicht gefunden")
        if result.get("rsrq_db") is not None:
            print(f"RSRQ:           {result['rsrq_db']:.0f} dB")
        else:
            print("RSRQ:           nicht gefunden")
        if result.get("snr_db") is not None:
            print(f"SNR:            {result['snr_db']:.1f} dB")
        else:
            print("SNR:            nicht gefunden")
    elif rat == "5G":
        print("=== 5G NR ===")
        print(f"NR ARFCN:       {result.get('nr_arfcn')}")
        print(f"NR Band:        {result.get('nr_band')}")
        print(f"NR Freq:        {result.get('nr_freq_mhz')} MHz")
        print(f"SSB RSRP:       {result.get('ssb_rsrp_dbm')} dBm")
        print(f"SSB SINR:       {result.get('ssb_sinr_db')} dB")
    elif rat == "3G":
        print("=== UMTS ===")
        print(f"Band:           {result.get('umts_band')}")
        print(f"UARFCN DL:      {result.get('uarfcn_dl')}")
        print(f"Freq DL:        {result.get('freq_dl_mhz')} MHz")
        print(f"RSCP:           {result.get('rscp_dbm')} dBm")
        print(f"Ec/No:          {result.get('ecno_db')} dB")
    elif rat == "2G":
        print("=== GSM ===")
        print(f"ARFCN:          {result.get('arfcn')}")
        print(f"Freq DL:        {result.get('freq_dl_mhz')} MHz")
        print(f"RxLev:          {result.get('rxlev')}")
    else:
        print("Keine detaillierte Auswertung möglich (RAT unbekannt).")

    print("")
    print("Hinweis: Werte sind theoretisch; reale Durchsätze und Pegel hängen von vielen Faktoren ab.")

# --- Webinterface (optional, wie zuvor) ---

try:
    from flask import Flask, request, render_template_string
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Cellular Radio Analyzer</title>
  <style>
    body { font-family: sans-serif; margin: 20px; }
    textarea { width: 100%; height: 200px; }
    pre { background: #f4f4f4; padding: 10px; }
  </style>
</head>
<body>
  <h1>Cellular Radio Analyzer</h1>
  <p>Show-Command auf dem Router: <code>show cellular 0/2/0 radio</code></p>
  <form method="post">
    <label for="output">Cisco Output:</label><br>
    <textarea name="output" id="output">{{ output|e }}</textarea><br><br>
    <label><input type="checkbox" name="json" {% if json_mode %}checked{% endif %}> JSON-Output</label><br><br>
    <button type="submit">Analysieren</button>
  </form>

  {% if result %}
    <h2>Ergebnis</h2>
    {% if json_mode %}
      <pre>{{ result_json }}</pre>
    {% else %}
      <pre>{{ result_pre }}</pre>
    {% endif %}
  {% endif %}
</body>
</html>
"""

def run_web(host: str = "0.0.0.0", port: int = 5000):
    if not FLASK_AVAILABLE:
        print("Flask ist nicht installiert. Bitte zuerst 'pip install flask' ausführen.")
        sys.exit(1)

    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def index():
        output = ""
        result = None
        json_mode = False
        result_json = ""
        result_pre = ""
        if request.method == "POST":
            output = request.form.get("output", "")
            json_mode = bool(request.form.get("json"))
            if output.strip():
                res = build_result(output)
                result = res
                result_json = json.dumps(res, indent=2, sort_keys=True)
                # CLI-Style in String rendern
                from io import StringIO
                buf = StringIO()
                old_stdout = sys.stdout
                sys.stdout = buf
                print_cli(res)
                sys.stdout = old_stdout
                result_pre = buf.getvalue()
        return render_template_string(HTML_TEMPLATE,
                                      output=output,
                                      result=result,
                                      json_mode=json_mode,
                                      result_json=result_json,
                                      result_pre=result_pre)

    app.run(host=host, port=port)

# --- Interaktiver Modus (Option B) ---

def read_interactive() -> str:
    print('--- Cellular Analyzer Interactive Mode ---')
    print('Bitte den kompletten Output von "show cellular 0/2/0 radio" einfügen.')
    print('Beenden mit einer einzelnen Zeile: END')
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Cellular Radio Analyzer (Cisco 'show cellular 0/2/0 radio').")
    parser.add_argument("--web", action="store_true", help="Webinterface starten (Flask).")
    parser.add_argument("--host", default="0.0.0.0", help="Listen-Host für Webmodus (default: 0.0.0.0).")
    parser.add_argument("--port", type=int, default=5000, help="Listen-Port für Webmodus (default: 5000).")
    parser.add_argument("--json", action="store_true", help="CLI: Ergebnis als JSON ausgeben.")
    parser.add_argument("file", nargs="?", help="Optional: Datei mit Output.")
    args = parser.parse_args()

    if args.web:
        run_web(args.host, args.port)
        return

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        if sys.stdin.isatty():
            # Interaktiver Modus (B)
            text = read_interactive()
        else:
            text = sys.stdin.read()

    if not text.strip():
        print("Kein Input erhalten.")
        sys.exit(1)

    result = build_result(text)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_cli(result)

if __name__ == "__main__":
    main()
