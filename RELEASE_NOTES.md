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
