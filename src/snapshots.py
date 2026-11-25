"""Phase 4 data: observed bikes and free docks per station, 2025 season.

Trip data shows journeys but never how many bikes a station held. A community
archive of the live GBFS station_status feed does: a snapshot of every station
about every 16 minutes since April 2024. The 2025 rows come from
github.com/MaxHalford/bike-sharing-history, and
github.com/ThatRandomUser23/toronto-bikeshare-data combines them into one
Parquet file. The station data is published by Bike Share Toronto under the
Open Government Licence - Toronto.

Downloads that file once (926 MB, not committed) and keeps 30 Apr - 31 Oct 2025
for the downtown and wide station sets, in local time like the trips.
Output: data/processed/snapshots_2025.parquet
"""
import pandas as pd

import config
import morning as M
from download import download

TZ = "America/Toronto"
COLUMNS = ["ts", "station_id", "capacity", "bikes", "disabled", "docks", "docks_disabled"]


def main():
    dest = config.RAW / "station_snapshots" / "toronto_bikeshare_snapshots.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    download(config.SNAPSHOTS_URL, dest)

    ids = sorted(set(M.candidates("downtown").index) | set(M.candidates("wide").index))
    year = config.TRIP_YEAR
    lo, hi = (pd.Timestamp(f"{year}-{md}", tz=TZ).tz_convert("UTC") for md in ("04-30", "11-01"))
    s = pd.read_parquet(dest, columns=COLUMNS,
                        filters=[("ts", ">=", lo), ("ts", "<", hi), ("station_id", "in", ids)])
    # Archive time is UTC; trips are local wall-clock time
    s.insert(0, "t", s.pop("ts").dt.tz_convert(TZ).dt.tz_localize(None).astype("datetime64[us]"))
    s = s.sort_values(["station_id", "t"]).reset_index(drop=True)
    out = config.PROCESSED / f"snapshots_{year}.parquet"
    s.to_parquet(out, index=False)
    print(f"  {len(s):,} rows, {s.station_id.nunique()} stations, {s.t.nunique():,} snapshot times, "
          f"{s.t.min():%Y-%m-%d %H:%M} to {s.t.max():%Y-%m-%d %H:%M}; saved {out.name}")


if __name__ == "__main__":
    main()
