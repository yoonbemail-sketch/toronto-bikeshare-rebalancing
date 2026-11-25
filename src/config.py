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
WIDE_N = 150                    # "wide" scope: busiest stations system-wide (~51% of trip ends)
# Downtown = 13 City neighbourhoods approximating the Downtown Plan area (list in clean.py)
SEASON_MONTHS = range(5, 11)    # May-October, working days only
# Ontario statutory holidays in the season: treated like weekends, not working days
HOLIDAYS_2025 = ["2025-05-19", "2025-07-01", "2025-08-04", "2025-09-01", "2025-10-13"]
PM_WINDOW = (15, 19)            # evening peak, used to show the AM/PM reversal
MORNING_WINDOW = (6, 10)        # [start, end) hour of the weekday morning peak we protect

# --- Operations ---------------------------------------------------------------
DEPOT_ADDRESS = "25 Booth Ave, Toronto"  # operator depot, per McNee & Miller (2023)
DEPOT_LATLON = (43.6543954, -79.3410455)  # OpenStreetMap Nominatim geocode, Nov 2026
ROUTE_STATIONS = 12             # stations in the routed cluster (license-sized)
MAX_TOUR_STOPS = 12             # multi-van: most stations in one tour (keeps each route MIP fast)
DRIVE_KMH = 30                  # ASSUMPTION: van speed, as in McNee & Miller (2023); handling time excluded
VAN_CAPACITIES = [10, 20, 30]   # ASSUMPTION: no public figure; reported as scenarios
VAN_CAPACITY = 20               # ASSUMPTION: central case
MOVE_BUDGET = None              # bikes handled per night; swept as a scenario, not fixed
ROAD_CIRCUITY = 1.3             # ASSUMPTION: road distance / straight-line distance
CAPACITY_BUFFER = 0             # ASSUMPTION: docks per station treated as unusable (disabled bike
                                # or dock), floored at 0 usable; 1 and 2 run in sensitivity.py

# --- Phase 4: observed station counts ------------------------------------------
# Community archive of the live GBFS station_status feed (2025 rows from
# github.com/MaxHalford/bike-sharing-history, about every 16 minutes)
SNAPSHOTS_URL = ("https://github.com/ThatRandomUser23/toronto-bikeshare-data/releases/"
                 "download/data-latest/toronto_bikeshare_snapshots.parquet")
NIGHT_START = 21                # 9pm the evening before: start of the overnight window
SNAPSHOT_MAX_AGE = 16           # minutes: a state is read from the nearest snapshot this close
MOVE_THRESHOLD = 3              # bikes: an unexplained change this large counts as an operator move
