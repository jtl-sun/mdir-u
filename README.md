# mDIR-U

**A fast, free dual-pane file manager for Ubuntu.** Classic MDIR speed,
modern previews, safe file operations, and integrated AI —
built for Linux terminals and the Ubuntu desktop.

[![Latest release](https://img.shields.io/github/v/release/jtl-sun/mdir-u?label=Ubuntu)](https://github.com/jtl-sun/mdir-u/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-2ea44f.svg)](LICENSE)
[![Tests](https://github.com/jtl-sun/mdir-u/actions/workflows/ci.yml/badge.svg)](https://github.com/jtl-sun/mdir-u/actions)

> **Free and open source.** Built so Ubuntu users can manage files quickly
> without subscriptions, ads, or account registration.

### Download for Ubuntu

[**Download the latest stable mDIR-U**](https://github.com/jtl-sun/mdir-u/releases/latest)
· [Windows version](https://github.com/jtl-sun/mdir-p)

```bash
git clone https://github.com/jtl-sun/mdir-u.git
cd mdir-u
./install_ubuntu.sh
```

Then open **mDIR** from the application menu or type `u` in a terminal.

![mDIR dual-pane workflow](docs/assets/mdir-demo.gif)

mDIR-U is a tribute to **Choi Jung Han**, developer of the legendary MDIR
file manager from the DOS era.

## Highlights

- Fast dual-pane file management with editable paths
- Responsive Copy, Move, and Delete for selections exceeding 1,000 items
- Compact overwrite warning before Copy or Move replaces a same-name item
- Background directory scans that show the first 250 rows quickly, even in
  directories containing tens of thousands of files
- Preview for images, PDF, Excel, Word, PowerPoint, CSV, text, and Markdown
- Safe text viewing with F3 and interactive nano editing with F4
- Advanced filename and content search
- Safe batch rename with find/delete and optional end numbering, plus secure
  ZIP creation/extraction
- Clickable path segments, green active-pane styling, and clear item details
- Exact comma-separated byte sizes, compact centered column headings, and
  visible ascending/descending sort arrows
- Direct mouse selection on any visible page; a first click only selects,
  fast double-click opens, and a deliberate slow click pair starts Rename
- Right-click selection anchors followed by Shift+left-click range selection
- Files below 10 GB and directories go to the Ubuntu Trash; files of 10 GB or
  more require permanent deletion
- Ubuntu locations, mounted filesystem selection, and desktop opening
- Integrated Codex, Ollama, and local shell panel
- Configurable top shortcut bar

Preview is disabled at startup. Press `Ctrl+F3` to show or hide it.

## Easy Ubuntu installation or update

Install Git once if needed, download MDIR-U, and run the installer:

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/jtl-sun/mdir-u.git
cd mdir-u
./install_ubuntu.sh
```

The installer:

- installs only missing required Ubuntu packages, including nano;
- creates a private environment under `~/.local/share/mdir-u`;
- installs missing Preview dependencies while reusing the existing venv and pip cache;
- creates permanent `u`, `U`, and `mdir-u` commands;
- adds `~/.local/bin` to your login PATH when necessary; and
- adds **mDIR** to the Ubuntu application menu with its own icon.
- verifies that the installed version exactly matches the downloaded source.

The installer can be run again at any time. It safely updates the program, reuses
already-installed dependencies, and keeps personal settings.

### Update a Git installation

```bash
cd ~/mdir-u
git pull
./install_ubuntu.sh
```

If you cloned it somewhere else, change `~/mdir-u` to that directory.

### Install from a downloaded ZIP

1. Download **Code > Download ZIP** from this GitHub page.
2. Extract the ZIP and open a terminal in the `mdir-u-main` folder.
3. Run:

```bash
chmod +x install_ubuntu.sh
./install_ubuntu.sh
```

### Run

Open **mDIR** from the Ubuntu application menu, or use:

```bash
u
U
mdir-u
```

If the current terminal was open before installation and cannot find `u`,
either open a new terminal or run:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Uninstall

```bash
./uninstall_ubuntu.sh
```

This removes program files and launchers but preserves personal settings.

## Controls

| Key | Action |
| --- | --- |
| `Tab`, `Left`, `Right` | Switch active pane |
| Click anywhere in a pane | Activate the clicked pane |
| `Enter` | Open directory or file |
| `Backspace` | Parent directory |
| `Space` | Mark or unmark |
| `F2` | Rename |
| `Ctrl+F2` | Batch rename selected items |
| `F3` | View a supported text file |
| `F4` | Edit a supported text file with nano |
| `F5` | Copy |
| `F6` | Move |
| `Alt+F5` | Compress selected items to ZIP |
| `Alt+F6` | Extract the selected ZIP |
| `F7` | Create directory |
| `F8` | Delete |
| `F9` | Select a location or mount |
| `F10` | Open mDIR Options |
| `F12` | Toggle AI/file pane |
| `Ctrl+F` | Advanced search |
| `Ctrl+F3` | Toggle document preview |
| `Ctrl+H` | Toggle hidden files |
| `Shift+F10` | Open a terminal at the selected directory |
| `Alt+Enter` | Show item properties |

The generic `Ctrl+P` command palette is disabled. Select **F10 Option** in the
footer to open mDIR-U settings for **Keys**, **Links**, **Theme**, and **Help**.
Use the arrow keys and Enter to select an item. **Help** opens this `README.md`
inside mDIR-U's read-only Viewer. In **Keys**, navigation, opening, selection,
and the Options key remain fixed; other file-operation, search, advanced-tool,
sorting, AI, and Preview shortcuts can be changed. Duplicate shortcuts and
keys reserved by essential actions are rejected. Changes are stored in
`~/.config/mdir-u/keys.json` and take effect immediately.

Copy, Move, and Delete run in a background worker. Large batches show progress
and an ETA; press `Esc` or choose **Cancel** to close the progress dialog
immediately and prevent another top-level item from starting.

Copy/Move also block a directory from being copied or moved into itself or its
own subtree. Approved overwrites are staged first, so a failed replacement can
restore the previous destination instead of leaving it deleted.

A fast second click within 0.75 seconds opens the item. A deliberate second
click after 1.0–3.0 seconds starts Rename.

Batch Rename starts with the safe `[N]` pattern, one counter digit, and both
quick options OFF. Turn on **Delete found text** to remove a phrase, or **End
number** to append a counter only when requested.

## Top shortcut bar

Click **Edit Links** to edit shortcut names, types, targets, panes, and
arguments. MDIR-U stores these links in:

```text
~/.mdir-u-shortcuts.json
```

Supported link types are `folder`, `file`, `program`, `web`, `command`, and
`action`. Placeholders include `{home}`, `{project}`, `{current}`, `{left}`,
`{right}`, `{selected}`, `{left_selected}`, and `{right_selected}`. Program
links can therefore send selected files to free external applications such as
LibreOffice, Meld, GIMP, or VLC without adding their weight to mDIR-U.

## Document Preview

Preview stays disabled until `Ctrl+F3` is pressed and rendering runs in the
background. DOCX and PPTX have a lightweight built-in text fallback. Install
the free LibreOffice application only if page-accurate Office layout or legacy
DOC/PPT preview is needed:

```bash
sudo apt install libreoffice
```

Clicking or pressing Enter on a file—including a search result—opens it with
Ubuntu's default application. The search dialog's **Location** button instead
returns to that file inside mDIR-U.

## AI and local shell

The AI panel is a core mDIR-U feature but loads only after `F12`, keeping normal
file browsing fast. Install and authenticate each provider CLI separately.
`Codex Local` and `Shell` use the current Linux account's direct
permissions, so review commands before running them.

Type an explicit safe file request in the AI panel with `/file` or `/파일`,
for example `/파일 선택한 파일을 오른쪽으로 복사`. mDIR-U turns it into a
local plan and shows the operation, files, and destination in a separate
approval dialog. mDIR-U does not provide automatic Undo. Copy/Move/Rename/MkDir therefore rely
on explicit review, overwrite confirmation, and rollback-aware file handling.
Delete continues to use Ubuntu Trash whenever the item qualifies for Trash.

## Advanced lightweight tools

The tools below load only when invoked, so normal terminal browsing stays
fast. `mIndex` uses Python's built-in SQLite. Duplicate Finder hashes only
equal-size candidates and optionally uses Pillow for visual image similarity.
Folder comparison is read-only, while Safe Sync copies new or changed items
from the active pane to the opposite pane without deleting destination items.
Named Workspaces remember both folders and pane state. Macros record reviewed
Copy/Move batches only and never overwrite an existing target automatically.

| Key | Advanced action |
| --- | --- |
| `Ctrl+Shift+F` | Search `mIndex`; prefix the term with `!` to rebuild |
| `Ctrl+Shift+D` | Find exact and visually similar duplicates |
| `Ctrl+Shift+C` | Compare both current folder trees |
| `Ctrl+Shift+Y` | Safe sync active pane to opposite pane |
| `Ctrl+Shift+S/L` | Save/load a named Workspace |
| `Ctrl+Shift+M` | Start/stop Copy/Move Macro recording |
| `Ctrl+Alt+M` | Review and play a saved Macro |

## WSL notes

MDIR-U runs in WSL Ubuntu. Windows drives appear under `/mnt`, such as
`/mnt/c` and `/mnt/s`. Opening graphical applications requires WSLg or another
configured desktop opener.

## Development validation

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[preview,dev]"
python3 -m mdir_u --check
python3 -m unittest discover -s tests -v
python3 -m build
```

## License

MDIR-U is released under the [MIT License](LICENSE). Attribution and the
license notice must be preserved when redistributing the software.
