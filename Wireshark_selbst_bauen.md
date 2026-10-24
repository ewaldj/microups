# Wireshark selbst bauen: .deb-Pakete für ARM64 und x86\_64

Oct 24, 2026 · @Ewald

## Überblick

Aus dem Wireshark-Quellcode entsteht auf jedem Zielsystem ein eigenes .deb: auf dem Raspberry Pi ein arm64-Paket, auf einem x86-Rechner ein amd64-Paket. Beide Builds laufen identisch ab, nur die Build-Maschine unterscheidet sich. Gebaut wird immer **nativ** auf der jeweiligen Architektur, nicht per Cross-Compile.

|  | ARM (Raspberry Pi) | x86 |
| --- | --- | --- |
| Architektur im Paketnamen | arm64 | amd64 |
| Build-Maschine | Raspberry Pi 4/5, 64-bit Raspberry Pi OS (Debian 13) | PC, Server oder VM mit Debian 13 (x86\_64) |
| Ergebnis | wireshark-custom\_4.6.9-1\_arm64.deb | wireshark-custom\_4.6.9-1\_amd64.deb |
| Bauzeit | länger, mit GUI grob eine Stunde oder mehr | deutlich kürzer |

Ablauf:

1. Build-Umgebung vorbereiten
2. Quellcode holen und prüfen
3. Mit CMake konfigurieren
4. Mit Ninja kompilieren
5. Mit `build-deb.sh` das .deb erzeugen
6. .deb auf den Zielsystemen installieren

Voraussetzungen:

- Build- und Zielsystem haben dieselbe Architektur **und** dieselbe Debian-Version (hier Debian 13 „trixie“ bzw. Raspberry Pi OS darauf). Ein arm64-Paket läuft nicht auf x86 und umgekehrt.
- Richtwert: rund 8 GB freier Speicherplatz und mindestens 4 GB RAM (oder entsprechend Swap) zum Linken.
- sudo-Rechte und Internetzugang für apt und den Download.

**Stand:** Die Schritte 1–4 sind auf einem Raspberry Pi (arm64, Wireshark 4.6.9) durchlaufen. Das Paketier-Skript aus Schritt 5 und der x86-Build sind noch nicht praktisch bestätigt, beim ersten Lauf bitte kurz prüfen.

## 1. Build-Umgebung vorbereiten

Die Paketliste ist auf ARM und x86 identisch, apt wählt automatisch die passende Architektur. Alle Befehle laufen auf der Build-Maschine.

**Werkzeuge und Bibliotheken:**

```bash
sudo apt update
sudo apt install -y build-essential cmake ninja-build pkg-config git wget file \
  dpkg-dev flex bison python3 perl libcap2-bin \
  libglib2.0-dev libpcap-dev libgcrypt20-dev libc-ares-dev libpcre2-dev \
  libspeexdsp-dev libssh-dev libxml2-dev zlib1g-dev liblz4-dev libzstd-dev \
  libnl-3-dev libnl-genl-3-dev libcap-dev libgnutls28-dev libsmi2-dev \
  libsnappy-dev libnghttp2-dev libnghttp3-dev libbrotli-dev libminizip-dev \
  libopus-dev libsbc-dev libspandsp-dev libkrb5-dev libmaxminddb-dev \
  liblua5.4-dev libsystemd-dev libxxhash-dev
```

Pflicht sind vor allem `libglib2.0-dev`, `libpcap-dev`, `libgcrypt20-dev`, `libc-ares-dev`, `libpcre2-dev`, `flex` und `bison`. Die übrigen Pakete schalten zusätzliche Dissector- und Decrypt-Funktionen frei. Existiert ein Paketname auf deinem System nicht, lass ihn weg.

**Zusätzlich für die GUI (Qt6):**

```bash
sudo apt install -y qt6-base-dev qt6-base-dev-tools qt6-tools-dev qt6-tools-dev-tools \
  qt6-multimedia-dev qt6-5compat-dev libqt6svg6-dev libgl-dev
```

Wer nur `tshark` und die Kommandozeilen-Tools braucht, überspringt diesen Block und baut später ohne GUI. Das spart auf dem Pi viel Zeit.

**Alternative:** `sudo apt build-dep wireshark` zieht die Abhängigkeiten des Debian-Pakets in einem Rutsch, funktioniert aber nur, wenn `deb-src` aktiv ist. In Debian 13 steht die Quelle meist in `/etc/apt/sources.list.d/debian.sources`, dort muss `Types: deb deb-src` stehen, danach `sudo apt update`.

## 2. Quellcode holen und prüfen

