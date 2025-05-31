#!/bin/bash

# can't install pydbus through pip
python -m venv --system-site-packages venv
. venv/bin/activate
pip install -r requirements.txt
