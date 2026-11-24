#!/usr/bin/env bash
# Run the full pipeline end to end. Later phases are added as they are built.
set -euo pipefail
cd "$(dirname "$0")/src"
PY=../.venv/bin/python

$PY download.py   # Phase 1: raw trips, GBFS stations, neighbourhood boundaries
$PY clean.py      # Phase 1: clean, join, choose study stations, log data issues
$PY eda.py        # Phase 2: charts and per-station morning profile
