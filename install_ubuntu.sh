#!/usr/bin/env sh
set -eu

sudo apt update
sudo apt install -y python3 python3-venv python3-pip xdg-utils poppler-utils zenity

python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[preview]"

printf '%s\n' "MDIR-U installed. Run: u, U, or mdir-u"
