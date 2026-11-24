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
TRIP_YEAR = None  # set in Phase 1 to the most recent full year in the CKAN package

# --- Study scope -------------------------------------------------------------
N_STATIONS = 40                 # busiest downtown stations; sized for the Gurobi license
DOWNTOWN = "City Downtown Plan area: Bathurst-Don River, Lake Ontario-Bloor/CPR"  # polygon built in Phase 1
SEASON_MONTHS = range(5, 11)    # May-October, weekdays only
MORNING_WINDOW = (6, 10)        # [start, end) hour of the weekday morning peak we protect

# --- Operations ---------------------------------------------------------------
DEPOT_ADDRESS = "25 Booth Ave, Toronto"  # operator depot, per McNee & Miller (2023)
VAN_CAPACITIES = [10, 20, 30]   # ASSUMPTION: no public figure; reported as scenarios
VAN_CAPACITY = 20               # ASSUMPTION: central case
MOVE_BUDGET = None              # bikes handled per night; swept as a scenario, not fixed
ROAD_CIRCUITY = 1.3             # ASSUMPTION: road distance / straight-line distance
