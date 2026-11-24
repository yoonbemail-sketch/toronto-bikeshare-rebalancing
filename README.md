# Toronto Bike Share: Overnight Rebalancing with Optimization

> **Status:** Phase 1 (data) complete. Analysis and results sections are
> placeholders and will be filled with real numbers as each phase is completed.

## The problem in one paragraph

Each weekday morning, commuters empty some downtown Bike Share stations and fill
others. Riders then find no bike to take, or no dock to return to. This project
uses a year of public trip data to measure that imbalance. It then builds two
Gurobi models: one decides how many bikes each station should hold at the start
of the morning, and one routes a van to move them. The result is compared with
doing nothing and with a simple rule of thumb.

## Headline results

_To be added in Phase 3: morning failures avoided against bikes moved, on
held-out days._

## Data

| Source | What it gives | Link |
|---|---|---|
| City of Toronto Open Data | Every trip: start/end station, start/end time, user type | [Bike Share Toronto Ridership Data](https://open.toronto.ca/dataset/bike-share-toronto-ridership-data/) |
| Bike Share Toronto GBFS feed | Station location and dock capacity | [station_information](https://tor.publicbikesystem.net/ube/gbfs/v1/en/station_information) |
| City of Toronto Open Data | 158 neighbourhood boundaries, used to define "downtown" | [Neighbourhoods](https://open.toronto.ca/dataset/neighbourhoods/) |

**Year used: 2025**, the most recent full year on the portal (checked Nov 2026).
7.81 million raw trips; 7.79 million after cleaning.

### Study stations

Downtown means 13 City neighbourhoods that together approximate the Downtown Plan
area: Bathurst St to the Don River, and Lake Ontario to Bloor St. The City does
not publish the Plan boundary itself as open data. From the downtown stations
that still exist and had 2025 trips, the 40 with the most May–Oct weekday trip
starts plus ends were selected. Together they account for **18.7%** of those
trip ends across the whole system.
List: [outputs/tables/study_stations.csv](outputs/tables/study_stations.csv).

![Study area](outputs/figures/study_area_map.png)

### Data issues found

Each issue is handled in [src/clean.py](src/clean.py) and counted in
[outputs/tables/data_issues.csv](outputs/tables/data_issues.csv).

| Issue | Size | Handling |
|---|---|---|
| **End station names are wrong for Jan–Oct.** `End_Station_Name` is a copy of `Start_Station_Name` on 100% of rows, even when the end station ID differs. Nov–Dec are correct. | 10 of 12 files | Names ignored; stations are joined by ID only. The end IDs were checked: the implied straight-line riding speed has a median of 9–10 km/h in every month, including the correct Nov–Dec files. Wrong IDs would make this erratic. |
| Mixed file encodings: Jan–Oct are Windows-1252, Nov–Dec are UTF-8 | 10 of 12 files | Read as UTF-8, falling back to Windows-1252 |
| Missing end station or end time (bike not returned to a dock) | 6,957 trips (0.09%) | Dropped |
| Trips under 60 seconds (false starts, immediate re-docks) | 16,889 (0.22%) | Dropped |
| Trips over 24 hours | 12 | Dropped |
| `Trip_Duration` disagrees with the timestamps by more than 60 s | 265 | Duration recomputed from timestamps |
| **The station list is a current snapshot (Nov 2026), not 2025.** 64 station IDs used in 2025 are not in it. | 785,885 trips (10.1%) touch one | Trips kept and flagged. These stations have no coordinates or capacity, so they cannot be study stations. |
| ↳ Toronto Island stations are seasonal, so they are absent from a winter snapshot | e.g. Centre Island Ferry Dock | Excluded by rule in any case: ferry access only, so no overnight vans |
| ↳ Downtown stations removed after 2025. 7047 University Ave / Gerrard St W would have ranked about 8th. 7004 University Ave / Elm St, two blocks away, appears in the feed with no 2025 trips and may have replaced it (not confirmed). | 1 station that would have made the top 40 | Excluded; the study set is limited to stations that exist today |
| Downtown stations with no 2025 trips (opened later) | 20 | Excluded: no history to model |
| Dock capacity comes from the 2026 feed and may differ from 2025 | unknown | Accepted as a limitation |

## Approach

1. **Data:** download, clean, and join trips to stations by station ID.
2. **Exploratory analysis:** when and where trips happen, and which stations
   empty out or fill up during the morning and evening peaks.
3. **Optimization:**
   - *Overnight repositioning (MIP):* choose each station's starting inventory
     to minimise expected morning failures, given a budget of bikes moved.
   - *Van routing (MIP):* for one cluster, the stop order and loads for a
     capacitated van.
4. **Evaluation:** replay held-out weekday mornings under three policies:
   no rebalancing, a fill-to-50% rule, and the optimised plan.

The full plan, with the formulations in mathematical notation, is in
[docs/PLAN.md](docs/PLAN.md). How Bike Share Toronto rebalances today, and how
this model relates to it, is in [docs/CURRENT_PRACTICE.md](docs/CURRENT_PRACTICE.md).

## Key findings from the data

_To be added in Phase 2._

## Assumptions

Every assumption is set in [src/config.py](src/config.py) and can be changed there.

| Assumption | Value | Why |
|---|---|---|
| Study subset | 40 busiest downtown stations (13 City neighbourhoods; see Data) | Must fit the free Gurobi license (≤ 2,000 variables/constraints) |
| Season | Weekdays, May–October | Peak season, when imbalance is worst |
| Protected window | Weekdays, 6–10am | Commuter peak; confirmed or revised in Phase 2 |
| Van capacity | 10, 20 and 30 bikes (20 central) | No public figure exists, so it is run as scenarios ([current practice](docs/CURRENT_PRACTICE.md)) |
| Depot | 25 Booth Ave | Operator depot used in the prior Toronto study |
| Road distance | 1.3 × straight-line distance | Standard circuity approximation; no road network used |
| Overnight starting inventory | Simulated from the previous day's trips | No inventory history is published; see [PLAN.md](docs/PLAN.md) |
| Scope | Overnight rebalancing only | The real operation runs 24/7; stations overnight moves cannot fix are flagged for daytime/valet service |

## Limitations

- **Censored demand:** trip data records only completed trips, so riders turned
  away by an empty station are invisible. Failures avoided are therefore a lower
  bound.
- **No historical inventory:** bikes per station over time are not published,
  so the overnight starting level is estimated.
- **Stations modelled independently** in the morning replay.

## How to run

```bash
.venv/bin/pip install -r requirements.txt
./run_all.sh          # download → clean (EDA and optimisation added in later phases)
```

Requires a Gurobi license; the free restricted license is enough. The first run
downloads about 230 MB and takes a few minutes.

## Repository layout

```
data/raw/          downloaded files (not committed)
data/processed/    cleaned tables (not committed; regenerated by the scripts)
src/               pipeline scripts; config.py holds paths and assumptions
outputs/figures/   charts (committed)
outputs/tables/    result tables (committed)
docs/PLAN.md       questions, formulations, evaluation design
```
