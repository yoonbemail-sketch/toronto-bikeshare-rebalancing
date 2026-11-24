"""Paths and modelling assumptions, kept in one place.

Every number marked ASSUMPTION is a judgement call, not data. Each one is
listed in the README's Assumptions table; change it here and rerun.
"""
from pathlib import Path

# --- Paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
FIGURES = ROOT / "outputs" / "figures"
TABLES = ROOT / "outputs" / "tables"

# --- Data sources ------------------------------------------------------------
CKAN_PACKAGE_URL = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show"
    "?id=bike-share-toronto-ridership-data"
)
GBFS_STATION_INFO_URL = "https://tor.publicbikesystem.net/ube/gbfs/v1/en/station_information"
NEIGHBOURHOODS_URL = (  # City of Toronto 158 neighbourhoods, WGS84
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/fc443770-ef0a-4025-9c2c-2cb558bfab00"
    "/resource/0719053b-28b7-48ea-b863-068823a93aaa/download/neighbourhoods-4326.geojson"
)
TRIP_YEAR = 2025               # most recent full year on the portal (checked 2026-11-24)

# --- Study scope -------------------------------------------------------------
N_STATIONS = 40                 # busiest downtown stations; sized for the Gurobi license
# Downtown = 13 City neighbourhoods approximating the Downtown Plan area (list in clean.py)
SEASON_MONTHS = range(5, 11)    # May-October, weekdays only
MORNING_WINDOW = (6, 10)        # [start, end) hour of the weekday morning peak we protect

# --- Operations ---------------------------------------------------------------
DEPOT_ADDRESS = "25 Booth Ave, Toronto"  # operator depot, per McNee & Miller (2023)
VAN_CAPACITIES = [10, 20, 30]   # ASSUMPTION: no public figure; reported as scenarios
VAN_CAPACITY = 20               # ASSUMPTION: central case
MOVE_BUDGET = None              # bikes handled per night; swept as a scenario, not fixed
ROAD_CIRCUITY = 1.3             # ASSUMPTION: road distance / straight-line distance
