#!/bin/bash
cd "$(dirname $(readlink -f "$0"))"
. venv/bin/activate
exec python3 i3status.py
