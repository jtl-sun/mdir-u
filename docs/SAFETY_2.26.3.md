# mDIR-U 2.26.3 safety review

This release removes automatic Undo and strengthens the filesystem operations that remain.

- Copy and Move refuse to place a directory inside itself or its own subtree.
- Approved Copy overwrites are staged before publication; failed replacements preserve the previous destination.
- Approved Move overwrites keep a rollback backup until the move succeeds.
- Safe Sync blocks destination-inside-source recursion, symbolic links, and file/folder type conflicts, and publishes changed files atomically.
- Cancelled mIndex rebuilds preserve the previously published index.
- Safe Sync comparison runs outside the Textual UI thread.
- Ubuntu Trash continues to use `gio trash` with no unsafe permanent-delete fallback.
- `install_ubuntu.sh` reuses the private venv and pip cache and installs only missing Ubuntu system packages.

The focused 2.26.3 safety regression suite covers subtree operations, overwrite rollback, Safe Sync conflicts, and cancelled index rebuilds. The normal GitHub CI remains the release gate for package installation, self-check, the full test suite, and package build.
