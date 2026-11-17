#!/bin/sh
# Runs the app as PUID:PGID (default: Unraid's nobody:users = 99:100) so that files in /data are owned by that user.
set -e

PUID="${PUID:-99}"
PGID="${PGID:-100}"
DATA="${NOTEBOOK_DATA_DIR:-/data}"
UMASK="${UMASK:-002}"
umask "$UMASK"

mkdir -p "$DATA"

if [ "$(id -u)" = "0" ] && [ "$PUID" != "0" ]; then
    chown "$PUID:$PGID" "$DATA" 2>/dev/null || true
    for f in "$DATA"/notebook.sqlite*; do
        [ -e "$f" ] && chown "$PUID:$PGID" "$f" 2>/dev/null || true
    done
    export HOME=/tmp
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups lab-notebook "$@"
fi

exec lab-notebook "$@"
