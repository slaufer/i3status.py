#!/bin/bash
cd "$(dirname $(readlink "$0"))"
. venv/bin/activate
exec python3 i3status.py
