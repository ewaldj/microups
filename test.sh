#!/usr/bin/env zsh
echo "hello"
# Reload shell environment so all installed tools are immediately available
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


if [[ -n "$ZSH_VERSION" ]]; then
    log "RELOAD SHEL"
    source "$ZSHRC"
else
    log "Skipping shell reload — not running in zsh (run: source ~/.zshrc manually)"
fi
