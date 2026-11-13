#!/usr/bin/env bash
# Sign + deploy an MPC controller script (.ini/.lua pair) to a Live III over SSH.
#
# What it does:
#   1. Computes the Akai controller-script checksum over the .lua:
#          sha256( <raw .lua bytes> + "a36d63a8-9cba-6246-9ef1-d573331c5419" )
#      (salt recovered from /usr/bin/MPC, 2026-11-12 — verified vs Akai's own scripts)
#   2. Writes that checksum into the .ini's `checksum=` line (in place).
#   3. Pushes the .ini + .lua into the device's RAM overlay staging dir /tmp/devices-akai.
#   4. Ensures the bind-mount of that dir over /usr/share/Akai/SME0/Devices/Akai is live
#      (re-creates staging + mount if a reboot cleared it).
#   5. Restarts the MPC app so it rescans scripts at startup — UNLESS --no-restart.
#
# Everything on the device is RAM-only and clears on reboot. The rootfs is never written.
#
# Prereqs on the device (once per boot): developer-mode SSH on
#   (Prefs > Info: tap version x3, serial x2, firmware x1), root login, no password.
# After each restart you must manually put the APC64 into its DAW/control mode and
# re-enable Control for its DAW port in Prefs > MIDI.
#
# Usage:
#   ./deploy.sh                       # sign+deploy apc64Session, then restart acvs
#   ./deploy.sh --no-restart          # sign+deploy only; print the restart command
#   ./deploy.sh --name foo --ip 1.2.3.4
#
set -euo pipefail

NAME="apc64Session"
IP="192.168.50.158"
RESTART=1
SALT='a36d63a8-9cba-6246-9ef1-d573331c5419'
DEVDIR="/tmp/devices-akai"
AKAIDIR="/usr/share/Akai/SME0/Devices/Akai"

while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="$2"; shift 2;;
    --ip)   IP="$2"; shift 2;;
    --no-restart) RESTART=0; shift;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LUA="$DIR/$NAME.lua"
INI="$DIR/$NAME.ini"
[ -f "$LUA" ] && [ -f "$INI" ] || { echo "missing $LUA or $INI" >&2; exit 1; }
SSH="ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new root@$IP"

# 1+2. sign: compute checksum and write into the .ini
CK="$(python3 - "$LUA" "$SALT" <<'PY'
import hashlib, sys
lua, salt = sys.argv[1], sys.argv[2].encode()
print(hashlib.sha256(open(lua, "rb").read() + salt).hexdigest())
PY
)"
echo "checksum: $CK"
# portable in-place edit of the checksum= line
python3 - "$INI" "$CK" <<'PY'
import re, sys
ini, ck = sys.argv[1], sys.argv[2]
t = open(ini).read()
t = re.sub(r'(?m)^checksum=.*$', 'checksum=' + ck, t)
open(ini, "w").write(t)
PY

# 3+4. ensure overlay exists, then push the signed pair into it
$SSH "mkdir -p $DEVDIR && { grep -q '$AKAIDIR' /proc/mounts || { cp -a '$AKAIDIR/.' $DEVDIR/ && mount --bind $DEVDIR '$AKAIDIR'; }; }"
tar cf - -C "$DIR" "$NAME.ini" "$NAME.lua" | \
  $SSH "tar xf - -C $DEVDIR && chown root:root $DEVDIR/$NAME.* && chmod 644 $DEVDIR/$NAME.*"
echo "deployed $NAME to $IP:$DEVDIR (overlay live)"

# 5. restart so the app rescans (drops the open project — save first)
if [ "$RESTART" = 1 ]; then
  echo "restarting MPC app (acvs) — the open project is dropped..."
  $SSH "systemctl restart acvs"
  echo "done. Re-enter DAW mode on the APC + re-enable Control for its DAW port."
else
  echo "skip restart. To apply: $SSH 'systemctl restart acvs'"
fi
