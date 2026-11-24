"""Phase 1b: clean trips, build the station table, pick the study stations.

Inputs  (data/raw/):  trips_<year>/*.csv, station_information.json, neighbourhoods.geojson
Outputs:
  data/processed/trips_<year>.parquet   cleaned trips, joined to stations by ID
  data/processed/stations.csv           every station in the GBFS feed + 2025 activity
  data/processed/study_stations.csv     the N busiest downtown stations
  outputs/tables/data_issues.csv        every cleaning step and how many rows it touched
  outputs/figures/study_area_map.png    downtown boundary and selected stations
"""
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.path import Path

import config

# Downtown = these City of Toronto neighbourhoods (158-neighbourhood model).
# Together they approximate the Downtown Plan area: Bathurst St to the Don River,
# Lake Ontario to Bloor St. The City does not publish the Plan boundary as open data.
DOWNTOWN_NEIGHBOURHOODS = [
    "Yonge-Bay Corridor", "Wellington Place", "Harbourfront-CityPlace",
    "St Lawrence-East Bayfront-The Islands", "Downtown Yonge East", "Church-Wellesley",
    "Bay-Cloverhill", "Kensington-Chinatown", "University", "Moss Park", "Regent Park",
    "Cabbagetown-South St.James Town", "North St.James Town",
]

# Toronto Islands bounding box (lat_max, lon_min, lon_max): south of the harbour,
# between the Western and Eastern Gaps. Excludes Etobicoke and Ontario Place lakeshore.
ISLANDS_BOX = (43.635, -79.40, -79.34)

issues = []  # (step, rows affected, action, note)


def log(step, n, action, note=""):
    issues.append({"step": step, "rows": int(n), "action": action, "note": note})
    print(f"  {step}: {n:,} ({action})")


