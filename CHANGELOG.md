# Changelog

## 2.26.3

- Removed automatic Undo from mDIR-U. File safety now relies on explicit confirmation, Ubuntu Trash, conflict checks, and rollback-aware replacement rather than a second automatic filesystem mutation.
- Blocked Copy and Move when a directory target is the source itself or lies inside the source tree.
- Hardened Safe Sync against destination-inside-source recursion, symbolic links, and file/folder type conflicts; changed file replacement now uses a staged atomic publish.
- Preserved the previous `mIndex` when a rebuild is cancelled and staged rebuild rows in SQLite before publishing them.
- Protected approved Copy/Move overwrites with staging and rollback so a failed operation keeps the previous destination.
- Moved Safe Sync comparison off the Textual UI thread before showing the confirmation dialog.
- Optimized `install_ubuntu.sh` to reuse its private venv and pip cache, avoid forced reinstalls and repeated pip upgrades, and run `apt` only for missing system packages.
- Added regression coverage for subtree operations, overwrite rollback, Safe Sync conflicts, and cancelled index rebuilds.

## 2.26.2

- Replaced the generic `Ctrl+P` command palette and its Maximize, Quit, and
  Screenshot commands with an mDIR-specific `F10 Option` screen.
- Added persistent key customization for non-essential shortcuts with duplicate
  and fixed-key collision checks.
- Added direct arrow-key navigation between Keys, Links, Theme, Help, and Close.
- Added a Help button that opens the installed `README.md` in the read-only
  Viewer and included the guide in wheel installations.
- Matched the Keys button styling to Links, Theme, and Help while retaining a
  visible keyboard focus indication.

## 2.25.0

- Added the lazy SQLite `mIndex` filename index and exact/visual duplicate
  discovery without changing files.
- Added a persistent Undo Center for safe Copy, Move, Rename, MkDir, Batch
  Rename, and safe-sync operations. Undo refuses to remove files edited later;
  Trash deletes and overwrites remain deliberately non-undoable.
- Added named two-pane Workspaces, a Copy/Move Macro recorder, and a reviewed
  macro queue that never overwrites an existing target automatically.
- Added Pause/Resume to background file operations and automatic queuing when
  another file operation is already running.
- Added recursive folder comparison and deletion-free one-way safe sync.
- Added explicit `/file` and `/파일` AI requests that produce a visible plan
  and require approval before any filesystem change.

## 2.24.1

- Close Preview before opening a file externally so the associated application
  receives an unobstructed, editable window.

## 2.24.0

- Expanded Preview to images, PDF, Excel, CSV/TSV, text, Markdown, JSON, XML,
  YAML, HTML, Word, and PowerPoint while keeping rendering lazy and bounded.
- Added lightweight DOCX/PPTX text fallback and optional on-demand
  LibreOffice rendering for page-accurate layouts and legacy DOC/PPT files.
- Open files from search results with one click or Enter in Ubuntu's default
  application; use **Location** to reveal one inside mDIR-U.
- Added selected-file placeholders to program links so free specialist apps
  can be connected without increasing mDIR-U's installed weight.
- Kept the AI panel as a core, lazily loaded feature with external provider
  tools remaining optional.

## 2.23.29

- Brought the Ubuntu edition up to feature parity with the platform-neutral
  changes in mDIR-P 2.23.16–2.23.29.
- A first file click now only selects the requested row. A fast click pair
  opens it, while a deliberate slow pair starts Rename without stale timing.
- Mouse selection now lands directly on the clicked row on any scrolled page,
  without first jumping to the top or bottom of the visible page.
- Added right-click selection anchors and Shift+left-click range selection;
  Shift+right-click remains an ordinary right-click selection action.
- File sizes now show complete comma-separated byte counts, file sizes align
  right, directory markers center, compact `Ext`/`Size`/`Modified` headers
  center, and the active sort direction appears in the column heading.
- Replaced width-changing drawn input cursors with the terminal's zero-width
  vertical cursor to prevent text spacing flicker while editing.
- Kept Ubuntu-native terminal events, paths, Trash, launchers, and the offline
  Debian package; Windows pointer polling, WinGet, and PowerShell installers
  are intentionally not included.

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
