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
