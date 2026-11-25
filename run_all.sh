#!/usr/bin/env bash
# Run the full pipeline end to end.
# Solver: HiGHS by default; SOLVER=gurobi ./run_all.sh to use Gurobi instead.
set -euo pipefail
cd "$(dirname "$0")/src"
PY=../.venv/bin/python

$PY download.py   # Phase 1: raw trips, GBFS stations, neighbourhood boundaries
$PY clean.py      # Phase 1: clean, join, choose study stations, log data issues
$PY eda.py        # Phase 2: charts and per-station morning profile
$PY rebalance.py  # Phase 3a: overnight plans (MIP) vs baselines on held-out mornings
$PY routing.py    # Phase 3b: van route for one cluster of the example plan
$PY solver_check.py  # HiGHS vs Gurobi on a sample (skipped if Gurobi is absent)
