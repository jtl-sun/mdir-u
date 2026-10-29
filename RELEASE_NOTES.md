# mDIR-U 2.26.36

## old_M_tema

This release adds the retro **old_M_tema** to mDIR-U's existing **F10 -> Theme** selector while preserving the current Linux-native file-management behavior.

- Black file workspace with cyan/teal interface bars.
- Strong red active-row cursor for clear DOS-style focus.
- EXE/MSI green, COM cyan, BAT/CMD yellow, and PowerShell PS1 magenta.
- AI/File, document Preview, File Search, dialogs and terminal thumbnails continue to follow the selected Textual theme.
- The selected theme is stored per user and restored on the next launch.
- The modern **mDir theme** remains the default.

## Project identity

mDIR-U remains in the **V2.xx.xx** version series and will not move to V3.x. The project keeps the direct, keyboard-friendly spirit of DOS-era Mdir while remaining a modern Linux file manager. Its core modern pillars are **AI/File**, **File View / Preview**, and **File Search**.

mDIR-U 2.26.32 already contains the taller mouse-friendly footer and the unified background progress engine. Windows-only UAC, Windows Terminal profile, and desktop progress-window behavior are intentionally not copied into the Ubuntu edition.

Install on Ubuntu with the 2.26.36 Debian package or extract the source archive and run `bash install_ubuntu.sh`. Existing personal settings are preserved.

---

# mDIR-U 2.26.32

## More comfortable footer mouse controls

- Made the existing bottom function-key command bar **three terminal rows high** so mouse clicks work across the entire button height, not just the text line.
- Reserved **one blank row below the buttons**, keeping the mouse targets farther from the Windows taskbar / Ubuntu dock.
- Retained the existing button labels, colors, order, keyboard shortcuts and file operations.
- No new settings or menus. The layout change is deliberately minimal.

Close mDIR before updating; install the `mDIR-U 2.26.32` Ubuntu DEB or source package, then reopen it. The display remains dependent on the terminal's cell height and window size.

---

# mDIR-U 2.26.31

This release introduces the shared progress engine used by Windows mDIR-P and Ubuntu mDIR-U.

- Copy/Move/Delete: current-file and overall progress, processed bytes, speed and ETA.
- ZIP compression/extraction: cancellable chunk-level progress and pause/resume.
- Advanced search: scanned entries, matched results and scan rate (no invented percentage while total is unknown).
- Background button continues work without the modal. `Ctrl+Alt+P` reopens the current progress dialog.
- Temporary output and source-preserving cancellation are used for large file transfers; existing Linux Trash policy remains unchanged.
- Per-chunk cancellation has limits for OS-managed Trash operations and same-volume renames.

Use the latest mDIR-U 2.26.31 Debian package or the source `install_ubuntu.sh` script. Back up important files and test removable disks separately. Existing personal settings remain in place.

---

# mDIR-U 2.26.30

Ubuntu adaptation of the mDIR-P 2.26.30 improvements.

- Shared Recent Folders history (40 entries), with a `▼` menu on both path bars and `Alt+Down`. Outside clicks close the menu and activate the clicked control.
- Batched selection updates and incremental Shift-range selection for large directories.
- List and terminal-thumbnail right-drag motion is coalesced on a 30 ms timer, with accelerated edge scrolling and pane-independent marks.
- Yellow/white selection-inversion symbol distinct from the thumbnail toggle.
- LibreOffice PDF cache for Excel, Word and PowerPoint; cancellation, timeout, isolated process/profile, atomic publication, source-change invalidation and bounded cleanup.
- Delayed startup callbacks preserve modal dialog focus.

Windows COM/UAC and Windows Terminal profiles are platform-specific and are not installed on Ubuntu. Existing Ubuntu Trash and permissions behavior is retained. The thumbnail view remains a portable terminal grid.

Install on Ubuntu 24.04 amd64 with `sudo apt install ./mdir-u_2.26.30_amd64.deb`, then run `u`. For source installation, extract the archive and run `bash install_ubuntu.sh`. LibreOffice is recommended by the Debian package and installed by the source installer. Without it, existing basic document fallbacks remain available.

See `docs/REBUILD-2.26.30.md` for build instructions and platform differences.

---

## mDIR-U 2.26.15

- Independent left/right thumbnail views and hidden-file controls.
- Right-aligned Select All, Deselect All and Invert Selection buttons on both panes.
- Teal selected-item backgrounds, white text and check marks, distinct from folder colors.
- Right-button drag selection: toggle each crossed item once per gesture, including fast movement and edge scrolling.
- Preserve selection when switching back to the file list and reuse existing copy/move actions.

Ubuntu thumbnails render inside the terminal using color character cells. They work without a separate X11/Wayland overlay; image detail depends on terminal size and color support.

### Ubuntu 24.04 amd64
Download the `.deb` file and run `sudo apt install ./mdir-u_2.26.15_amd64.deb`. Start with `u` or `mdir-u`.
For other supported Linux environments, use the source ZIP and `bash install_ubuntu.sh` (Python 3.11 or newer).

Release assets are built from the merged commit only after CI tests and package checks pass. Checksums are in `SHA256SUMS.txt`.
