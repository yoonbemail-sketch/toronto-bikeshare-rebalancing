"""One-off check of usable dock capacity at the 40 study stations.

A disabled bike sits in a dock but cannot be ridden, and a disabled dock takes
no bike, so a station's usable capacity is below its dock count. Trip data does
not show this; the live GBFS station_status feed does. This saves one snapshot.

Not part of run_all.sh: the feed is live, so each run gives a new snapshot
(a November 2026 one here, outside the May-Oct 2025 study season).
Output: outputs/tables/station_status_<date>.csv
"""
from datetime import datetime, timezone

import pandas as pd
import requests

import config

STATUS_URL = config.GBFS_STATION_INFO_URL.replace("station_information", "station_status")
HEADERS = {"User-Agent": "bikeshare-portfolio-analysis"}


def main():
    feed = requests.get(STATUS_URL, headers=HEADERS, timeout=60).json()
    taken = datetime.fromtimestamp(feed["last_updated"], timezone.utc).astimezone()
    status = pd.DataFrame(feed["data"]["stations"])
    status["station_id"] = status.station_id.astype(int)
    study = pd.read_csv(config.PROCESSED / "study_stations.csv", index_col="station_id")
    s = study[["name", "capacity"]].join(status.set_index("station_id")[
        ["num_bikes_available", "num_bikes_disabled", "num_docks_available",
         "num_docks_disabled", "is_installed", "is_renting", "is_returning"]])
    s["unusable_docks"] = s.num_bikes_disabled + s.num_docks_disabled
    s.insert(0, "snapshot_time", taken.isoformat(timespec="minutes"))
    out = config.TABLES / f"station_status_{taken:%Y-%m-%d}.csv"
    s.to_csv(out)

    print(f"snapshot {taken:%Y-%m-%d %H:%M %Z}, {s.num_bikes_disabled.notna().sum()} of "
          f"{len(s)} study stations in the feed")
    print(f"  stations with >=1 disabled bike: {(s.num_bikes_disabled > 0).sum()}")
    print(f"  stations with >=1 disabled dock: {(s.num_docks_disabled > 0).sum()}")
    print(f"  disabled bikes {int(s.num_bikes_disabled.sum())}, disabled docks "
          f"{int(s.num_docks_disabled.sum())}, of {int(s.capacity.sum())} docks: "
          f"{s.unusable_docks.sum() / s.capacity.sum():.1%} unusable")
    print(f"  unusable docks per station: median {s.unusable_docks.median():.0f}, "
          f"mean {s.unusable_docks.mean():.1f}, max {int(s.unusable_docks.max())}")
    print(f"  saved {out.name}")


if __name__ == "__main__":
    main()
