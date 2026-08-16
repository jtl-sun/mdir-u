#!/usr/bin/env sh
set -eu

DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
INSTALL_ROOT="$DATA_HOME/mdir-u"
BIN_ROOT="$HOME/.local/bin"
DESKTOP_FILE="$DATA_HOME/applications/mdir-u.desktop"

rm -f "$BIN_ROOT/u" "$BIN_ROOT/U" "$BIN_ROOT/mdir-u" "$DESKTOP_FILE"
rm -rf "$INSTALL_ROOT"

printf '%s\n' "MDIR-U program files and launchers were removed."
printf '%s\n' "Personal settings were preserved."
