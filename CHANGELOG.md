# Changelog

## 2.23.1

- Reworked `install_ubuntu.sh` into a permanent install/update command using a
  private environment under `~/.local/share/mdir-u`.
- Added persistent `u`, `U`, and `mdir-u` launchers under `~/.local/bin` and an
  Ubuntu application-menu entry with the mDIR icon.
- Added `uninstall_ubuntu.sh` while preserving personal configuration.
- Added nano to the automatic Ubuntu dependency installation.
- Extended slow double-click recognition and delayed mouse-triggered Rename.
- Clicking empty space anywhere in either file pane now activates that pane.

## 2.22.1

- Changed F4 Edit to open supported text files in the interactive nano editor.
- The mDir interface is suspended while nano is active and restored when nano
  exits.
- Added an installation message with `sudo apt install nano` when nano is not
  available.

## 2.22.0

- Ported the current MDIR-P file-management features to Ubuntu and other
  Linux terminals while preserving Linux locations, mounts, shell launching,
  default-application opening, and XDG configuration paths.
- Added background Copy, Move, and permanent Delete with live progress and
  cancellation.
- Added batch rename, advanced file/content search, ZIP creation, and secure
  ZIP extraction.
- Added automatic external directory refresh and responsive folder-size work.
- Added Ubuntu GitHub Actions validation and package builds.
