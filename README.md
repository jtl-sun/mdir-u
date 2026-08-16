# MDIR-U

**MDIR for Ubuntu. MDIR Universal.**

MDIR-U is a fast, keyboard-oriented dual-pane file manager for Ubuntu and
other Linux terminals. It combines the direct workflow of classic MDIR and
Total Commander with large-directory performance, document preview, and an
optional AI command panel.

MDIR-U is a tribute to **Choi Jung Han**, developer of the legendary MDIR
file manager from the DOS era.

## Highlights

- Fast dual-pane file management with editable paths
- Responsive Copy, Move, and Delete for selections exceeding 1,000 items
- Cached listings for directories containing tens of thousands of files
- Preview for images, PDF documents, and Excel workbooks
- Safe text viewing with F3 and interactive nano editing with F4
- Advanced filename and content search
- Safe batch rename and secure ZIP creation/extraction
- Ubuntu locations, mounted filesystem selection, and desktop opening
- Optional Codex, Ollama, and local shell panel
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

- installs the required Ubuntu packages, including nano;
- creates a private environment under `~/.local/share/mdir-u`;
- installs all Preview dependencies;
- creates permanent `u`, `U`, and `mdir-u` commands;
- adds `~/.local/bin` to your login PATH when necessary; and
- adds **mDIR** to the Ubuntu application menu with its own icon.

The installer can be run again at any time. It safely updates the program and
keeps personal settings.

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
| `F10` | Quit |
| `F12` | Toggle AI/file pane |
| `Ctrl+F` | Advanced search |
| `Ctrl+F3` | Toggle document preview |
| `Ctrl+H` | Toggle hidden files |
| `Shift+F10` | Open a terminal at the selected directory |
| `Alt+Enter` | Show item properties |

Copy, Move, and permanent Delete run in a background worker. Large batches
show progress and an ETA; press `Esc` or choose **Cancel** to stop after the
current top-level item.

Select a file and click it again after a clear pause to Rename. A slightly
slow double-click opens the item instead of accidentally starting Rename.

## Top shortcut bar

Click **Edit Links** to edit shortcut names, types, targets, panes, and
arguments. MDIR-U stores these links in:

```text
~/.mdir-u-shortcuts.json
```

Supported link types are `folder`, `file`, `program`, `web`, `command`, and
`action`. Placeholders include `{home}`, `{project}`, `{current}`, `{left}`,
and `{right}`.

## AI and local shell

The AI panel is optional. Install and authenticate each provider CLI
separately. `Codex Local` and `Shell` use the current Linux account's direct
permissions, so review commands before running them.

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
