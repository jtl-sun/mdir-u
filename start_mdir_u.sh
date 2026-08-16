#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALLED_PYTHON="${XDG_DATA_HOME:-$HOME/.local/share}/mdir-u/venv/bin/python"

if [ -x "$INSTALLED_PYTHON" ]; then
    exec "$INSTALLED_PYTHON" -m mdir_u "$@"
fi

exec python3 "$SCRIPT_DIR/mdir_u.py" "$@"
