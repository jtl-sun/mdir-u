# Changelog

## 2.23.15

- Ported the complete platform-neutral mDIR-P 2.23.2–2.23.15 feature set to
  Ubuntu while preserving Linux paths, mounts, shell tools, and XDG storage.
- Added clickable path segments, trailing path separators, green active-pane
  styling, and a pale-yellow information separator.
- Added selected-name MkDir defaults, batch-rename find/delete and optional
  end numbering with safe `[N]`, one-digit, OFF defaults.
- Moved large-directory scans off the UI thread, shows the first 250 rows
  quickly, and cancels obsolete scans when navigation changes.
- Added compact Move/Delete summaries, immediate cancellation UI, and safe
  Trash handling for files below 10 GB and directories; no unsafe fallback.
- Added complete AI process-group force stop, thin cursors in single-line
  inputs, stale mouse-state cleanup, and final fast-open/slow-rename timing.
- The Ubuntu installer now verifies that the installed package version exactly
  matches the downloaded source version.

## 2.23.2

- Show a compact warning immediately before Copy or Move would overwrite an
  existing same-name file or directory.
- Keep both the source and existing destination unchanged when the overwrite
  warning is cancelled.
- Require explicit overwrite approval in the Linux background file-operation
  engine as a second safety layer.

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
