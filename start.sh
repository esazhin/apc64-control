#!/usr/bin/env bash
# APC64 Control: clone and run. Sets up .venv on first run (and again when pyproject.toml changes), then serves the
# page and API in the foreground (Ctrl-C releases the unit).
#
#   ./start.sh                  run with the real APC64
#   ./start.sh --simulate       run with the simulated APC64 (no device needed)
#   ./start.sh --install        install and start the systemd user unit and the desktop launcher
#   ./start.sh --uninstall      stop and remove them
#   ./start.sh --setup          only set up .venv
# Any other arguments go to the service (e.g. --port 5791, --host 127.0.0.1).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
REPO=$PWD
UNIT=apc64-host.service
UNIT_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
APPS_DIR=${XDG_DATA_HOME:-$HOME/.local/share}/applications

say() { printf 'apc64: %s\n' "$*"; }
die() { printf 'apc64: %s\n' "$*" >&2; exit 1; }

find_python() {
    for py in python3.14 python3 python; do
        if command -v "$py" >/dev/null && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 14))' 2>/dev/null; then
            echo "$py"; return
        fi
    done
    die "Python 3.14 or newer is needed (python3.14 not found); install it with your package manager"
}

setup() {
    if [ ! -x .venv/bin/python ]; then
        say "creating .venv"
        "$(find_python)" -m venv .venv
    fi
    if [ ! -f .venv/.installed ] || [ pyproject.toml -nt .venv/.installed ]; then
        say "installing dependencies"
        .venv/bin/pip install --quiet --upgrade pip
        .venv/bin/pip install --quiet -e .
        touch .venv/.installed
    fi
    command -v amidi >/dev/null || say "note: amidi (alsa-utils) not found; it is needed to find the APC64"
    command -v notify-send >/dev/null || say "note: notify-send (libnotify) not found; the page still asks before taking the unit"
}

port() {   # the page's port: the environment, then config.local, then the default
    local p=${APC64_HTTP_PORT:-}
    [ -z "$p" ] && [ -f config.local ] && p=$(sed -n 's/^APC64_HTTP_PORT=//p' config.local | tail -1)
    echo "${p:-5058}"
}

install_unit() {
    setup
    mkdir -p "$UNIT_DIR" "$APPS_DIR"
    sed "s|<repo>|$REPO|g" deploy/$UNIT > "$UNIT_DIR/$UNIT"
    sed "s|localhost:5058|localhost:$(port)|" deploy/apc64-host.desktop > "$APPS_DIR/apc64-host.desktop"
    systemctl --user daemon-reload
    systemctl --user enable --now $UNIT
    say "installed: it starts at login and asks before taking the unit; page http://localhost:$(port)/"
    say "log: journalctl --user -u apc64-host -f   stop: systemctl --user stop apc64-host"
}

uninstall_unit() {
    systemctl --user disable --now $UNIT 2>/dev/null || true
    rm -f "$UNIT_DIR/$UNIT" "$APPS_DIR/apc64-host.desktop"
    systemctl --user daemon-reload
    say "removed the systemd user unit and the launcher (the repository, .venv and your data are untouched)"
}

case "${1:-}" in
    --install) install_unit; exit ;;
    --uninstall) uninstall_unit; exit ;;
    --setup) setup; say "ready: ./start.sh to run"; exit ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit ;;
esac

setup
if systemctl --user is-active --quiet $UNIT 2>/dev/null; then
    die "the systemd unit is already running it (page http://localhost:$(port)/); stop it first: systemctl --user stop apc64-host"
fi
page_port=$(port)
for ((i = 1; i <= $#; i++)); do   # a --port given here wins
    case "${!i}" in
        --port=*) page_port=${!i#--port=} ;;
        --port) j=$((i + 1)); page_port=${!j:-$page_port} ;;
    esac
done
say "page: http://localhost:$page_port/; Ctrl-C to stop"
exec .venv/bin/python -m _apc64_host "$@"
