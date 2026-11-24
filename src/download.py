"""Phase 1a: download raw data.

- Trip data for one year from the City of Toronto Open Data portal (CKAN API).
- Current station list (location, capacity) from the Bike Share Toronto GBFS feed.

Files land in data/raw/. Rerunning skips files that are already downloaded.
Usage: python src/download.py [year]
"""
import json
import sys
import zipfile
from datetime import datetime, timezone

import requests

import config

HEADERS = {"User-Agent": "bikeshare-portfolio-analysis"}


def find_trip_resource(year: int) -> dict:
    """Look up the zip for `year` in the CKAN package listing."""
    pkg = requests.get(config.CKAN_PACKAGE_URL, headers=HEADERS, timeout=60).json()["result"]
    for res in pkg["resources"]:
        if res["name"] == f"bikeshare-ridership-{year}.zip":
            return res
    available = [r["name"] for r in pkg["resources"]]
    raise SystemExit(f"No trip file for {year}. Available: {available}")


def download(url: str, dest) -> None:
    if dest.exists():
        print(f"  already have {dest.name}")
        return
    print(f"  downloading {url}")
    with requests.get(url, headers=HEADERS, stream=True, timeout=600) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        tmp.rename(dest)


def main(year: int) -> None:
    config.RAW.mkdir(parents=True, exist_ok=True)

    # 1. Trips: one zip of monthly CSVs per year
    print(f"Trip data {year}")
    res = find_trip_resource(year)
    zip_path = config.RAW / f"bikeshare-ridership-{year}.zip"
    download(res["url"], zip_path)
    out_dir = config.RAW / f"trips_{year}"
    if not out_dir.exists():
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(out_dir)
    print(f"  extracted to {out_dir.relative_to(config.ROOT)}")

    # 2. Stations: GBFS is a live feed, so save a dated snapshot
    print("GBFS station_information")
    feed = requests.get(config.GBFS_STATION_INFO_URL, headers=HEADERS, timeout=60).json()
    stamp = datetime.fromtimestamp(feed["last_updated"], tz=timezone.utc).strftime("%Y-%m-%d")
    dest = config.RAW / "station_information.json"
    dest.write_text(json.dumps(feed))
    print(f"  saved {len(feed['data']['stations'])} stations (feed timestamp {stamp} UTC)")

    # 3. Neighbourhood boundaries (used to define "downtown")
    print("Neighbourhood boundaries")
    download(config.NEIGHBOURHOODS_URL, config.RAW / "neighbourhoods.geojson")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else config.TRIP_YEAR)