# ---------------------------------------------------------------- trips ------
def read_month(path):
    """Jan-Oct 2025 files are Windows-1252; Nov-Dec are UTF-8. Try UTF-8 first."""
    cols = ["Trip_Id", "Trip_Duration", "Start_Station_Id", "Start_Time",
            "Start_Station_Name", "End_Station_Id", "End_Time", "Bike_Id",
            "User_Type", "Bike_Model"]
    try:
        return pd.read_csv(path, usecols=cols, dtype=str, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(path, usecols=cols, dtype=str, encoding="cp1252")


def load_trips(year):
    files = sorted((config.RAW / f"trips_{year}").glob("*.csv"))
    raw = pd.concat([read_month(f) for f in files], ignore_index=True)
    log("raw rows", len(raw), "loaded", f"{len(files)} monthly files")
    # End_Station_Name is not even read: Jan-Oct it is a copy of Start_Station_Name.
    log("End_Station_Name wrong (Jan-Oct)", 0, "column ignored",
        "Jan-Oct end names copy the start name; end IDs verified via implied speed")

    t = pd.DataFrame({
        "trip_id": pd.to_numeric(raw.Trip_Id, errors="coerce").astype("Int64"),
        "duration_s": pd.to_numeric(raw.Trip_Duration, errors="coerce"),
        "start_id": pd.to_numeric(raw.Start_Station_Id, errors="coerce").astype("Int64"),
        "end_id": pd.to_numeric(raw.End_Station_Id, errors="coerce").astype("Int64"),
        "start_time": pd.to_datetime(raw.Start_Time, errors="coerce"),
        "end_time": pd.to_datetime(raw.End_Time, errors="coerce"),
        "bike_id": raw.Bike_Id,
        "user_type": raw.User_Type.astype("category"),
        "bike_model": raw.Bike_Model.astype("category"),
        "start_name_trips": raw.Start_Station_Name.str.strip(),  # for name checks only
    })
    return t


def clean_trips(t):
    dup = t.trip_id.duplicated()
    log("duplicate trip_id", dup.sum(), "dropped")
    t = t[~dup]

    miss = t[["start_id", "end_id", "start_time", "end_time"]].isna().any(axis=1)
    log("missing station ID or timestamp", miss.sum(), "dropped",
        "mostly trips with no end station (bike not returned to a dock)")
    t = t[~miss]

    # Duration field vs timestamps: trust timestamps, they drive the hourly analysis
    gap = ((t.end_time - t.start_time).dt.total_seconds() - t.duration_s).abs()
    log("duration field disagrees with timestamps by >60 s", (gap > 60).sum(), "kept",
        "duration recomputed from timestamps")
    t = t.assign(duration_s=(t.end_time - t.start_time).dt.total_seconds())

    short = t.duration_s < 60
    log("trip shorter than 60 s", short.sum(), "dropped",
        "false starts / immediate re-docks, standard industry filter")
    t = t[~short]

    long_ = t.duration_s > 24 * 3600
    log("trip longer than 24 h", long_.sum(), "dropped", "likely lost or unreturned bikes")
    t = t[~long_]
    return t


# ------------------------------------------------------------- stations ------
def load_neighbourhoods():
    g = json.loads((config.RAW / "neighbourhoods.geojson").read_text())
    shapes = {}
    for f in g["features"]:
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        shapes[f["properties"]["AREA_NAME"]] = [Path(np.array(p[0])) for p in polys]
    return shapes


def neighbourhood_of(lon, lat, shapes):
    pts = np.column_stack([lon, lat])
    out = np.full(len(pts), None, dtype=object)
    for name, paths in shapes.items():
        for p in paths:
            out[p.contains_points(pts) & (out == None)] = name  # noqa: E711
    return out


def build_stations(shapes):
    feed = json.loads((config.RAW / "station_information.json").read_text())
    s = pd.DataFrame(feed["data"]["stations"])
    s = pd.DataFrame({
        "station_id": pd.to_numeric(s.station_id).astype("Int64"),
        "name": s.name.str.strip(),
        "lat": s.lat, "lon": s.lon,
        "capacity": s.capacity,
        "is_valet": s.get("is_valet_station", False).fillna(False).astype(bool),
    })
    s["neighbourhood"] = neighbourhood_of(s.lon.values, s.lat.values, shapes)
    s["downtown"] = s.neighbourhood.isin(DOWNTOWN_NEIGHBOURHOODS)
    return s


def add_activity(s, t):
    """2025 trip counts per station: all year, and May-Oct weekdays (the study period)."""
    season = t.start_time.dt.month.isin(config.SEASON_MONTHS) & (t.start_time.dt.day_of_week < 5)
    counts = pd.DataFrame({
        "starts_2025": t.start_id.value_counts(),
        "ends_2025": t.end_id.value_counts(),
        "starts_season_wkday": t.loc[season, "start_id"].value_counts(),
        "ends_season_wkday": t.loc[season, "end_id"].value_counts(),
    }).fillna(0).astype(int)
    s = s.merge(counts, left_on="station_id", right_index=True, how="left")
    s[counts.columns] = s[counts.columns].fillna(0).astype(int)
    s["trips_season_wkday"] = s.starts_season_wkday + s.ends_season_wkday

    # Name used in 2025 trip data, to spot IDs that were moved or reused since 2025
    trip_names = t.groupby("start_id").start_name_trips.agg(lambda x: x.mode().iat[0])
    s["name_in_trips"] = s.station_id.map(trip_names)
    # ignore the "- SMART" suffix and punctuation when comparing names
    norm = lambda x: (x.str.lower().str.replace("- smart", "", regex=False)  # noqa: E731
                      .str.replace(r"[^a-z0-9]", "", regex=True))
    s["name_matches_trips"] = norm(s.name) == norm(s.name_in_trips.fillna(""))
    return s


def check_join(t, s):
    """Trips whose station ID is not in today's GBFS feed (station removed/renumbered)."""
    known = set(s.station_id)
    miss_start, miss_end = ~t.start_id.isin(known), ~t.end_id.isin(known)
    either = miss_start | miss_end
    log("station ID not in current GBFS feed", either.sum(), "kept, flagged",
        f"{t.loc[miss_start, 'start_id'].nunique()} start IDs; no coordinates, so "
        "these stations cannot enter the study set")
    gone = (t[miss_start].groupby("start_id")
            .agg(name=("start_name_trips", lambda x: x.mode().iat[0]),
                 trips=("start_id", "size"),
                 first_seen=("start_time", "min"), last_seen=("start_time", "max"))
            .sort_values("trips", ascending=False))
    gone.to_csv(config.TABLES / "stations_missing_from_gbfs.csv")
    return t.assign(start_known=~miss_start, end_known=~miss_end)


# ----------------------------------------------------------------- study -----
def pick_study_stations(s):
    """Busiest downtown stations that exist today (need capacity) and had 2025 trips.

    Toronto Island stations are excluded: they are seasonal and reachable only by
    ferry, so overnight van rebalancing does not apply. (They are also absent from a
    winter GBFS snapshot; the explicit rule keeps a summer rerun consistent.)
    """
    lat_max, lon_min, lon_max = ISLANDS_BOX
    island = (s.lat < lat_max) & s.lon.between(lon_min, lon_max)
    log("Toronto Islands stations in feed", island.sum(), "excluded from study set",
        "ferry access only; seasonal, so absent from a winter snapshot")
    new = s.downtown & (s.trips_season_wkday == 0)
    log("downtown stations with no 2025 trips", new.sum(), "excluded from study set",
        "opened after 2025 (e.g. 7004 University Ave / Elm St); no history to model")
    cand = s[s.downtown & ~island & (s.capacity > 0) & ~new]
    study = cand.nlargest(config.N_STATIONS, "trips_season_wkday")
    share = study.trips_season_wkday.sum() / s.trips_season_wkday.sum()
    print(f"  {len(study)} study stations = {share:.1%} of May-Oct weekday trip ends "
          f"(of {len(cand)} downtown stations)")
    return study


def plot_map(s, study, shapes):
    fig, ax = plt.subplots(figsize=(9, 7))
    for name in DOWNTOWN_NEIGHBOURHOODS:
        for p in shapes[name]:
            ax.fill(*p.vertices.T, color="#dbe7f3", ec="#7a9cc6", lw=0.6)
    near = s[s.lon.between(-79.45, -79.33) & s.lat.between(43.62, 43.69)]
    ax.scatter(near.lon, near.lat, s=6, c="#b0b0b0", label="Other stations")
    ax.scatter(study.lon, study.lat, s=study.capacity * 2, c="#d1495b", ec="white", lw=0.5,
               label=f"Study stations (n={len(study)}, size = docks)")
    ax.set(xlim=(-79.43, -79.345), ylim=(43.628, 43.68), aspect=1 / np.cos(np.radians(43.65)),
           title="Study area: downtown Toronto neighbourhoods and the 40 busiest stations\n"
                 "(busiest by May-Oct 2025 weekday trip starts + ends)")
    ax.set_xticks([]); ax.set_yticks([])
    ax.legend(loc="lower right", frameon=False)
    fig.tight_layout()
    fig.savefig(config.FIGURES / "study_area_map.png", dpi=150)


def main():
    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    year = config.TRIP_YEAR
    print("Trips")
    t = clean_trips(load_trips(year))
    print("Stations")
    shapes = load_neighbourhoods()
    s = build_stations(shapes)
    t = check_join(t, s)
    s = add_activity(s, t)
    zero = (s.capacity <= 0).sum()
    log("GBFS station with capacity 0", zero, "excluded from study set")
    study = pick_study_stations(s)
    log("study stations whose 2025 trip name differs from current GBFS name",
        (~study.name_matches_trips).sum(), "reviewed",
        "see study_stations.csv: name vs name_in_trips")

    # Join: attach start/end station attributes by ID
    attrs = s.set_index("station_id")[["neighbourhood", "downtown"]]
    t = t.join(attrs.add_prefix("start_"), on="start_id").join(attrs.add_prefix("end_"), on="end_id")
    t = t.drop(columns="start_name_trips")

    t.to_parquet(config.PROCESSED / f"trips_{year}.parquet", index=False)
    s.to_csv(config.PROCESSED / "stations.csv", index=False)
    study.to_csv(config.PROCESSED / "study_stations.csv", index=False)
    study.to_csv(config.TABLES / "study_stations.csv", index=False)  # small; committed
    log("clean trips written", len(t), "saved")
    pd.DataFrame(issues).to_csv(config.TABLES / "data_issues.csv", index=False)
    plot_map(s, study, shapes)
    print("Done.")


if __name__ == "__main__":
    main()
