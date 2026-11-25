"""Shared helpers for Phase 3: station events and the replay that counts failures.

A station's day is a time-ordered list of events: -1 when a bike is taken,
+1 when a bike is returned. Replaying the events from a starting inventory y:
  - a pickup at an empty station is a FAILED PICKUP (inventory stays 0)
  - a return at a full station is a FAILED RETURN (inventory stays at capacity)
Stations are replayed independently: a failed pickup at A does not cancel the
matching return at B. These counts are lower bounds on real failures, because
recorded trips already exclude riders who were turned away.
"""
import numpy as np
import pandas as pd

import config


ISLANDS_BOX = (43.635, -79.40, -79.34)  # same rule as clean.py: ferry-only stations


def candidates(scope):
    """Station set before the valet filter.
    downtown: the 40 busiest downtown stations chosen in Phase 1.
    wide:     the WIDE_N busiest stations system-wide (May-Oct working days),
              excluding Toronto Islands and stations with no 2025 history."""
    if scope == "downtown":
        return pd.read_csv(config.PROCESSED / "study_stations.csv", index_col="station_id")
    if scope == "wide":
        s = pd.read_csv(config.PROCESSED / "stations.csv", index_col="station_id")
        lat_max, lon_min, lon_max = ISLANDS_BOX
        island = (s.lat < lat_max) & s.lon.between(lon_min, lon_max)
        s = s[~island & (s.capacity > 0) & (s.trips_season_wkday > 0)]
        return s.nlargest(config.WIDE_N, "trips_season_wkday")
    raise SystemExit(f"Unknown scope {scope!r}; use 'downtown' or 'wide'")


def swing_exceeds_capacity(ev, stations, days):
    """Share of mornings on which a station's swing (highest minus lowest point of
    its running bike count) exceeds its capacity: no 6am level could avoid a failure."""
    share = {}
    mornings = [morning(ev, d) for d in days]
    for sid, row in stations.iterrows():
        hits = 0
        for m in mornings:
            cum = np.cumsum(np.r_[0, m.get(sid, [])])
            hits += (cum.max() - cum.min()) > row.capacity
        share[sid] = hits / len(days)
    return pd.Series(share)


def load_study(scope="downtown"):
    """Stations overnight repositioning can help: candidates minus valet-type
    stations (swing > capacity on most mornings; see README, Phase 2 finding 6)."""
    cand = candidates(scope)
    share = swing_exceeds_capacity(load_events(cand.index), cand, working_days())
    valet = share > 0.5
    return cand[~valet.reindex(cand.index).values], cand[valet.reindex(cand.index).values]


def load_events(station_ids):
    """All departures (-1) and arrivals (+1) at the given stations, May-Oct 2025."""
    t = pd.read_parquet(config.PROCESSED / f"trips_{config.TRIP_YEAR}.parquet",
                        columns=["start_id", "end_id", "start_time", "end_time"])
    # 30 April included: the day before 1 May is needed for the overnight replay
    first, last = pd.Timestamp(f"{config.TRIP_YEAR}-04-30"), pd.Timestamp(f"{config.TRIP_YEAR}-11-01")
    in_season = lambda s: (s >= first) & (s < last)  # noqa: E731
    dep = t[t.start_id.isin(station_ids) & in_season(t.start_time)]
    arr = t[t.end_id.isin(station_ids) & in_season(t.end_time)]
    ev = pd.concat([
        pd.DataFrame({"station_id": dep.start_id.astype(int), "time": dep.start_time, "d": -1}),
        pd.DataFrame({"station_id": arr.end_id.astype(int), "time": arr.end_time, "d": 1}),
    ], ignore_index=True)
    return ev.sort_values(["station_id", "time"], kind="stable").reset_index(drop=True)


def working_days():
    days = pd.date_range(f"{config.TRIP_YEAR}-05-01", f"{config.TRIP_YEAR}-10-31", freq="D")
    holidays = pd.to_datetime(config.HOLIDAYS_2025)
    return days[(days.day_of_week < 5) & ~days.isin(holidays)]


def window(ev, start, end):
    """Events in [start, end), grouped by station: {station_id: np.array of +1/-1}."""
    w = ev[(ev.time >= start) & (ev.time < end)]
    return {sid: g.d.to_numpy() for sid, g in w.groupby("station_id")}


def morning(ev, day):
    lo, hi = config.MORNING_WINDOW
    return window(ev, day + pd.Timedelta(hours=lo), day + pd.Timedelta(hours=hi))


def replay(deltas, capacity, start):
    """Replay events from one or many starting levels at once.

    deltas: array of +1/-1; start: int or array of starting inventories.
    Returns (failed_pickups, failed_returns, end_inventory), same shape as start.
    """
    inv = np.array(start, dtype=int, copy=True)
    fail_pick = np.zeros_like(inv)
    fail_ret = np.zeros_like(inv)
    for d in deltas:
        if d < 0:
            empty = inv == 0
            fail_pick += empty
            inv -= ~empty
        else:
            full = inv == capacity
            fail_ret += full
            inv += ~full
    return fail_pick, fail_ret, inv


def failure_curves(ev, stations, days):
    """g_i(y): average morning failures at station i if it starts at y bikes,
    over the given days. Returns {station_id: np.array of length C_i + 1}."""
    curves = {}
    mornings = [morning(ev, d) for d in days]
    for sid, row in stations.iterrows():
        levels = np.arange(row.capacity + 1)
        total = np.zeros(len(levels))
        for m in mornings:
            fp, fr, _ = replay(m.get(sid, []), row.capacity, levels)
            total += fp + fr
        curves[sid] = total / len(days)
    return curves


def overnight_inventory(ev, stations, day, start_fill=0.5):
    """No-rebalancing estimate of each station's bikes at 6am on `day`:
    start at `start_fill` of capacity at 6am the previous day, replay 24h of trips."""
    lo = config.MORNING_WINDOW[0]
    t1 = day + pd.Timedelta(hours=lo)
    events = window(ev, t1 - pd.Timedelta(days=1), t1)
    b = {}
    for sid, row in stations.iterrows():
        _, _, inv = replay(events.get(sid, []), row.capacity, round(start_fill * row.capacity))
        b[sid] = int(inv)
    return pd.Series(b)