Den Tarball lädst du von wireshark.org, die aktuelle Versionsnummer steht auf der [Download-Seite](https://www.wireshark.org/download.html). Ältere Versionen liegen unter `download/src/all-versions/`.

```bash
export VER=4.6.9            # hier die gewünschte Version eintragen
mkdir -p ~/src && cd ~/src
wget https://www.wireshark.org/download/src/wireshark-$VER.tar.xz
wget https://www.wireshark.org/download/SIGNATURES-$VER.txt
sha256sum wireshark-$VER.tar.xz
grep wireshark-$VER.tar.xz SIGNATURES-$VER.txt
```

Die beiden SHA256-Werte müssen übereinstimmen. Liegt die Version nicht mehr im Hauptverzeichnis, steht die Datei im Unterordner `all-versions`, die Signaturdatei dann ebenfalls dort.

Danach entpacken:

```bash
tar xf wireshark-$VER.tar.xz
cd wireshark-$VER
```

## 3. Mit CMake konfigurieren

Konfiguriert wird in einem eigenen Build-Ordner, damit der Quellbaum sauber bleibt.

```bash
mkdir build && cd build
cmake -G Ninja -DCMAKE_BUILD_TYPE=Release ..
```

CMake prüft hier alle Abhängigkeiten. Am Ende steht eine Zusammenfassung der gefundenen und fehlenden Features. Fehlt etwas Pflichtmäßiges, bricht CMake mit einer Meldung wie `Could NOT find GLIB2` ab, dann das passende `-dev`-Paket nachinstallieren, den Ordner `build` löschen und neu konfigurieren.

Optionen, die du anhängen kannst:

| Option | Wirkung |
| --- | --- |
| `-DBUILD_wireshark=OFF` | Nur Kommandozeile (`tshark`, `dumpcap`, `editcap` …), keine Qt-GUI. Deutlich schnellerer Build. |
| `-DCMAKE_BUILD_TYPE=Release` | Optimiert, ohne Debug-Symbole. Standard ohne Angabe ist `RelWithDebInfo` (sehr große Binärdateien). |
| `-DCMAKE_INSTALL_PREFIX=/usr/local` | Installationsort. Das ist bereits der Standard. |

`-DDUMPCAP_INSTALL_OPTION` wird hier bewusst **nicht** gesetzt. Die Rechte von `dumpcap` setzt später das Paket selbst (siehe Schritt 5), weil CMake sie beim Installieren in ein Staging-Verzeichnis nicht sauber vergeben kann.

## 4. Kompilieren

Gebaut wird im Ordner `build` mit Ninja, das alle CPU-Kerne nutzt. Auf dem Raspberry Pi dauert das mit GUI deutlich länger, starte den Build deshalb in `tmux` oder `screen`, damit eine abgerissene SSH-Sitzung ihn nicht beendet.

```bash
cd ~/src/wireshark-$VER/build
ninja
```

Bricht der Build auf dem Pi beim Linken mit `Killed` ab, fehlt Arbeitsspeicher. Dann mit weniger parallelen Jobs weitermachen (`ninja -j2`) oder Swap vergrößern. Ninja setzt an der Abbruchstelle fort.

**Ergebnis prüfen:**

```bash
ninja                        # meldet nur kurz "vcs_version.h unchanged" und endet
ls -l run/wireshark run/tshark run/dumpcap run/libwireshark.so*
./run/tshark --version | head -1
```

Wichtig: `ninja install` baut **nichts** mit. Fehlt ein Bauergebnis, schlägt die Installation mit `file INSTALL cannot copy file … run/libwireshark.so…` fehl. Erst wenn `ninja` ohne Fehler durchläuft und die Dateien in `run/` existieren, geht es weiter.

## 5. Das .deb-Paket bauen

Das Paket entsteht in drei Schritten: Installation in ein Staging-Verzeichnis (`DESTDIR`), Abhängigkeiten automatisch ermitteln, mit `dpkg-deb` verpacken. Das Skript erledigt alles und erkennt die Architektur selbst, es ist auf ARM und x86 dasselbe.

`checkinstall` taugt dazu auf Debian 13 nicht mehr: Es ist seit Jahren ungepflegt und bricht beim Kopieren der Dateien ab (siehe Fehlerbilder).

Speichere das Skript als `~/build-deb.sh`, mache es ausführbar (`chmod +x ~/build-deb.sh`) und rufe es mit der Version auf, z. B. `~/build-deb.sh 4.6.9`.

```bash
#!/bin/bash
# build-deb.sh: erzeugt aus dem fertigen Wireshark-Build ein .deb
# Aufruf: ./build-deb.sh 4.6.9
set -euo pipefail

VER="${1:?Version angeben, z. B. ./build-deb.sh 4.6.9}"
BUILD="$HOME/src/wireshark-$VER/build"
ROOT="$HOME/pkg"
PKG="$ROOT/wireshark-custom"
ARCH=$(dpkg --print-architecture)          # arm64 oder amd64
OUT="$ROOT/wireshark-custom_${VER}-1_${ARCH}.deb"

cd "$BUILD"
ninja                                      # stellt sicher, dass alles gebaut ist

rm -rf "$ROOT"
mkdir -p "$PKG/DEBIAN"
DESTDIR="$PKG" ninja install/strip         # installiert ins Staging-Verzeichnis, ohne Debug-Symbole

# Abhängigkeiten aus allen installierten ELF-Dateien ermitteln
cd "$ROOT"
mkdir -p debian && touch debian/control    # Dummy, den dpkg-shlibdeps verlangt
ELFS=$(find "$PKG/usr/local" -type f \
        -exec sh -c 'file -b "$1" | grep -q "^ELF"' _ {} \; -print)
DEPS=$(dpkg-shlibdeps -O -l"$PKG/usr/local/lib" $ELFS 2>/dev/null \
        | sed -n 's/^shlibs:Depends=//p' || true)
rm -rf debian
[ -n "$DEPS" ] || { echo "Keine Depends ermittelt (dpkg-dev installiert?)" >&2; exit 1; }

cat > "$PKG/DEBIAN/control" <<EOF
Package: wireshark-custom
Version: $VER-1
Architecture: $ARCH
Maintainer: Ewald <ewald@jeitler.cc>
Depends: $DEPS, libcap2-bin
Provides: wireshark, tshark
Conflicts: wireshark, wireshark-common, tshark
Description: Wireshark $VER (selbst gebaut)
EOF

cat > "$PKG/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
ldconfig
setcap cap_net_raw,cap_net_admin+eip /usr/local/bin/dumpcap || true
EOF

cat > "$PKG/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
ldconfig
EOF
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"

dpkg-deb --build --root-owner-group "$PKG" "$OUT"
echo
dpkg -I "$OUT"
echo "Fertig: $OUT"
```

Was das Skript festlegt:

- **Depends:** `dpkg-shlibdeps` liest aus den Binärdateien, welche Bibliotheken zur Laufzeit nötig sind (Qt6, GLib, libpcap …) und trägt die passenden Debian-Pakete ein. `apt` zieht sie bei der Installation automatisch nach.
- **Conflicts / Provides:** Das Paket ersetzt die Distributionspakete `wireshark`, `wireshark-common` und `tshark`. Beide Varianten lassen sich nicht parallel installieren.
- **postinst:** Aktualisiert den Library-Cache und setzt die Capabilities für `dumpcap`, damit normale Benutzer ohne root mitschneiden können.
- **Installationsort:** `/usr/local`, wie bei einem normalen `ninja install`.

**Ergebnis prüfen:**

```bash
dpkg -I ~/pkg/wireshark-custom_*.deb      # Depends muss gefüllt sein
dpkg -c ~/pkg/wireshark-custom_*.deb | head -30
ls -lh ~/pkg/*.deb                         # Größe: mit install/strip deutlich kleiner als die Rohdateien
```

## 6. Installation und Test auf den Zielsystemen

Kopiere das .deb auf das Zielsystem und installiere es mit `apt`, nicht mit `dpkg -i`. Nur `apt` löst die eingetragenen Abhängigkeiten auf und entfernt dabei das Distributions-Wireshark, falls vorhanden.

```bash
scp ~/pkg/wireshark-custom_4.6.9-1_arm64.deb user@zielsystem:/tmp/
# auf dem Zielsystem:
sudo apt install /tmp/wireshark-custom_4.6.9-1_arm64.deb
```

Auf einem x86-Zielsystem nimmst du entsprechend die `_amd64.deb`.

**Funktion prüfen:**

```bash
hash -r                          # Shell-Cache der Programmpfade leeren
which wireshark tshark           # muss /usr/local/bin/... zeigen
tshark --version | head -1       # muss die neue Version nennen
getcap /usr/local/bin/dumpcap    # erwartet: cap_net_admin,cap_net_raw=eip
dumpcap -D                       # als normaler Benutzer: listet die Interfaces
```

Zeigt `which` noch `/usr/bin/wireshark`, ist das alte Paket nicht entfernt worden oder `/usr/bin` steht im `PATH` vor `/usr/local/bin`.

**Mitschneiden auf eine Gruppe beschränken (optional):** Mit den Capabilities darf jeder lokale Benutzer capturen. Das Debian-Paket beschränkt das auf die Gruppe `wireshark`. Das gleiche erreichst du so:

```bash
sudo groupadd -f wireshark
sudo chgrp wireshark /usr/local/bin/dumpcap
sudo chmod 750 /usr/local/bin/dumpcap
sudo setcap cap_net_raw,cap_net_admin+eip /usr/local/bin/dumpcap
sudo usermod -aG wireshark <benutzer>      # danach neu anmelden
```

Das Paket-`postinst` ändert Gruppe und Modus von \`dumpcap\` nicht. Installierst du das Paket erneut oder aktualisierst es, überschreibt dpkg beides mit den Paketwerten. Wiederhole danach den Block.

**Deinstallation:**

```bash
sudo apt remove wireshark-custom
```

Bei mehreren Rechnern lohnt sich ein kleines internes APT-Repository (z. B. mit `reprepro`), damit die Pakete per `apt upgrade` verteilt werden. Das ist optional und nicht Teil dieser Anleitung.

## Fehlerbilder und Lösungen

Die ersten vier Einträge sind beim Aufbau dieser Anleitung auf dem Raspberry Pi tatsächlich aufgetreten.

| Meldung / Symptom | Ursache | Lösung |
| --- | --- | --- |
| CMake: `Could NOT find GLIB2` (oder PCAP, GCRYPT, CARES, PCRE2, Qt6) | `-dev`-Paket fehlt. Oft lief `apt build-dep` ins Leere, weil `deb-src` nicht aktiv ist. | Pakete aus Schritt 1 installieren, Ordner `build` löschen, neu mit `cmake` konfigurieren. |
| `file INSTALL cannot copy file …/run/libwireshark.so…: No such file or directory` | Der Build war nicht (vollständig) fertig, `ninja install` baut nicht mit. | Erst `ninja` ohne Fehler durchlaufen lassen, `ls run/` prüfen, dann installieren. |
| `checkinstall` bricht beim Installieren ab, obwohl die Dateien in `run/` existieren | checkinstall 1.6.3 ist veraltet und verkraftet die aktuelle glibc in Debian 13 nicht. | Nicht verwenden, stattdessen `build-deb.sh` (DESTDIR-Methode). |
| `checkinstall`: `syntax error near unexpected token newline` bei `--maintainer` | Die `<` `>` in der E-Mail-Adresse landen in einem `eval`. | Hinfällig, wenn checkinstall nicht mehr benutzt wird. |
| Build endet mit `Killed` oder `c++: fatal error: Killed` | Zu wenig RAM beim Kompilieren oder Linken, der Kernel beendet den Prozess. | `ninja -j2` (oder `-j1`) und Swap vergrößern. Ninja macht an der Abbruchstelle weiter. |
| Skript: "Keine Depends ermittelt" | `dpkg-dev` fehlt oder `file` ist nicht installiert. | `sudo apt install dpkg-dev file`, Skript neu starten. |
| `ninja install/strip` meldet einen Fehler bei `setcap` | Der Build wurde mit `-DDUMPCAP_INSTALL_OPTION=capabilities` konfiguriert. CMake versucht dann `setcap` im Staging-Pfad. | Neuen Build-Ordner anlegen und ohne diese Option konfigurieren (Schritt 3). Das Paket setzt die Rechte im `postinst`. |
| `error while loading shared libraries: libwireshark.so.…` | Library-Cache nicht aktualisiert. | `sudo ldconfig`. `/usr/local/lib` ist in Debian standardmäßig im Suchpfad. |
| `wireshark --version` zeigt noch die alte Version | Altes Paket noch da oder `PATH`-Reihenfolge. | `hash -r`, `which -a wireshark`, altes Paket mit `apt remove wireshark wireshark-common` entfernen. |
| `dumpcap: You don't have permission to capture` | Capabilities fehlen oder wurden überschrieben. | `sudo setcap cap_net_raw,cap_net_admin+eip /usr/local/bin/dumpcap`, mit `getcap` kontrollieren. |

## Update auf eine neue Wireshark-Version

Für jede neue Version wiederholst du die Schritte 2 bis 5 mit der neuen Versionsnummer. Die Build-Umgebung aus Schritt 1 bleibt bestehen. Der Quellordner jeder Version bekommt einen eigenen `build`-Ordner, alte Versionen stören nicht.

```bash
export VER=4.6.10                 # neue Version
cd ~/src
wget https://www.wireshark.org/download/src/wireshark-$VER.tar.xz
wget https://www.wireshark.org/download/SIGNATURES-$VER.txt
sha256sum wireshark-$VER.tar.xz && grep wireshark-$VER.tar.xz SIGNATURES-$VER.txt
tar xf wireshark-$VER.tar.xz && cd wireshark-$VER
mkdir build && cd build
cmake -G Ninja -DCMAKE_BUILD_TYPE=Release ..
ninja
~/build-deb.sh $VER
```

Auf den Zielsystemen genügt dann:

```bash
sudo apt install ./wireshark-custom_4.6.10-1_arm64.deb     # bzw. _amd64.deb
```

`apt` erkennt die höhere Versionsnummer und ersetzt das installierte Paket. Neue Wireshark-Versionen können zusätzliche Build-Abhängigkeiten verlangen. Meldet CMake etwas Fehlendes, steht die Abhilfe im Kapitel Fehlerbilder.
