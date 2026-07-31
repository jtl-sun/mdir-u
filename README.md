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
- Cached and batched listings for directories with tens of thousands of files
- Preview for images, PDF documents, and Excel workbooks
- Safe F3 View and F4 Edit for bounded text files
- AI panel for Codex, Codex Quick, Codex Local, Ollama, and other CLIs
- Direct local Bash/Shell commands outside the Codex sandbox
- Ubuntu locations and mounted filesystem selection
- Total Commander-inspired dark theme
- Configurable top shortcut bar with an in-app Link Manager
- English UI with Unicode filename support

Preview is disabled at startup. Press `Ctrl+F3` to show or hide it.

## Ubuntu installation

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip xdg-utils poppler-utils zenity

git clone https://github.com/jtl-sun/mdir-u.git
cd mdir-u
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[preview]"
```

Start MDIR-U with any of these case-sensitive Linux commands:

```bash
u
U
mdir-u
```

For a local source checkout, you can also run:

```bash
./start_mdir_u.sh
python3 -m mdir_u
```

## Controls

| Key | Action |
| --- | --- |
| `Tab`, `Left`, `Right` | Switch active pane |
| `Enter` | Open directory or file |
| `Backspace` | Parent directory |
| `Space` | Mark or unmark |
| `F2` | Rename |
| `F3` | View a supported text file |
| `F4` | Edit a supported text file |
| `F5` | Copy |
| `F6` | Move |
| `F7` | Create directory |
| `F8` | Delete |
| `F9` | Select a location or mount |
| `F10` | Quit |
| `F12` | Toggle AI/file pane |
| `Ctrl+F` | Advanced search |
| `Ctrl+F3` | Toggle document preview |
| `Ctrl+H` | Toggle hidden files |
| `Shift+F10` | Open a terminal at the selected directory |

## Top Shortcut Bar

The shortcut bar sits below the title line and can open folders in a chosen
pane, launch files or programs, open websites, run shell commands, or trigger
selected MDIR-U actions.

Click **Edit Links** to open the built-in Link Manager. You can edit names,
types, targets, panes, and arguments; add or remove links; change their order;
and browse for files or folders. **Save** updates the bar immediately.

MDIR-U stores the links in:

```text
~/.mdir-u-shortcuts.json
```

The optional Browse buttons use `zenity` or `kdialog` on Linux. The supported
link types are `folder`, `file`, `program`, `web`, `command`, and `action`.
Placeholders include `{home}`, `{project}`, `{current}`, `{left}`, and
`{right}`.

## AI and local shell

The AI panel is optional. Install and authenticate each provider's CLI
separately. Codex uses workspace restrictions by default. `Codex Local` and
`Shell` can directly modify files or install software with the permissions of
the current Linux account, so review commands before running them.

## WSL notes

MDIR-U runs in WSL Ubuntu. Windows drives appear under `/mnt`, such as
`/mnt/c` and `/mnt/s`. Linux GUI actions such as opening a document require
WSLg or another configured desktop opener.

## License

MDIR-U is released under the [MIT License](LICENSE). Attribution and the
license notice must be preserved when redistributing the software.
