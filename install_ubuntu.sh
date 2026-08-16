#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
INSTALL_ROOT="$DATA_HOME/mdir-u"
VENV_ROOT="$INSTALL_ROOT/venv"
BIN_ROOT="$HOME/.local/bin"
APPLICATIONS_ROOT="$DATA_HOME/applications"
ICON_SOURCE="$SCRIPT_DIR/mdir_u/assets/mdir.png"
INSTALLED_ICON="$INSTALL_ROOT/mdir.png"
DESKTOP_FILE="$APPLICATIONS_ROOT/mdir-u.desktop"

if command -v apt-get >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then
        SUDO=""
    elif command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        printf '%s\n' "sudo is required to install Ubuntu system packages." >&2
        exit 1
    fi
    $SUDO apt-get update
    $SUDO apt-get install -y python3 python3-venv python3-pip xdg-utils poppler-utils zenity nano
fi

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
    printf '%s\n' "MDIR-U requires Python 3.11 or newer." >&2
    exit 1
}

mkdir -p "$INSTALL_ROOT" "$BIN_ROOT" "$APPLICATIONS_ROOT"
if [ ! -x "$VENV_ROOT/bin/python" ]; then
    python3 -m venv "$VENV_ROOT"
fi

"$VENV_ROOT/bin/python" -m pip install --upgrade pip
"$VENV_ROOT/bin/python" -m pip install --no-cache-dir --force-reinstall "$SCRIPT_DIR[preview]"

ln -sfn "$VENV_ROOT/bin/u" "$BIN_ROOT/u"
ln -sfn "$VENV_ROOT/bin/U" "$BIN_ROOT/U"
ln -sfn "$VENV_ROOT/bin/mdir-u" "$BIN_ROOT/mdir-u"

if [ -f "$ICON_SOURCE" ]; then
    cp "$ICON_SOURCE" "$INSTALLED_ICON"
fi

{
    printf '%s\n' '[Desktop Entry]'
    printf '%s\n' 'Type=Application'
    printf '%s\n' 'Name=mDIR'
    printf '%s\n' 'Comment=Dual-pane terminal file manager'
    printf 'Exec=%s\n' "$VENV_ROOT/bin/mdir-u"
    printf 'Icon=%s\n' "$INSTALLED_ICON"
    printf '%s\n' 'Terminal=true'
    printf '%s\n' 'Categories=Utility;FileManager;'
} > "$DESKTOP_FILE"
chmod 755 "$DESKTOP_FILE"

if ! printf '%s' ":$PATH:" | grep -F ":$BIN_ROOT:" >/dev/null 2>&1; then
    if ! grep -F 'export PATH="$HOME/.local/bin:$PATH"' "$HOME/.profile" >/dev/null 2>&1; then
        printf '\n%s\n' '# Added by MDIR-U installer' >> "$HOME/.profile"
        printf '%s\n' 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.profile"
    fi
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_ROOT" >/dev/null 2>&1 || true
fi

VERSION=$("$VENV_ROOT/bin/python" -c 'import mdir_u; print(mdir_u.__version__)')
printf '\n%s\n' "MDIR-U $VERSION installed successfully."
printf '%s\n' "Commands: u, U, mdir-u"
printf '%s\n' "Application menu: mDIR"
printf '%s\n' "If this terminal cannot find u yet, run: export PATH=\"$HOME/.local/bin:\$PATH\""
