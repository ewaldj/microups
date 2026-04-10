#!/usr/bin/env zsh
# MacPrepE.sh — macOS dev environment setup & update

VERSION="0.10"

# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------
BREW_PACKAGES=(
    joe
    python
    uv
    pipx
    nmap
    iperf
    iperf3
    btop
    tcpdump
    fping
    curl
    tmux
    screen
    tcpreplay
    git-filter-repo
)

PIP_PACKAGES=(
    scapy
)

# Remote install scripts — fetched and executed via bash
REMOTE_INSTALLERS=(
    "https://raw.githubusercontent.com/ewaldj/dscp-top/refs/heads/main/e-install.sh"
    "https://raw.githubusercontent.com/ewaldj/eping/refs/heads/main/e-install.sh"
    "https://raw.githubusercontent.com/ewaldj/muxpi/main/e-install.sh"
    "https://raw.githubusercontent.com/ewaldj/mau-tg/refs/heads/main/e-install.sh"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "[MacPrepE v${VERSION}] $*"; }
err()  { echo "[ERROR] $*" >&2; exit 1; }

ZSHRC="$HOME/.zshrc"
path_entry='export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"'

add_path_once() {
    grep -qxF "$path_entry" "$ZSHRC" 2>/dev/null || echo "$path_entry" >> "$ZSHRC"
}

# ---------------------------------------------------------------------------
# Privilege check — cache sudo credentials upfront
# ---------------------------------------------------------------------------
check_sudo() {
    if [[ $EUID -eq 0 ]]; then
        log "Running as root"
    else
        log "Caching sudo credentials..."
        sudo -v || err "sudo authentication failed"
        # Keep sudo alive for the duration of the script
        ( while true; do sudo -n true; sleep 50; done ) &
        SUDO_KEEPALIVE_PID=$!
        trap 'kill "$SUDO_KEEPALIVE_PID" 2>/dev/null' EXIT
    fi
}

# ---------------------------------------------------------------------------
# Homebrew
# ---------------------------------------------------------------------------
install_brew() {
    if ! command -v brew &>/dev/null; then
        log "Installing Homebrew (non-interactive)..."
        NONINTERACTIVE=1 /bin/bash -c \
            "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
            || err "Homebrew install failed"
    else
        log "Homebrew already installed — skipping"
    fi
    eval "$(/opt/homebrew/bin/brew shellenv)"
}

# ---------------------------------------------------------------------------
# Brew packages
# ---------------------------------------------------------------------------
sync_brew_packages() {
    brew update
    for pkg in "${BREW_PACKAGES[@]}"; do
        if brew list --formula "$pkg" &>/dev/null; then
            log "brew: upgrading $pkg"
            brew upgrade "$pkg" 2>/dev/null || log "brew: $pkg already up-to-date"
        else
            log "brew: installing $pkg"
            brew install "$pkg" || err "Failed to install $pkg"
        fi
    done
}

# ---------------------------------------------------------------------------
# pip packages
# ---------------------------------------------------------------------------
sync_pip_packages() {
    for pkg in "${PIP_PACKAGES[@]}"; do
        if pip3 show "$pkg" &>/dev/null; then
            log "pip: upgrading $pkg"
            pip3 install --upgrade "$pkg" --break-system-packages
        else
            log "pip: installing $pkg"
            pip3 install "$pkg" --break-system-packages || err "Failed to install $pkg"
        fi
    done
}

# ---------------------------------------------------------------------------
# Remote installers
# ---------------------------------------------------------------------------
run_remote_installers() {
    for url in "${REMOTE_INSTALLERS[@]}"; do
        log "remote: running $url"
        sudo /bin/bash -c "$(curl -fsSL "$url")" || log "WARNING: remote installer failed: $url"
    done
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
check_sudo
run_remote_installers
install_brew
add_path_once
sync_brew_packages
sync_pip_packages

log "Done."
# Reload shell environment so all installed tools are immediately available
source "$ZSHRC"
