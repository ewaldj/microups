# Screen & Tmux Quick Guide

A short cheat sheet for terminal multiplexers: run programs in a session that survives disconnects (SSH drop, closed terminal, etc.) and reattach to it later, right where you left off.

## Contents

- [Why use a multiplexer](#why-use-a-multiplexer)
- [screen](#screen)
- [tmux](#tmux)
- [Typical workflow](#typical-workflow)
- [Which one should I use?](#which-one-should-i-use)

## Why use a multiplexer

Both `screen` and `tmux` let you:

- keep processes running after you disconnect
- reattach to the same session later, output intact
- split a terminal into multiple windows and panes

## screen

### Sessions

| Action | Command |
|---|---|
| Start a new session | `screen` |
| Start a **named** session (recommended) | `screen -S mysession` |
| Detach from current session | `Ctrl-a` `d` |
| List running sessions | `screen -ls` |
| Reattach (only one session) | `screen -r` |
| Reattach to a named session | `screen -r mysession` |
| Force-detach elsewhere and reattach here | `screen -r -d mysession` |
| Kill from inside | `exit` |
| Kill from outside | `screen -X -S mysession quit` |

### Keyboard shortcuts

All shortcuts start with the prefix `Ctrl-a`.

| Shortcut | Action |
|---|---|
| `Ctrl-a c` | create a new window |
| `Ctrl-a n` | next window |
| `Ctrl-a p` | previous window |
| `Ctrl-a "` | list windows and select one |
| `Ctrl-a A` | rename current window |
| `Ctrl-a S` | split horizontally |
| `Ctrl-a \|` | split vertically |
| `Ctrl-a Tab` | switch between panes |
| `Ctrl-a d` | detach |

## tmux

### Sessions

| Action | Command |
|---|---|
| Start a new session | `tmux` |
| Start a **named** session (recommended) | `tmux new -s mysession` |
| Detach from current session | `Ctrl-b` `d` |
| List running sessions | `tmux ls` |
| Reattach to last session | `tmux attach` |
| Reattach to a named session | `tmux attach -t mysession` |
| Kill from inside | `exit` |
| Kill from outside | `tmux kill-session -t mysession` |

### Keyboard shortcuts

All shortcuts start with the prefix `Ctrl-b`.

| Shortcut | Action |
|---|---|
| `Ctrl-b c` | create a new window |
| `Ctrl-b n` | next window |
| `Ctrl-b p` | previous window |
| `Ctrl-b w` | list windows and select one |
| `Ctrl-b ,` | rename current window |
| `Ctrl-b %` | split pane vertically (side by side) |
| `Ctrl-b "` | split pane horizontally (top/bottom) |
| `Ctrl-b arrow` | move between panes |
| `Ctrl-b z` | zoom/unzoom current pane |
| `Ctrl-b d` | detach |

## Typical workflow

1. SSH into a remote server.
2. Start a named session:
   ```bash
   screen -S work
   # or
   tmux new -s work
   ```
3. Run your long-running command (build, monitoring script, install, ...).
4. Detach: `Ctrl-a d` (screen) or `Ctrl-b d` (tmux).
5. Disconnect, close the terminal, go home.
6. Later, SSH back in and reattach:
   ```bash
   screen -r work
   # or
   tmux attach -t work
   ```
   Your command is still running and all output is still there.

## Which one should I use?

- **screen** — simpler, pre-installed on almost every Linux/Unix system, good enough for "just keep this running" use cases.
- **tmux** — more modern, more configurable, nicer scripting and session management, better default pane-splitting. Generally the preferred choice today if you can install it.

Both do the same core job: keep processes alive across disconnects and let you get back to them later.
